package supervisor

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"
)

type fakeProcess struct {
	pid  int
	done chan error
}

func newFakeProcess(pid int) *fakeProcess {
	return &fakeProcess{pid: pid, done: make(chan error, 1)}
}

func (p *fakeProcess) PID() int    { return p.pid }
func (p *fakeProcess) Wait() error { return <-p.done }
func (p *fakeProcess) Kill() error {
	p.finish(errors.New("killed"))
	return nil
}
func (p *fakeProcess) finish(err error) {
	select {
	case p.done <- err:
	default:
	}
}

func TestUnexpectedExitRestartsWithBackoffAndLimit(t *testing.T) {
	processes := []*fakeProcess{newFakeProcess(1), newFakeProcess(2), newFakeProcess(3)}
	var mu sync.Mutex
	launches := 0
	var events []Event

	s, err := New(Config{
		Launch: func(context.Context) (Process, error) {
			mu.Lock()
			defer mu.Unlock()
			p := processes[launches]
			launches++
			return p, nil
		},
		CheckHealth:         func(context.Context) error { return nil },
		MaxRestarts:         2,
		BaseBackoff:         time.Millisecond,
		HealthTimeout:       time.Second,
		HealthRetryInterval: time.Millisecond,
		OnEvent: func(e Event) {
			mu.Lock()
			events = append(events, e)
			mu.Unlock()
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := s.Start(context.Background()); err != nil {
		t.Fatal(err)
	}
	processes[0].finish(errors.New("crash 1"))
	waitFor(t, func() bool { mu.Lock(); defer mu.Unlock(); return launches == 2 })
	processes[1].finish(errors.New("crash 2"))
	waitFor(t, func() bool { mu.Lock(); defer mu.Unlock(); return launches == 3 })
	processes[2].finish(errors.New("crash 3"))
	waitFor(t, func() bool {
		select {
		case <-s.Done():
			return true
		default:
			return false
		}
	})

	if got := s.Status().State; got != "restart_limit_reached" {
		t.Fatalf("state = %q, want restart_limit_reached", got)
	}
	mu.Lock()
	defer mu.Unlock()
	backoffs := 0
	limit := false
	for _, event := range events {
		if event.Kind == "restart_backoff" {
			backoffs++
		}
		if event.Kind == "restart_limit_reached" {
			limit = true
		}
	}
	if backoffs != 2 || !limit {
		t.Fatalf("backoffs=%d limit=%v events=%+v", backoffs, limit, events)
	}
}

func TestExplicitStopDoesNotRestart(t *testing.T) {
	process := newFakeProcess(7)
	launches := 0
	s, err := New(Config{
		Launch: func(context.Context) (Process, error) {
			launches++
			return process, nil
		},
		CheckHealth: func(context.Context) error { return nil },
		RequestGracefulStop: func(context.Context) error {
			process.finish(nil)
			return nil
		},
		MaxRestarts:         3,
		BaseBackoff:         time.Millisecond,
		HealthTimeout:       time.Second,
		HealthRetryInterval: time.Millisecond,
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := s.Start(context.Background()); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	if err := s.Stop(ctx); err != nil {
		t.Fatal(err)
	}
	if launches != 1 {
		t.Fatalf("launches = %d, want 1", launches)
	}
	if got := s.Status().State; got != "stopped" {
		t.Fatalf("state = %q, want stopped", got)
	}
}

func TestNewRejectsInvalidConfig(t *testing.T) {
	if _, err := New(Config{}); err == nil {
		t.Fatal("New accepted a nil launcher")
	}
}

func waitFor(t *testing.T, condition func() bool) {
	t.Helper()
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		if condition() {
			return
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatal("timed out waiting for condition")
}
