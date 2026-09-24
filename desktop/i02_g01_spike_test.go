package main

// Isolated experiment only. Neither this adapter nor /spike routes ship in Wails.
import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

type spikeHost struct {
	b              *bridge
	pump           *deliveryPump
	id, mode       string
	permit, report map[string]any
	calls, seq     int
	trace          []string
	dropped        bool
}

func (h *spikeHost) mark(event string) { h.seq++; h.trace = append(h.trace, event) }
func (h *spikeHost) post(path string, p any) (int, map[string]any) {
	raw, _ := json.Marshal(p)
	status, data, err := h.b.request("POST", path, raw)
	if err != nil {
		return 503, map[string]any{"error": "transport_lost"}
	}
	var result map[string]any
	_ = json.Unmarshal(data, &result)
	return status, result
}
func (h *spikeHost) start() {
	status, _ := h.post("/v1/commands", map[string]any{"kind": "start", "target": "intervention:arrangement-a", "version": 1, "payload": map[string]any{}, "command_id": "g01-user-start"})
	if status != 200 {
		panic("user command did not commit")
	}
	h.mark("user_response_committed")
}
func (h *spikeHost) present(d delivery) bool {
	if h.mode == "before_call" {
		h.start()
	}
	call := fmt.Sprintf("call-%s-%d", h.id, h.seq)
	h.mark("call_gate_requested")
	status, _ := h.post("/spike/begin", map[string]any{"permit": h.permit, "call": call, "sequence": h.seq})
	if status != 200 {
		h.mark("call_gate_rejected")
		return false
	}
	h.calls++
	h.mark("api_enter")
	if h.mode == "during_call" {
		h.start()
	}
	h.mark("api_return")
	h.report = map[string]any{"permit": h.permit, "call": call, "sequence": h.seq, "source": "api_return", "delivered": h.mode != "api_failure", "command": "g01-result-" + d.ID,
		"host_wall_before": 9999999999, "host_wall_after": -1000} // deliberately backwards; never used as ordering evidence
	if h.mode == "after_return" {
		h.start()
	}
	return h.mode != "api_failure"
}

type spikeTransport struct{ h *spikeHost }

func (s *spikeTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	if r.URL.Path != "/v1/commands" {
		return http.DefaultTransport.RoundTrip(r)
	}
	raw, _ := io.ReadAll(r.Body)
	r.Body.Close()
	r.Body, _ = r.GetBody()
	var p map[string]any
	_ = json.Unmarshal(raw, &p)
	if p["kind"] == "delivery_receipt" {
		if s.h.report == nil {
			return &http.Response{StatusCode: 409, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(`{"error":"no_device_result"}`)), Request: r}, nil
		}
		if s.h.mode == "hold" || s.h.mode == "window_close" {
			return nil, errors.New("held in host memory")
		}
		if s.h.mode == "request_loss" && !s.h.dropped {
			s.h.dropped = true
			s.h.mark("request_lost")
			return nil, errors.New("injected request loss")
		}
		rewritten, _ := json.Marshal(s.h.report)
		clone := r.Clone(r.Context())
		u := *r.URL
		u.Path = "/spike/result"
		clone.URL = &u
		clone.Body = io.NopCloser(bytes.NewReader(rewritten))
		clone.ContentLength = int64(len(rewritten))
		resp, err := http.DefaultTransport.RoundTrip(clone)
		if s.h.mode == "response_loss" && !s.h.dropped && err == nil {
			s.h.dropped = true
			io.Copy(io.Discard, resp.Body)
			resp.Body.Close()
			s.h.mark("committed_response_lost")
			return nil, errors.New("injected response loss")
		}
		if err == nil && resp.StatusCode == 200 {
			s.h.mark("result_committed")
		}
		return resp, err
	}
	resp, err := http.DefaultTransport.RoundTrip(r)
	if p["kind"] == "delivery_claim" && err == nil && resp.StatusCode == 200 && (s.h.permit == nil || s.h.permit["attempt"] != p["target"]) {
		status, permit := s.h.post("/spike/permit", map[string]any{"attempt": p["target"], "host": s.h.id})
		if status != 200 {
			resp.Body.Close()
			return nil, errors.New("permit unavailable")
		}
		s.h.permit = permit
		s.h.mark("permit_saved")
		if s.h.mode == "claim_loss_cancel" {
			s.h.start()
			resp.Body.Close()
			return nil, errors.New("claim response lost after cancel")
		}
	}
	return resp, err
}

