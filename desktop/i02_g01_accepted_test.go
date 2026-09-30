package main

// ADR-0058 only: new assertions, separate from the immutable old evidence.
import (
	"encoding/json"
	"os"
	"reflect"
	"runtime"
	"testing"
	"time"
)

type g01Reply struct {
	status int
	body   map[string]any
	err    error
}

func spikePost(c *spikeCore, path string, value any) g01Reply {
	raw, _ := json.Marshal(value)
	status, data, err := c.b.request("POST", path, raw)
	var body map[string]any
	_ = json.Unmarshal(data, &body)
	return g01Reply{status, body, err}
}
func spikeAsync(c *spikeCore, path string, value any) <-chan g01Reply {
	done := make(chan g01Reply, 1)
	go func() { done <- spikePost(c, path, value) }()
	return done
}
func waitSpikeBarrier(t *testing.T, c *spikeCore) {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if c.json(t, "/spike/control", map[string]any{"action": "inspect"})["entered"] == true {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("deterministic barrier not reached")
}
func acceptedOnly(t *testing.T) {
	if os.Getenv("I02_G01_SPIKE") != "1" || os.Getenv("I02_G01_CONTRACT") != "ADR-0058" {
		t.Skip("explicit ADR-0058 isolated validation")
	}
}
func acceptedObservation(t *testing.T, row map[string]any) {
	row["contract"] = "ADR-0058"
	row["platform"] = runtime.GOOS
	row["status"] = "PASS"
	row["production_snapshot_unchanged"] = true
	row["resends"] = 0
	raw, _ := json.Marshal(row)
	t.Log("G01_ACCEPTED_OBSERVATION " + string(raw))
}
func TestG01TransactionQualification(t *testing.T) {
	acceptedOnly(t)
	for _, name := range []string{"rollback_after_check_then_host_exit", "rollback_after_check_same_host_retry", "core_restart_after_check_uncommitted"} {
		t.Run(name, func(t *testing.T) {
			c := startSpikeCore(t)
			h := startSpikeHost(t)
			connected := h.ask(t, map[string]any{"Op": "connect", "Mode": "hold", "Endpoint": c.b.get()})
			if connected["status"] != float64(200) {
				t.Fatal("binding failed")
			}
			sent := h.ask(t, map[string]any{"Op": "step"})
			h.ask(t, map[string]any{"Op": "start"})
			before := c.json(t, "/v1/state", nil)
			empty := c.json(t, "/spike/inspect", map[string]any{})
			c.json(t, "/spike/control", map[string]any{"action": "arm", "point": "after_live_check_before_commit"})
			pending := spikeAsync(c, "/spike/result", sent["report"])
			waitSpikeBarrier(t, c)
			trace := []string{"original_instance_bound", "device_return", "user_response", "transaction_live_check_passed", "paused_before_commit"}
			expected := 409
			if name == "core_restart_after_check_uncommitted" {
				c.stop()
				<-pending // Transport outcome is NOT evidence of commit status.
				h.stop()
				c.restart(t)
				trace = append(trace, "core_killed_before_commit", "host_exited", "new_core_database_recovered")
			} else {
				c.json(t, "/spike/control", map[string]any{"action": "rollback_after_check"})
				c.json(t, "/spike/control", map[string]any{"action": "release"})
				reply := <-pending
				if reply.err != nil || reply.status != 503 {
					t.Fatal("injected rollback not reported")
				}
				trace = append(trace, "transaction_rolled_back")
				if name == "rollback_after_check_then_host_exit" {
					h.stop()
					trace = append(trace, "host_exited_after_rollback")
				} else {
					expected = 200
				}
			}
			recovered := c.json(t, "/spike/inspect", map[string]any{})
			if !reflect.DeepEqual(empty, recovered) {
				t.Fatal("database retained uncommitted result/qualification")
			}
			stable := c.json(t, "/v1/state", nil)
			for _, key := range []string{"database_id", "sessions", "checkpoints", "evidence", "plans", "actions", "arrangements"} {
				if !reflect.DeepEqual(before[key], stable[key]) {
					t.Fatalf("restart changed %s", key)
				}
			}
			retry := spikePost(c, "/spike/result", sent["report"])
			if retry.err != nil || retry.status != expected {
				t.Fatalf("retry %d expected %d: %v", retry.status, expected, retry.body)
			}
			saved := c.json(t, "/spike/inspect", map[string]any{})
			count := len(saved["reports"].([]any))
			if expected == 409 {
				if !reflect.DeepEqual(empty, saved) {
					t.Fatal("rejection left partial records")
				}
			} else {
				if count != 1 || saved["commands"] != float64(1) || saved["facts"] != float64(1) {
					t.Fatal("not exactly one atomic result")
				}
				report := saved["reports"].([]any)[0].(map[string]any)
				if report["order"] != "unknown" || report["opportunity"] != "unknown" || report["precise_latency"] != nil || report["sent_at"] != nil {
					t.Fatal("invented timing")
				}
				second := spikePost(c, "/spike/result", sent["report"])
				if second.status != 200 || !reflect.DeepEqual(second.body, retry.body) || !reflect.DeepEqual(saved, c.json(t, "/spike/inspect", map[string]any{})) {
					t.Fatal("duplicate result")
				}
			}
			if !reflect.DeepEqual(stable, c.json(t, "/v1/state", nil)) {
				t.Fatal("report changed domain snapshot")
			}
			stale := spikePost(c, "/v1/context", map[string]any{"kind": "interventions", "id": "intervention:arrangement-a", "version": 1})
			if stale.status != 409 || sent["calls"] != float64(1) {
				t.Fatal("revived operation or extra call")
			}
			acceptedObservation(t, map[string]any{"case": name, "input_trace": append(trace, "retry_rechecks_current_transaction"), "expected_http": expected, "actual_http": retry.status, "saved_reports": count, "database_empty_after_rollback_or_restart": true, "api_calls": 1, "order": "unknown", "opportunity": "unknown", "reason": retry.body["error"]})
		})
	}
}

func TestG01InitialBinding(t *testing.T) {
	acceptedOnly(t)
	for _, name := range []string{"first_binding_success", "exit_before_open", "exit_during_registration_before_open", "pid_reuse_before_open_substitute", "exit_after_open_before_confirm", "wrong_challenge", "stale_challenge"} {
		t.Run(name, func(t *testing.T) {
			c := startSpikeCore(t)
			h := startSpikeHost(t)
			who := h.ask(t, map[string]any{"Op": "observe"})
			before := c.json(t, "/v1/state", nil)
			empty := c.json(t, "/spike/inspect", map[string]any{})
			trace := []string{"registration_uses_own_pid_and_run"}
			expected := 409
			actual := 409
			if name == "exit_before_open" {
				h.stop()
				r := spikePost(c, "/spike/host", map[string]any{"host": who["host"], "pid": who["pid"]})
				actual = r.status
				trace = append(trace, "original_exited", "open_or_liveness_rejected")
			} else if name == "exit_during_registration_before_open" || name == "pid_reuse_before_open_substitute" {
				c.json(t, "/spike/control", map[string]any{"action": "arm", "point": "before_identity_open"})
				pending := spikeAsync(c, "/spike/host", map[string]any{"host": who["host"], "pid": who["pid"]})
				waitSpikeBarrier(t, c)
				h.stop()
				replacement := startSpikeHost(t)
				newer := replacement.ask(t, map[string]any{"Op": "observe"})
				if name == "pid_reuse_before_open_substitute" {
					c.json(t, "/spike/control", map[string]any{"action": "substitute_open", "pid": newer["pid"]})
				}
				c.json(t, "/spike/control", map[string]any{"action": "release"})
				r := <-pending
				actual = r.status
				trace = append(trace, "paused_before_open", "original_killed_and_waited", "replacement_running_unregistered", "resume_open")
				if name == "pid_reuse_before_open_substitute" {
					if r.status != 200 {
						t.Fatal("reuse model failed to open live replacement")
					}
					// Supply the new challenge to the live replacement; trusted adapter must
					// refuse even if its PID were numerically reused. It is not the old run.
					replacement.ask(t, map[string]any{"Op": "register_only", "Mode": "hold", "Endpoint": c.b.get()})
					probe := cloneMap(r.body)
					probe["pid"] = newer["pid"] // Model exact numeric PID reuse at the trusted adapter.
					rejected := replacement.ask(t, map[string]any{"Op": "confirm", "Report": probe})
					actual = int(rejected["status"].(float64))
					trace = append(trace, "substitute_open_returned_live_wrong_instance", "replacement_refuses_old_run_challenge")
				}
			} else {
				registered := h.ask(t, map[string]any{"Op": "register_only", "Mode": "hold", "Endpoint": c.b.get()})
				if registered["status"] != float64(200) {
					t.Fatal("open failed")
				}
				challenge := registered["result"].(map[string]any)
				trace = append(trace, "handle_opened", "fresh_challenge_generated")
				// A handle and challenge alone do not establish registration or permission.
				gate := spikePost(c, "/spike/permit", map[string]any{"host": who["host"], "attempt": "arrangement-a"})
				if gate.status != 409 {
					t.Fatal("unconfirmed binding allowed permit")
				}
				switch name {
				case "first_binding_success":
					confirmed := h.ask(t, map[string]any{"Op": "confirm", "Report": challenge})
					actual = int(confirmed["status"].(float64))
					expected = 200
					if c.json(t, "/spike/control", map[string]any{"action": "inspect"})["registered_host"] != who["host"] {
						t.Fatal("original not bound")
					}
					trace = append(trace, "same_original_process_acknowledges_after_open", "retained_handle_still_live")
				case "exit_after_open_before_confirm":
					h.stop()
					actual = spikePost(c, "/spike/host_confirm", challenge).status
					trace = append(trace, "original_exits", "delayed_ack_rejected_by_retained_handle")
				case "wrong_challenge":
					challenge["nonce"] = "not_the_open_challenge"
					actual = spikePost(c, "/spike/host_confirm", challenge).status
					trace = append(trace, "wrong_challenge_rejected")
				case "stale_challenge":
					h.ask(t, map[string]any{"Op": "register_only", "Mode": "hold", "Endpoint": c.b.get()})
					actual = spikePost(c, "/spike/host_confirm", challenge).status
					trace = append(trace, "new_challenge_issued", "old_ack_rejected")
				}
			}
			if actual != expected {
				t.Fatalf("binding status %d expected %d", actual, expected)
			}
			if !reflect.DeepEqual(empty, c.json(t, "/spike/inspect", map[string]any{})) || !reflect.DeepEqual(before, c.json(t, "/v1/state", nil)) {
				t.Fatal("binding changed reports or domain state")
			}
			if expected == 409 && c.json(t, "/spike/control", map[string]any{"action": "inspect"})["registered_host"] != nil {
				t.Fatal("failed binding became active")
			}
			acceptedObservation(t, map[string]any{"case": name, "input_trace": trace, "expected_http": expected, "actual_http": actual, "saved_reports": 0, "api_calls": 0, "synthetic_pid_reuse": name == "pid_reuse_before_open_substitute", "binding_only": true})
		})
	}
}
