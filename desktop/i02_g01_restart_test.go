package main

import (
	"encoding/json"
	"os"
	"reflect"
	"testing"
	"time"
)

func TestG01RestartRevalidation(t *testing.T) {
	if os.Getenv("I02_G01_SPIKE") != "1" {
		t.Skip("isolated opt-in experiment")
	}
	cases := []string{"exit_observer_delayed", "exit_after_check_before_commit", "committed_response_lost_restart_unregistered", "pid_reuse_substitute", "pid_mismatch", "identity_unavailable", "missing_identity", "window_close_live_process"}
	for _, name := range cases {
		t.Run(name, func(t *testing.T) {
			c := startSpikeCore(t)
			h := startSpikeHost(t)
			mode := "hold"
			if name == "committed_response_lost_restart_unregistered" {
				mode = "response_loss"
			}
			h.ask(t, map[string]any{"Op": "connect", "Mode": mode, "Endpoint": c.b.get()})
			sent := h.ask(t, map[string]any{"Op": "step"})
			h.ask(t, map[string]any{"Op": "start"})
			before := c.json(t, "/v1/state", nil)
			prior := c.json(t, "/spike/inspect", map[string]any{})
			request := sent["report"]
			path := "/spike/result"
			expected := 409
			expectedReports := 0
			trace := []string{"permit_bound_to_os_process_handle", "api_return", "user_response_committed"}
			replacementRunning := false
			synthetic := name == "pid_reuse_substitute"
			switch name {
			case "exit_observer_delayed":
				c.json(t, "/spike/control", map[string]any{"action": "delay_observer"})
				c.json(t, "/spike/control", map[string]any{"action": "arm", "point": "before_live_check"})
			case "exit_after_check_before_commit":
				c.json(t, "/spike/control", map[string]any{"action": "arm", "point": "after_live_check_before_commit"})
			case "pid_reuse_substitute":
				c.json(t, "/spike/control", map[string]any{"action": "reuse_identity"})
				trace = append(trace, "same_pid_different_instance_injected")
			case "pid_mismatch":
				path = "/spike/host"
				request = map[string]any{"host": sent["host"], "pid": os.Getpid()}
				trace = append(trace, "same_host_label_different_pid")
			case "identity_unavailable":
				c.json(t, "/spike/control", map[string]any{"action": "identity_unavailable"})
				trace = append(trace, "retained_handle_closed")
			case "missing_identity":
				path = "/spike/host"
				request = map[string]any{"host": "no-process-evidence"}
				trace = append(trace, "registration_without_process_evidence")
			case "window_close_live_process":
				h.ask(t, map[string]any{"Op": "close_window"})
				expected = 200
				expectedReports = 1
				trace = append(trace, "window_closed_process_still_alive")
			case "committed_response_lost_restart_unregistered":
				h.stop()
				replacement := startSpikeHost(t)
				live := replacement.ask(t, map[string]any{"Op": "observe"})
				replacementRunning = live["host"] != sent["host"]
				expected = 200
				expectedReports = 1
				trace = []string{"permit_bound_to_os_process_handle", "api_return", "result_already_committed_response_lost", "user_response_committed", "old_host_killed_and_waited", "new_host_running_not_registered"}
			}
			type response struct {
				status int
				body   []byte
				err    error
			}
			done := make(chan response, 1)
			raw, _ := json.Marshal(request)
			go func() { status, body, err := c.b.request("POST", path, raw); done <- response{status, body, err} }()
			if name == "exit_observer_delayed" || name == "exit_after_check_before_commit" {
				deadline := time.Now().Add(2 * time.Second)
				for {
					state := c.json(t, "/spike/control", map[string]any{"action": "inspect"})
					if state["entered"] == true {
						break
					}
					if time.Now().After(deadline) {
						t.Fatal("barrier not reached")
					}
					time.Sleep(10 * time.Millisecond)
				}
				trace = append(trace, "deterministic_transaction_barrier_reached")
				h.stop()
				replacement := startSpikeHost(t)
				live := replacement.ask(t, map[string]any{"Op": "observe"})
				replacementRunning = live["host"] != sent["host"]
				if !replacementRunning {
					t.Fatal("replacement not running")
				}
				trace = append(trace, "old_host_killed_and_waited", "new_host_running_not_registered", "release_transaction_barrier")
				c.json(t, "/spike/control", map[string]any{"action": "release"})
			}
			result := <-done
			if result.err != nil {
				t.Fatal(result.err)
			}
			var body map[string]any
			_ = json.Unmarshal(result.body, &body)
			saved := c.json(t, "/spike/inspect", map[string]any{})
			after := c.json(t, "/v1/state", nil)
			control := c.json(t, "/spike/control", map[string]any{"action": "inspect"})
			if !reflect.DeepEqual(before, after) {
				t.Fatal("report changed production domain snapshot")
			}
			if sent["calls"] != float64(1) {
				t.Fatal("unexpected device calls")
			}
			stale := []byte(`{"kind":"interventions","id":"intervention:arrangement-a","version":1}`)
			status, _, _ := c.b.request("POST", "/v1/context", stale)
			if status != 409 {
				t.Fatal("old user context revived")
			}
			if name == "exit_observer_delayed" && control["cached_exit"] != false {
				t.Fatal("observer delay not applied")
			}
			if name == "committed_response_lost_restart_unregistered" && !reflect.DeepEqual(prior, saved) {
				t.Fatal("committed retry changed facts")
			}
			if result.status == 409 && !reflect.DeepEqual(prior, saved) {
				t.Fatal("rejected result left partial experiment writes")
			}
			if name == "committed_response_lost_restart_unregistered" && !reflect.DeepEqual(body, prior["reports"].([]any)[0]) {
				t.Fatal("committed command did not return exact stored result")
			}
			actualReports := len(saved["reports"].([]any))
			outcome := "PASS"
			if result.status != expected || actualReports != expectedReports {
				outcome = "FAIL"
			}
			observation := map[string]any{"case": name, "status": outcome, "expected_http": expected, "actual_http": result.status, "expected_reports": expectedReports, "actual_reports": actualReports, "reason": body["error"], "input_trace": trace, "os_handle_observation": true, "synthetic_identity_reuse": synthetic, "replacement_running_unregistered": replacementRunning, "cached_exit": control["cached_exit"], "api_calls": 1, "resends": 0, "production_snapshot_unchanged": true, "old_context_http": status, "windows": "NOT_RUN"}
			encoded, _ := json.Marshal(observation)
			t.Log("G01_R2_OBSERVATION " + string(encoded))
			if outcome != "PASS" {
				t.Fatalf("required restart boundary failed: status %d vs %d, reports %d vs %d", result.status, expected, actualReports, expectedReports)
			}
		})
	}
}
