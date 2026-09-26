package main

import (
	"encoding/json"
	"net/http"
	"os"
	"testing"
)

// Diagnostic evidence for Issue #33, NOT an acceptance oracle for late receipts.
// The real pump, HTTP server and SQLite Core run; native submission alone is a
// callback substitute. Do not turn the observed cancellation into a product rule.
func TestI02DeliveryInterleavingEvidence(t *testing.T) {
	if os.Getenv("I02_DELIVERY_PROBE") != "1" {
		t.Skip("opt-in diagnostic; late-receipt semantics await governance")
	}
	for _, order := range []string{"receipt_before_response", "response_inside_presentation", "receipt_request_lost_then_response", "receipt_committed_response_lost_then_response"} {
		t.Run(order, func(t *testing.T) {
			b := deliveryCore(t)
			var drop *dropResponse
			if order == "receipt_request_lost_then_response" || order == "receipt_committed_response_lost_then_response" {
				drop = &dropResponse{base: http.DefaultTransport, kind: "delivery_receipt", before: order == "receipt_request_lost_then_response"}
				b.client.Transport = drop
			}
			start := func() {
				raw := []byte(`{"kind":"start","target":"intervention:arrangement-a","version":1,"payload":{},"command_id":"probe-user-start"}`)
				status, _, err := b.request("POST", "/v1/commands", raw)
				if err != nil || status != 200 {
					t.Fatalf("user response did not commit: status=%d error=%v", status, err)
				}
			}
			presentations := 0
			pump := newDeliveryPump(b, func(delivery) bool {
				presentations++
				if order == "response_inside_presentation" {
					start()
				}
				return true // Synthetic successful native submission, not Windows evidence.
			})
			pump.step(deliverySnapshot(t, b))
			if order != "response_inside_presentation" {
				start()
			}
			for i := 0; i < 3; i++ {
				pump.step(deliverySnapshot(t, b))
			}
			status, raw, err := b.request("GET", "/v1/state", nil)
			if err != nil || status != 200 {
				t.Fatal("snapshot unavailable")
			}
			var state map[string]json.RawMessage
			if err := json.Unmarshal(raw, &state); err != nil {
				t.Fatal(err)
			}
			var sessions, checkpoints, schedules []map[string]any
			_ = json.Unmarshal(state["sessions"], &sessions)
			_ = json.Unmarshal(state["checkpoints"], &checkpoints)
			_ = json.Unmarshal(state["schedules"], &schedules)
			if len(sessions) != 1 || sessions[0]["status"] != "executing" || len(checkpoints) != 1 ||
				checkpoints[0]["session_id"] != sessions[0]["id"] || checkpoints[0]["due_at"] != float64(160) ||
				len(schedules) < 2 || string(state["evidence"]) != "[]" {
				t.Fatal("session, checkpoint, schedule or unknown-evidence invariant violated")
			}
			receiptRequestsBeforeManualRetry := 0
			if drop != nil {
				receiptRequestsBeforeManualRetry = len(drop.bodies)
			}
			before := string(raw)
			late := []byte(`{"kind":"delivery_receipt","target":"delivery:arrangement-a","version":2,"payload":{"delivered":true},"command_id":"receipt:delivery:arrangement-a"}`)
			lateStatus, lateBody, err := b.request("POST", "/v1/commands", late)
			if err != nil {
				t.Fatal(err)
			}
			var response struct {
				Error string `json:"error"`
			}
			_ = json.Unmarshal(lateBody, &response)
			_, after, _ := b.request("GET", "/v1/state", nil)
			if before != string(after) {
				t.Fatal("diagnostic retry changed persisted state")
			}
			old := []byte(`{"kind":"interventions","id":"intervention:arrangement-a","version":1}`)
			oldStatus, _, _ := b.request("POST", "/v1/context", old)
			if presentations != 1 || oldStatus != 409 {
				t.Fatal("repeated presentation or stale user context accepted")
			}
			// Record the observed result, but intentionally do not assert that either
			// cancelled or delivered is the correct policy for the contested ordering.
			observation := map[string]any{"case": order, "native_submission": "synthetic_success", "presentations": presentations,
				"late_receipt_http_status": lateStatus, "late_receipt_error": response.Error, "old_user_context_http_status": oldStatus,
				"deliveries": state["deliveries"], "sessions": state["sessions"], "checkpoints": state["checkpoints"],
				"schedules": state["schedules"], "events": state["events"], "evidence": state["evidence"]}
			if drop != nil {
				observation["pump_receipt_requests_before_manual_retry"] = receiptRequestsBeforeManualRetry
			}
			encoded, _ := json.Marshal(observation)
			t.Log("I02_OBSERVATION " + string(encoded))
		})
	}
}
