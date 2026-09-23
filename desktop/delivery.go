package main

import "encoding/json"

type delivery struct {
	ID            string `json:"id"`
	Version       int    `json:"version"`
	Target        string `json:"target"`
	TargetKind    string `json:"target_kind"`
	TargetVersion int    `json:"target_version"`
	Status        string `json:"status"`
}

type deliveryAttempt struct {
	original  delivery
	presented bool
	delivered bool
	done      bool
}

// Volatile transport work for one Core connection epoch, not domain state.
// Keep exact commands across WebSocket reconnects; never adopt an orphan claim.
type deliveryPump struct {
	bridge   *bridge
	present  func(delivery) bool
	attempts map[string]*deliveryAttempt
}

func newDeliveryPump(b *bridge, present func(delivery) bool) *deliveryPump {
	return &deliveryPump{bridge: b, present: present, attempts: map[string]*deliveryAttempt{}}
}
func (p *deliveryPump) command(kind string, d delivery, version int, payload any) (success, terminal bool) {
	prefix := "claim:"
	if kind == "delivery_receipt" {
		prefix = "receipt:"
	}
	raw, _ := json.Marshal(map[string]any{"kind": kind, "target": d.ID, "version": version, "payload": payload, "command_id": prefix + d.ID})
	status, _, err := p.bridge.request("POST", "/v1/commands", raw)
	if err != nil {
		return false, false
	}
	return status == 200, status == 200 || status == 400 || status == 409
}
func (p *deliveryPump) step(deliveries []delivery) {
	seen := map[string]bool{}
	for _, current := range deliveries {
		seen[current.ID] = true
		a := p.attempts[current.ID]
		if a == nil {
			if current.Status != "pending" {
				continue
			}
			a = &deliveryAttempt{original: current}
			p.attempts[current.ID] = a
		}
		if a.done {
			continue
		}
		// A changed/expired context must never regain a presentation through replay.
		if current.Status != "pending" && current.Status != "claimed" && !(a.presented && (current.Status == "delivered" || current.Status == "failed")) {
			a.done = true
			continue
		}
		d := a.original
		if !a.presented {
			success, terminal := p.command("delivery_claim", d, d.Version, map[string]any{})
			if !success {
				a.done = terminal
				continue
			}
			// The saved result can outlive its context. Re-read current authority before
			// native presentation, especially after a lost claim response.
			contextBody, _ := json.Marshal(map[string]any{"kind": d.TargetKind, "id": d.Target, "version": d.TargetVersion})
			status, raw, err := p.bridge.request("POST", "/v1/context", contextBody)
			if err == nil && (status == 400 || status == 409) {
				a.done = true
				continue
			}
			var latest struct {
				Valid bool `json:"valid"`
				State struct {
					Deliveries []delivery `json:"deliveries"`
				} `json:"state"`
			}
			if err != nil || status != 200 || json.Unmarshal(raw, &latest) != nil {
				continue
			}
			valid := false
			for _, now := range latest.State.Deliveries {
				if now.ID == d.ID && now.Status == "claimed" {
					valid = true
				}
			}
			if !valid || !latest.Valid {
				a.done = true
				continue
			}
			a.delivered = p.present(d)
			a.presented = true
		}
		_, terminal := p.command("delivery_receipt", d, d.Version+1, map[string]any{"delivered": a.delivered})
		a.done = terminal
	}
	for id := range p.attempts {
		if !seen[id] {
			delete(p.attempts, id)
		}
	}
}