// A real disposable host process. Its only persistence is the parent test's
// explicit replay input; that input is a fault-injection artefact, not a host log.
func TestG01SpikeHostProcess(t *testing.T) {
	if os.Getenv("G01_SPIKE_HOST") != "1" {
		t.Skip("subprocess helper")
	}
	h := &spikeHost{b: newBridge(), id: fmt.Sprintf("host-%d-%d", os.Getpid(), time.Now().UnixNano())}
	h.b.client.Transport = &spikeTransport{h}
	h.pump = newDeliveryPump(h.b, h.present)
	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 4096), 1<<20)
	for scanner.Scan() {
		var p struct {
			Op, Mode string
			Endpoint endpoint
			Report   map[string]any
		}
		if json.Unmarshal(scanner.Bytes(), &p) != nil {
			t.Fatal("invalid harness input")
		}
		status := 200
		result := map[string]any{}
		switch p.Op {
		case "connect":
			h.b.set(p.Endpoint)
			h.mode = p.Mode
			status, result = h.post("/spike/host", map[string]any{"host": h.id})
			h.mark("connected")
		case "observe":
		case "mode":
			h.mode = p.Mode
		case "step":
			h.pump.step(deliverySnapshot(t, h.b))
		case "start":
			h.start()
		case "close_window":
			h.mark("window_closed_process_alive")
		case "flush":
			report := h.report
			if p.Report != nil {
				report = p.Report
			}
			if report == nil {
				status = 409
				result = map[string]any{"error": "no_volatile_result"}
			} else {
				status, result = h.post("/spike/result", report)
				h.mark("result_request_returned")
			}
		case "click_only":
			d := deliverySnapshot(t, h.b)[0]
			h.post("/v1/commands", map[string]any{"kind": "delivery_claim", "target": d.ID, "version": d.Version, "payload": map[string]any{}, "command_id": "g01-claim-click"})
			h.start()
			status, result = h.post("/spike/result", map[string]any{"permit": h.permit, "command": "click-result", "call": "missing", "delivered": true, "source": "click", "sequence": 9})
		default:
			t.Fatal("unknown operation")
		}
		raw, _ := json.Marshal(map[string]any{"status": status, "result": result, "report": h.report, "permit": h.permit, "calls": h.calls, "trace": h.trace, "host": h.id})
		fmt.Println("G01_HOST " + string(raw))
	}
}

type spikeProcess struct {
	cmd *exec.Cmd
	in  io.WriteCloser
	out *bufio.Scanner
}

func startSpikeHost(t *testing.T) *spikeProcess {
	t.Helper()
	cmd := exec.Command(os.Args[0], "-test.run=^TestG01SpikeHostProcess$")
	cmd.Env = append(os.Environ(), "G01_SPIKE_HOST=1")
	in, _ := cmd.StdinPipe()
	out, _ := cmd.StdoutPipe()
	cmd.Stderr = os.Stderr
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	p := &spikeProcess{cmd, in, bufio.NewScanner(out)}
	p.out.Buffer(make([]byte, 4096), 1<<20)
	t.Cleanup(func() { p.stop() })
	return p
}
func (p *spikeProcess) stop() {
	if p.cmd.ProcessState == nil {
		p.in.Close()
		_ = p.cmd.Process.Kill()
		_ = p.cmd.Wait()
	}
}
func (p *spikeProcess) ask(t *testing.T, value any) map[string]any {
	t.Helper()
	raw, _ := json.Marshal(value)
	_, err := fmt.Fprintln(p.in, string(raw))
	if err != nil {
		t.Fatal(err)
	}
	for p.out.Scan() {
		line := p.out.Text()
		if strings.HasPrefix(line, "G01_HOST ") {
			var r map[string]any
			if json.Unmarshal([]byte(strings.TrimPrefix(line, "G01_HOST ")), &r) != nil {
				t.Fatal("bad host reply")
			}
			return r
		}
	}
	t.Fatal("host exited before reply")
	return nil
}

