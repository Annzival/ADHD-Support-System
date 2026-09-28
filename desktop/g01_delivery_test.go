package main

import (
	"encoding/json"
	"io"
	"net/http"
	"os"
	"testing"
)

type deliveryHook struct {
	base   http.RoundTripper
	kind   string
	before func()
}

func (h *deliveryHook) RoundTrip(r *http.Request) (*http.Response, error) {
	if r.Method == "POST" && h.before != nil {
		raw, _ := io.ReadAll(r.Body)
		r.Body.Close()
		r.Body, _ = r.GetBody()
		var cmd struct {
			Kind string `json:"kind"`
		}
		_ = json.Unmarshal(raw, &cmd)
		if cmd.Kind == h.kind {
			f := h.before
			h.before = nil
			f()
		}
	}
	return h.base.RoundTrip(r)
}
func startDuringDelivery(t *testing.T, b *bridge) {
	t.Helper()
	raw := []byte(`{"kind":"start","target":"intervention:arrangement-a","version":1,"payload":{},"command_id":"g01-start"}`)
	if status, _, err := b.request("POST", "/v1/commands", raw); err != nil || status != 200 {
		t.Fatal("start failed", status, err)
	}
}
func TestG01ProductionPumpInterleavings(t *testing.T) {
	for _, order := range []string{"normal", "during_call", "after_return", "request_loss", "response_loss", "window_close", "api_failure"} {
		t.Run(order, func(t *testing.T) {
			b := deliveryCore(t)
			var loss *dropResponse
			if order == "request_loss" || order == "response_loss" {
				loss = &dropResponse{base: http.DefaultTransport, kind: "delivery_receipt", before: order == "request_loss"}
				b.client.Transport = loss
			}
			if order == "after_return" {
				b.client.Transport = &deliveryHook{base: http.DefaultTransport, kind: "delivery_receipt", before: func() { startDuringDelivery(t, b) }}
			}
			calls := 0
			p := newDeliveryPump(b, func(delivery) bool {
				calls++
				if order == "during_call" {
					startDuringDelivery(t, b)
				}
				return order != "api_failure"
			})
			p.now = func() float64 { return 100 }
			p.step(deliverySnapshot(t, b))
			if order == "request_loss" || order == "response_loss" {
				startDuringDelivery(t, b)
			}
			// Closing a window does not recreate the pump/process or reissue the call.
			for i := 0; i < 3; i++ {
				p.step(deliverySnapshot(t, b))
			}
			_, raw, err := b.request("GET", "/v1/state", nil)
			if err != nil {
				t.Fatal(err)
			}
			var state struct {
				Reports []struct {
					Order       string `json:"order"`
					Opportunity string `json:"opportunity"`
				} `json:"device_reports"`
				Sessions []json.RawMessage `json:"sessions"`
			}
			if json.Unmarshal(raw, &state) != nil || len(state.Reports) != 1 || calls != 1 {
				t.Fatal("missing/duplicate report or presentation", calls, string(raw))
			}
			late := order == "during_call" || order == "after_return" || order == "request_loss"
			want := "before_response"
			if late {
				want = "unknown"
			}
			if state.Reports[0].Order != want {
				t.Fatal("wrong order", state.Reports[0])
			}
			if late && state.Reports[0].Opportunity != "unknown" {
				t.Fatal("late result counted")
			}
			if late || order == "response_loss" {
				if len(state.Sessions) != 1 {
					t.Fatal("session changed")
				}
				status, _, _ := b.request("POST", "/v1/context", []byte(`{"kind":"interventions","id":"intervention:arrangement-a","version":1}`))
				if status != 409 {
					t.Fatal("old operation revived")
				}
			}
			if loss != nil && (len(loss.bodies) != 2 || string(loss.bodies[0]) != string(loss.bodies[1])) {
				t.Fatal("retry changed result")
			}
		})
	}
}
func TestG01CancelledBeforeCallCannotPresent(t *testing.T) {
	for _, kind := range []string{"delivery_claim", "delivery_begin"} {
		t.Run(kind, func(t *testing.T) {
			b := deliveryCore(t)
			b.client.Transport = &deliveryHook{base: http.DefaultTransport, kind: kind, before: func() { startDuringDelivery(t, b) }}
			calls := 0
			p := newDeliveryPump(b, func(delivery) bool { calls++; return true })
			for i := 0; i < 3; i++ {
				p.step(deliverySnapshot(t, b))
			}
			if calls != 0 {
				t.Fatal("cancelled unsent attempt called device")
			}
		})
	}
}

func TestG01InitialBindingRefusesWrongOrReusedProcessIdentity(t *testing.T) {
	for _, c := range []struct {
		name, run string
		pid       int
		want      bool
	}{
		{"original", hostRun, os.Getpid(), true},
		{"wrong_pid", hostRun, os.Getpid() + 1, false},
		{"replacement_with_reused_numeric_pid", "previous-process-run", os.Getpid(), false},
	} {
		t.Run(c.name, func(t *testing.T) {
			raw, _ := json.Marshal(map[string]any{"host_run": c.run, "pid": c.pid})
			if hostChallengeMatches(raw) != c.want {
				t.Fatal("first binding confused process instances")
			}
		})
	}
}
