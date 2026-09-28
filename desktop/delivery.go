package main

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"os"
	"time"
)

type delivery struct {
	Strength      string `json:"strength"`
	ID            string `json:"id"`
	Version       int    `json:"version"`
	Target        string `json:"target"`
	TargetKind    string `json:"target_kind"`
	TargetVersion int    `json:"target_version"`
	Status        string `json:"status"`
}

type deliveryAttempt struct {
	original   delivery
	permission json.RawMessage
	call       string
	receipt    []byte
	presented  bool
	done       bool
}

// Transport memory belongs to this process and Core connection. It is never
// persisted or transferred into a replacement host's identity.
type deliveryPump struct {
	bridge   *bridge
	present  func(delivery) bool
	attempts map[string]*deliveryAttempt
	binding  json.RawMessage
	now      func() float64
}

var hostRun = randomIdentity()

func randomIdentity() string {
	var value [32]byte
	if _, err := rand.Read(value[:]); err != nil {
		panic("OS random source unavailable")
	}
	return hex.EncodeToString(value[:])
}

func newDeliveryPump(b *bridge, present func(delivery) bool) *deliveryPump {
	return &deliveryPump{bridge: b, present: present, attempts: map[string]*deliveryAttempt{},
		now: func() float64 { return float64(time.Now().UnixNano()) / 1e9 }}
}

func (p *deliveryPump) bind() bool {
	if p.binding != nil {
		return true
	}
	raw, _ := json.Marshal(map[string]any{"host_run": hostRun, "pid": os.Getpid()})
	status, challenge, err := p.bridge.request("POST", "/v1/host/challenge", raw)
	if err != nil || status != 200 {
		return false
	}
	if !hostChallengeMatches(challenge) {
		return false
	}
	// Only this original process answers a fresh challenge created after OpenProcess.
	status, binding, err := p.bridge.request("POST", "/v1/host/confirm", challenge)
	if err != nil || status != 200 {
		return false
	}
	p.binding = binding
	return true
}

func hostChallengeMatches(challenge []byte) bool {
	var identity struct {
		Host string `json:"host_run"`
		PID  int    `json:"pid"`
	}
	return json.Unmarshal(challenge, &identity) == nil && identity.Host == hostRun && identity.PID == os.Getpid()
}

func deliveryCommand(kind string, d delivery, version int, payload any) []byte {
	prefix := map[string]string{"delivery_claim": "claim:", "delivery_begin": "begin:", "delivery_receipt": "receipt:"}[kind]
	raw, _ := json.Marshal(map[string]any{"kind": kind, "target": d.ID, "version": version, "payload": payload, "command_id": prefix + d.ID})
	return raw
}

func (p *deliveryPump) send(raw []byte) (bool, bool, []byte) {
	status, result, err := p.bridge.request("POST", "/v1/commands", raw)
	if err != nil {
		return false, false, nil
	}
	return status == 200, status == 200 || status == 400 || status == 409, result
}

func (p *deliveryPump) valid(d delivery) (bool, bool) {
	raw, _ := json.Marshal(map[string]any{"kind": d.TargetKind, "id": d.Target, "version": d.TargetVersion})
	status, result, err := p.bridge.request("POST", "/v1/context", raw)
	if err != nil {
		return false, false
	}
	if status == 400 || status == 409 {
		return false, true
	}
	var context struct {
		Valid bool `json:"valid"`
		State struct {
			Deliveries []delivery `json:"deliveries"`
		} `json:"state"`
	}
	if status != 200 || json.Unmarshal(result, &context) != nil {
		return false, false
	}
	for _, current := range context.State.Deliveries {
		if current.ID == d.ID && current.Status == "claimed" && context.Valid {
			return true, false
		}
	}
	return false, true
}

func (p *deliveryPump) step(deliveries []delivery) {
	for _, current := range deliveries {
		if p.attempts[current.ID] == nil && current.Status == "pending" {
			p.attempts[current.ID] = &deliveryAttempt{original: current, call: randomIdentity()}
		}
	}
	for _, a := range p.attempts {
		if a.done {
			continue
		}
		d := a.original
		if !a.presented {
			if !p.bind() {
				continue
			}
			if a.permission == nil {
				success, terminal, result := p.send(deliveryCommand("delivery_claim", d, d.Version, p.binding))
				if !success {
					a.done = terminal
					continue
				}
				a.permission = append(json.RawMessage(nil), result...)
			}
			// A replayed grant is not fresh permission to present cancelled work.
			valid, terminal := p.valid(d)
			if !valid {
				a.done = terminal
				continue
			}
			success, terminal, _ := p.send(deliveryCommand("delivery_begin", d, d.Version+1, map[string]any{"permission": a.permission, "call": a.call}))
			if !success {
				a.done = terminal
				continue
			}
			valid, terminal = p.valid(d)
			if !valid {
				a.done = terminal
				continue
			}
			delivered := p.present(d)
			returned := p.now()
			a.presented = true
			a.receipt = deliveryCommand("delivery_receipt", d, d.Version+1, map[string]any{
				"permission": a.permission, "call": a.call, "source": "api_return", "delivered": delivered, "api_return_at": returned})
		}
		// Cancellation stops new calls, not retries of the already returned result.
		// Keep the exact bytes even when the snapshot no longer contains the attempt.
		_, terminal, _ := p.send(a.receipt)
		a.done = terminal
	}
}