type spikeCore struct {
	cmd               *exec.Cmd
	b                 *bridge
	dir, root, python string
}

func startSpikeCore(t *testing.T) *spikeCore {
	root, _ := filepath.Abs("..")
	python := os.Getenv("I01_TEST_PYTHON")
	if python == "" {
		python = "python3"
	}
	c := &spikeCore{dir: t.TempDir(), root: root, python: python, b: newBridge()}
	c.restart(t)
	t.Cleanup(func() { c.stop() })
	return c
}
func (c *spikeCore) stop() {
	if c.cmd != nil && c.cmd.ProcessState == nil {
		_ = c.cmd.Process.Kill()
		_ = c.cmd.Wait()
	}
}
func (c *spikeCore) restart(t *testing.T) {
	t.Helper()
	c.stop()
	boot := filepath.Join(c.dir, "boot.json")
	_ = os.Remove(boot)
	c.cmd = exec.Command(c.python, "-m", "spikes.i02_g01.server", c.dir, boot)
	c.cmd.Dir = c.root
	c.cmd.Stderr = os.Stderr
	if err := c.cmd.Start(); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 100; i++ {
		raw, err := os.ReadFile(boot)
		if err == nil {
			var e endpoint
			_ = json.Unmarshal(raw, &e)
			c.b.set(e)
			_ = os.Remove(boot)
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatal("spike Core bootstrap timeout")
}
func (c *spikeCore) json(t *testing.T, path string, p any) map[string]any {
	t.Helper()
	method := "POST"
	var body []byte
	if p == nil {
		method = "GET"
	} else {
		body, _ = json.Marshal(p)
	}
	status, raw, err := c.b.request(method, path, body)
	if status != 200 || err != nil {
		t.Fatalf("snapshot %s status %d", path, status)
	}
	var v map[string]any
	_ = json.Unmarshal(raw, &v)
	return v
}
func cloneMap(v map[string]any) map[string]any {
	raw, _ := json.Marshal(v)
	var r map[string]any
	_ = json.Unmarshal(raw, &r)
	return r
}

func TestG01BoundedSpike(t *testing.T) {
	if os.Getenv("I02_G01_SPIKE") != "1" {
		t.Skip("isolated opt-in experiment")
	}
	cases := []string{"normal", "claim_loss_cancel", "before_call", "during_call", "after_return", "request_loss", "response_loss", "window_close", "api_failure", "click_only", "wrong_permit", "wrong_attempt", "wrong_core", "wrong_host", "wrong_database", "wrong_call", "conflict_command", "conflict_attempt", "duplicate_new_command", "rollback", "core_before", "core_after", "host_before", "host_after", "both_before", "both_after"}
	for _, name := range cases {
		t.Run(name, func(t *testing.T) {
			c := startSpikeCore(t)
			h := startSpikeHost(t)
			mode := name
			if strings.Contains(name, "_before") || strings.Contains(name, "_after") || strings.HasPrefix(name, "wrong_") || name == "rollback" {
				mode = "hold"
			}
			if strings.HasSuffix(name, "_after") {
				mode = "response_loss"
			}
			h.ask(t, map[string]any{"Op": "connect", "Mode": mode, "Endpoint": c.b.get()})
			var sent map[string]any
			if name == "click_only" {
				sent = h.ask(t, map[string]any{"Op": "click_only"})
			} else {
				sent = h.ask(t, map[string]any{"Op": "step"})
				if name != "before_call" && name != "during_call" && name != "after_return" {
					h.ask(t, map[string]any{"Op": "start"})
				}
			}
			report, _ := sent["report"].(map[string]any)
			if name == "window_close" {
				h.ask(t, map[string]any{"Op": "close_window"})
			}
			coreRestart := strings.HasPrefix(name, "core_") || strings.HasPrefix(name, "both_")
			hostRestart := strings.HasPrefix(name, "host_") || strings.HasPrefix(name, "both_")
			traceBefore := h.ask(t, map[string]any{"Op": "observe"})
			preserved := c.json(t, "/v1/state", nil)
			if coreRestart {
				c.restart(t)
			}
			if hostRestart {
				h.stop()
				h = startSpikeHost(t)
			}
			if coreRestart || hostRestart {
				h.ask(t, map[string]any{"Op": "connect", "Mode": "hold", "Endpoint": c.b.get()})
			}
			if hostRestart {
				empty := h.ask(t, map[string]any{"Op": "flush"})
				if empty["status"] != float64(409) || empty["result"].(map[string]any)["error"] != "no_volatile_result" {
					t.Fatal("new host recovered volatile report")
				}
			}
			before := c.json(t, "/v1/state", nil)
			for _, key := range []string{"database_id", "sessions", "checkpoints", "evidence", "plans", "actions", "arrangements"} {
				if !reflect.DeepEqual(before[key], preserved[key]) {
					t.Fatalf("restart changed %s", key)
				}
			}
			prior := c.json(t, "/spike/inspect", map[string]any{})
			expected := 200
			reason := ""
			input := report
			if name == "before_call" || name == "click_only" || name == "claim_loss_cancel" {
				expected = 409
			}
			if strings.HasSuffix(name, "_before") {
				expected = 409
				reason = "run_boundary_uncommitted"
			}
			if strings.HasPrefix(name, "wrong_") {
				input = cloneMap(report)
				expected = 409
				if name == "wrong_call" {
					input["call"] = "mismatched"
					reason = "no_matching_device_result"
				} else {
					permit := input["permit"].(map[string]any)
					field := strings.TrimPrefix(name, "wrong_")
					if field == "permit" {
						field = "id"
					}
					permit[field] = "mismatched"
					reason = "permit_or_attempt_mismatch"
				}
			}
			if name == "conflict_command" || name == "conflict_attempt" {
				input = cloneMap(report)
				input["delivered"] = false
				expected = 409
				reason = "command_content_conflict"
				if name == "conflict_attempt" {
					input["command"] = "other-result"
					reason = "attempt_result_conflict"
				}
			}
			if name == "duplicate_new_command" {
				input = cloneMap(report)
				input["command"] = "equivalent-result"
			}
			if name == "rollback" {
				input = cloneMap(report)
				input["fault_before_commit"] = true
				expected = 503
				reason = "injected_not_committed"
			}
			var response map[string]any
			if name == "click_only" {
				response = sent
			} else {
				response = h.ask(t, map[string]any{"Op": "flush", "Report": input})
			}
			if response["status"] != float64(expected) {
				t.Fatalf("status got %v want %d: %v", response["status"], expected, response["result"])
			}
			if reason != "" && response["result"].(map[string]any)["error"] != reason {
				t.Fatalf("rejection reason: %v", response)
			}
			saved := c.json(t, "/spike/inspect", map[string]any{})
			if expected != 200 && !reflect.DeepEqual(prior, saved) {
				t.Fatal("rejection or rollback changed experiment state")
			}
			if name == "rollback" {
				response = h.ask(t, map[string]any{"Op": "flush", "Report": report})
				if response["status"] != float64(200) {
					t.Fatal("retry after rollback failed")
				}
				saved = c.json(t, "/spike/inspect", map[string]any{})
				input = report
			}
			if expected == 200 || name == "rollback" {
				rows := saved["reports"].([]any)
				if len(rows) != 1 || saved["facts"] != float64(1) {
					t.Fatal("duplicate or missing report")
				}
				r := rows[0].(map[string]any)
				if r["order"] != "unknown" || r["opportunity"] != "unknown" || r["precise_latency"] != nil || r["sent_at"] != nil || r["user_seen"] != "unknown" {
					t.Fatal("invented timing/eligibility")
				}
				retry := h.ask(t, map[string]any{"Op": "flush", "Report": input})
				if name != "rollback" && (retry["status"] != float64(200) || !reflect.DeepEqual(response["result"], retry["result"])) {
					t.Fatal("same command did not return identical result")
				}
				if !reflect.DeepEqual(saved, c.json(t, "/spike/inspect", map[string]any{})) {
					t.Fatal("retry added records")
				}
			}
			after := c.json(t, "/v1/state", nil)
			if !reflect.DeepEqual(before, after) {
				t.Fatal("historical report changed production state/events/schedule")
			}
			stale := []byte(`{"kind":"interventions","id":"intervention:arrangement-a","version":1}`)
			status, _, _ := c.b.request("POST", "/v1/context", stale)
			if status != 409 {
				t.Fatal("old user operation revived")
			}
			final := h.ask(t, map[string]any{"Op": "step"})
			wantCalls := float64(1)
			if name == "before_call" || name == "click_only" || name == "claim_loss_cancel" || hostRestart {
				wantCalls = 0
			}
			if final["calls"] != wantCalls {
				t.Fatal("repeated or prohibited device call")
			}
			trace := final["trace"].([]any)
			if hostRestart {
				trace = append(append(traceBefore["trace"].([]any), "host_process_restarted"), trace...)
			}
			observation := map[string]any{"case": name, "status": "PASS", "expected_http": expected, "response": response["result"], "input_trace": trace, "association": sent["permit"], "api_calls": sent["calls"], "calls_in_final_host": final["calls"], "resends": 0, "core_restarted": coreRestart, "host_restarted": hostRestart, "saved_reports": len(saved["reports"].([]any)), "order": "unknown", "opportunity": "unknown", "production_snapshot_unchanged_by_report": true, "windows": "NOT_RUN"}
			proof := "controlled callback order only; Windows API order unknown"
			decision := "same_run_permit_and_call_match"
			if expected != 200 {
				decision = reason
				if decision == "" {
					decision = "no_device_result"
				}
			}
			if strings.HasSuffix(name, "_after") {
				decision = "exact_committed_command_lookup_before_run_guard"
			}
			observation["harness_order_evidence"] = proof
			observation["decision_reason"] = decision
			raw, _ := json.Marshal(observation)
			t.Log("G01_OBSERVATION " + string(raw))
		})
	}
}

func TestG01MixedCommittedAndUncommitted(t *testing.T) {
	if os.Getenv("I02_G01_SPIKE") != "1" {
		t.Skip("isolated opt-in experiment")
	}
	for _, boundary := range []string{"core", "host", "both"} {
		t.Run(boundary, func(t *testing.T) {
			c := startSpikeCore(t)
			h := startSpikeHost(t)
			h.ask(t, map[string]any{"Op": "connect", "Mode": "normal", "Endpoint": c.b.get()})
			first := h.ask(t, map[string]any{"Op": "step"})
			h.ask(t, map[string]any{"Op": "start"})
			c.json(t, "/spike/advance", map[string]any{"now": 160})
			h.ask(t, map[string]any{"Op": "mode", "Mode": "hold"})
			second := h.ask(t, map[string]any{"Op": "step"})
			if second["calls"] != float64(2) {
				t.Fatal("expected two distinct device attempts")
			}
			existing := c.json(t, "/spike/inspect", map[string]any{})
			before := c.json(t, "/v1/state", nil)
			trace := h.ask(t, map[string]any{"Op": "observe"})["trace"]
			if boundary != "host" {
				c.restart(t)
			}
			if boundary != "core" {
				h.stop()
				h = startSpikeHost(t)
			}
			h.ask(t, map[string]any{"Op": "connect", "Mode": "hold", "Endpoint": c.b.get()})
			committed := h.ask(t, map[string]any{"Op": "flush", "Report": first["report"]})
			uncommitted := h.ask(t, map[string]any{"Op": "flush", "Report": second["report"]})
			if committed["status"] != float64(200) || uncommitted["status"] != float64(409) || uncommitted["result"].(map[string]any)["error"] != "run_boundary_uncommitted" {
				t.Fatal("mixed restart boundary incorrect")
			}
			if !reflect.DeepEqual(existing, c.json(t, "/spike/inspect", map[string]any{})) {
				t.Fatal("mixed restart changed reports")
			}
			after := c.json(t, "/v1/state", nil)
			for _, key := range []string{"database_id", "sessions", "checkpoints", "evidence", "plans", "actions", "arrangements", "schedules"} {
				if !reflect.DeepEqual(before[key], after[key]) {
					t.Fatalf("mixed restart changed %s", key)
				}
			}
			beforeStep := h.ask(t, map[string]any{"Op": "observe"})
			end := h.ask(t, map[string]any{"Op": "step"})
			if beforeStep["calls"] != end["calls"] {
				t.Fatal("mixed restart resent")
			}
			raw, _ := json.Marshal(map[string]any{"case": "mixed_" + boundary, "status": "PASS", "input_trace": trace, "api_calls": 2, "resends": 0, "saved_reports": 1, "core_restarted": boundary != "host", "host_restarted": boundary != "core", "committed_http": 200, "uncommitted_http": 409, "reason": "run_boundary_uncommitted", "order": "unknown", "opportunity": "unknown", "existing_state_and_report_preserved": true, "windows": "NOT_RUN"})
			t.Log("G01_OBSERVATION " + string(raw))
		})
	}
}

// A new OS process exists before its registration reaches Core. Retained bytes
// below stand for an old request delayed in transport, not host persistence.
// Keep the required 409 assertion: observed 200 must remain a failing candidate.
func TestG01RestartBeforeRegistration(t *testing.T) {
	if os.Getenv("I02_G01_SPIKE") != "1" {
		t.Skip("isolated opt-in experiment")
	}
	c := startSpikeCore(t)
	old := startSpikeHost(t)
	old.ask(t, map[string]any{"Op": "connect", "Mode": "hold", "Endpoint": c.b.get()})
	sent := old.ask(t, map[string]any{"Op": "step"})
	old.ask(t, map[string]any{"Op": "start"})
	old.stop()
	replacement := startSpikeHost(t)
	// observe proves the replacement process is executing, without registering it.
	live := replacement.ask(t, map[string]any{"Op": "observe"})
	if live["host"] == sent["host"] {
		t.Fatal("host incarnation did not change")
	}
	before := c.json(t, "/v1/state", nil)
	raw, _ := json.Marshal(sent["report"])
	status, result, err := c.b.request("POST", "/spike/result", raw)
	if err != nil {
		t.Fatal(err)
	}
	after := c.json(t, "/v1/state", nil)
	if !reflect.DeepEqual(before, after) {
		t.Fatal("diagnostic changed domain state")
	}
	saved := c.json(t, "/spike/inspect", map[string]any{})
	outcome := "PASS"
	if status != 409 || len(saved["reports"].([]any)) != 0 {
		outcome = "FAIL"
	}
	observation := map[string]any{"case": "host_restart_before_registration", "status": outcome, "input_trace": []string{"permit_saved", "api_enter", "api_return", "result_request_held_in_transport", "user_response_committed", "old_host_killed_and_waited", "new_host_started_and_running", "new_host_registration_not_yet_received", "old_result_released_to_core"}, "api_calls": 1, "resends": 0, "core_restarted": false, "host_restarted": true, "old_and_new_host_differ": true, "expected_http": 409, "actual_http": status, "saved_reports": len(saved["reports"].([]any)), "order": "unknown", "opportunity": "unknown", "reason": "Core only knows registered host; OS restart precedes registration", "production_snapshot_unchanged_by_report": true, "windows": "NOT_RUN"}
	output, _ := json.Marshal(observation)
	t.Log("G01_OBSERVATION " + string(output))
	if outcome != "PASS" {
		t.Fatalf("candidate accepted pre-restart uncommitted result before new host registration: status=%d body=%s", status, result)
	}
}
