package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

type dropResponse struct {
	delay  time.Duration
	base   http.RoundTripper
	kind   string
	before bool
	bodies [][]byte
}

func (d *dropResponse) RoundTrip(r *http.Request) (*http.Response, error) {
	if r.Method != "POST" {
		return d.base.RoundTrip(r)
	}
	raw, _ := io.ReadAll(r.Body)
	r.Body.Close()
	r.Body, _ = r.GetBody()
	var cmd struct {
		Kind string `json:"kind"`
	}
	_ = json.Unmarshal(raw, &cmd)
	if cmd.Kind != d.kind {
		return d.base.RoundTrip(r)
	}
	d.bodies = append(d.bodies, raw)
	if len(d.bodies) == 1 && d.before {
		return nil, errors.New("injected request loss")
	}
	resp, err := d.base.RoundTrip(r)
	if len(d.bodies) == 1 && err == nil {
		time.Sleep(d.delay)
		io.Copy(io.Discard, resp.Body)
		resp.Body.Close()
		return nil, errors.New("injected committed response loss")
	}
	return resp, err
}
func deliveryCore(t *testing.T) *bridge {
	t.Helper()
	python := os.Getenv("I01_TEST_PYTHON")
	if python == "" {
		python = "python3"
	}
	root, _ := filepath.Abs("..")
	dir := t.TempDir()
	boot := filepath.Join(dir, "bootstrap.json")
	// Real Core + HTTP protocol, with deterministic clock and continuously online ticks.
	script := `import sys,threading,time
from agent_core.core import Core
from agent_core.transport import Server
c=Core(sys.argv[1],clock=lambda:100)
c.seed_fixture(confirmed=True,start=99,duration=60,window_end=1000)
c.tick(desktop_online=True)
s=Server(c)
s.last_desktop=time.monotonic()
s.publish(sys.argv[2])
threading.Thread(target=s.schedule,daemon=True).start()
s.serve_forever()
`
	ctx, cancel := context.WithCancel(context.Background())
	cmd := exec.CommandContext(ctx, python, "-c", script, filepath.Join(dir, "state.sqlite3"), boot)
	cmd.Dir = root
	if err := cmd.Start(); err != nil {
		cancel()
		t.Fatal(err)
	}
	t.Cleanup(func() { cancel(); _ = cmd.Wait() })
	b := newBridge()
	for i := 0; i < 100; i++ {
		raw, err := os.ReadFile(boot)
		if err == nil {
			var e endpoint
			if json.Unmarshal(raw, &e) != nil {
				t.Fatal("bad bootstrap")
			}
			b.set(e)
			return b
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatal("Core bootstrap timeout")
	return nil
}
func deliverySnapshot(t *testing.T, b *bridge) []delivery {
	t.Helper()
	status, raw, err := b.request("GET", "/v1/state", nil)
	if err != nil || status != 200 {
		t.Fatal("state unavailable")
	}
	var state struct {
		Deliveries []delivery `json:"deliveries"`
	}
	if json.Unmarshal(raw, &state) != nil {
		t.Fatal("bad snapshot")
	}
	return state.Deliveries
}
func TestDeliveryRetriesUncertainCommandsWithoutRepeatingPresentation(t *testing.T) {
	for _, kind := range []string{"delivery_claim", "delivery_receipt"} {
		for _, before := range []bool{false, true} {
			name := kind + "/committed_response_loss"
			if before {
				name = kind + "/request_loss"
			}
			t.Run(name, func(t *testing.T) {
				b := deliveryCore(t)
				drop := &dropResponse{base: http.DefaultTransport, kind: kind, before: before}
				b.client.Transport = drop
				presentations := 0
				p := newDeliveryPump(b, func(delivery) bool { presentations++; return true })
				for i := 0; i < 5; i++ {
					p.step(deliverySnapshot(t, b))
				}
				state := deliverySnapshot(t, b)
				if presentations != 1 || state[0].Status != "delivered" {
					t.Fatalf("presentations=%d delivery=%s", presentations, state[0].Status)
				}
				if len(drop.bodies) != 2 || string(drop.bodies[0]) != string(drop.bodies[1]) {
					t.Fatal("retry must preserve exact command ID, version and payload")
				}
			})
		}
	}
}

func TestSlowClaimDoesNotBlockDesktopHeartbeat(t *testing.T) {
	b := deliveryCore(t)
	drop := &dropResponse{base: http.DefaultTransport, kind: "delivery_claim", delay: 2500 * time.Millisecond}
	b.client.Transport = drop
	presentations := make(chan bool, 5)
	p := newDeliveryPump(b, func(delivery) bool { presentations <- true; return true })
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { defer close(done); watchDeliveries(ctx, b.get(), p) }()
	defer func() { cancel(); <-done }()
	select {
	case <-presentations:
	case <-time.After(5 * time.Second):
		t.Fatal("slow claim response suppressed delivery while desktop remained online")
	}
}

func TestExpiredClaimAndOrphanClaimNeverPresent(t *testing.T) {
	b := deliveryCore(t)
	drop := &dropResponse{base: http.DefaultTransport, kind: "delivery_claim"}
	b.client.Transport = drop
	presentations := 0
	p := newDeliveryPump(b, func(delivery) bool { presentations++; return true })
	p.step(deliverySnapshot(t, b))
	current := deliverySnapshot(t, b)
	// A new host/epoch must not adopt a claim for which it owns no command history.
	orphan := newDeliveryPump(b, func(delivery) bool { presentations++; return true })
	orphan.step(current)
	// Let the real scheduler expire the unobserved desktop's claim.
	deadline := time.Now().Add(3 * time.Second)
	for deliverySnapshot(t, b)[0].Status != "expired" {
		if time.Now().After(deadline) {
			t.Fatal("scheduler did not expire claim")
		}
		time.Sleep(30 * time.Millisecond)
	}
	// Even a queued stale claimed snapshot cannot resurrect an expired context.
	p.step(current)
	p.step(deliverySnapshot(t, b))
	if presentations != 0 {
		t.Fatal("expired or orphan claim presented")
	}
}
func TestFailedNativeSubmissionRetriesOnlyOriginalNegativeReceipt(t *testing.T) {
	b := deliveryCore(t)
	drop := &dropResponse{base: http.DefaultTransport, kind: "delivery_receipt", before: true}
	b.client.Transport = drop
	presentations := 0
	p := newDeliveryPump(b, func(delivery) bool { presentations++; return false })
	for i := 0; i < 4; i++ {
		p.step(deliverySnapshot(t, b))
	}
	if presentations != 1 || deliverySnapshot(t, b)[0].Status != "failed" {
		t.Fatal("negative receipt changed or presentation repeated")
	}
	if len(drop.bodies) != 2 || string(drop.bodies[0]) != string(drop.bodies[1]) {
		t.Fatal("negative receipt must retry unchanged")
	}
}
