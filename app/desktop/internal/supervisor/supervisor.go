// Package supervisor provides only mechanical child-process supervision.
// It deliberately has no knowledge of product state, scheduling, persistence,
// notifications, or LLMs.
package supervisor

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"
)

// Process is the small surface the supervisor needs from a child process.
type Process interface {
	PID() int
	Wait() error
	Kill() error
}

// Launcher starts one child process.
type Launcher func(context.Context) (Process, error)

// HealthChecker verifies that a newly launched child is usable.
type HealthChecker func(context.Context) error

// GracefulStopper asks the child to exit normally before the supervisor uses
// Process.Kill as a timeout fallback.
type GracefulStopper func(context.Context) error

// Event is a machine-readable lifecycle record. The Windows host writes these
// records to JSONL so the real-machine evidence can be checked independently.
type Event struct {
	Time    time.Time `json:"time"`
	Kind    string    `json:"kind"`
	PID     int       `json:"pid,omitempty"`
	Restart int       `json:"restart,omitempty"`
	Backoff string    `json:"backoff,omitempty"`
	Message string    `json:"message,omitempty"`
}

// Status is observational process state, not application/domain state.
type Status struct {
	State        string `json:"state"`
	PID          int    `json:"pid,omitempty"`
	RestartCount int    `json:"restartCount"`
	LastError    string `json:"lastError,omitempty"`
}

// Config controls bounded process supervision.
type Config struct {
	Launch              Launcher
	CheckHealth         HealthChecker
	RequestGracefulStop GracefulStopper
	OnEvent             func(Event)
	MaxRestarts         int
	BaseBackoff         time.Duration
	HealthTimeout       time.Duration
	HealthRetryInterval time.Duration
}

// Supervisor restarts unexpected child exits with exponential backoff. It has
// no restart loop after an explicit Stop call or after the configured cap.
type Supervisor struct {
	config Config

	mu         sync.RWMutex
	process    Process
	status     Status
	running    bool
	stopping   bool
	done       chan struct{}
	stopSignal chan struct{}
}

// New validates process-only configuration.
func New(config Config) (*Supervisor, error) {
	if config.Launch == nil {
		return nil, errors.New("supervisor: Launch is required")
	}
	if config.MaxRestarts < 0 {
		return nil, errors.New("supervisor: MaxRestarts cannot be negative")
	}
	if config.BaseBackoff <= 0 {
		return nil, errors.New("supervisor: BaseBackoff must be positive")
	}
	if config.HealthTimeout <= 0 {
		return nil, errors.New("supervisor: HealthTimeout must be positive")
	}
	if config.HealthRetryInterval <= 0 {
		return nil, errors.New("supervisor: HealthRetryInterval must be positive")
	}
	return &Supervisor{config: config, status: Status{State: "stopped"}}, nil
}

// Start launches and health-checks the initial child synchronously, then
// observes its lifecycle in the background.
func (s *Supervisor) Start(ctx context.Context) error {
	s.mu.Lock()
	if s.running {
		s.mu.Unlock()
		return errors.New("supervisor: already running")
	}
	s.running = true
	s.stopping = false
	s.done = make(chan struct{})
	s.stopSignal = make(chan struct{})
	s.status = Status{State: "starting"}
	s.mu.Unlock()

	process, err := s.startOne(ctx)
	if err != nil {
		s.finish("failed", err)
		return err
	}
	go s.monitor(process)
	return nil
}

// Stop marks the shutdown as explicit before requesting a graceful child
// exit. That ordering prevents a normal shutdown from looking like a crash.
func (s *Supervisor) Stop(ctx context.Context) error {
	s.mu.Lock()
	if !s.running {
		s.mu.Unlock()
		return nil
	}
	if !s.stopping {
		s.stopping = true
		s.status.State = "stopping"
		close(s.stopSignal)
	}
	process := s.process
	done := s.done
	s.mu.Unlock()

	s.emit(Event{Kind: "explicit_stop_requested", PID: processPID(process)})
	if process != nil && s.config.RequestGracefulStop != nil {
		if err := s.config.RequestGracefulStop(ctx); err != nil {
			s.emit(Event{Kind: "graceful_stop_request_failed", PID: process.PID(), Message: err.Error()})
		}
	}

	select {
	case <-done:
		return nil
	case <-ctx.Done():
		if process != nil {
			if err := process.Kill(); err != nil {
				return fmt.Errorf("supervisor: graceful stop timed out and kill failed: %w", err)
			}
			s.emit(Event{Kind: "forced_stop_after_timeout", PID: process.PID()})
		}
		return ctx.Err()
	}
}

// Done closes when this supervisor has stopped, failed initial startup, or
// reached its restart cap.
func (s *Supervisor) Done() <-chan struct{} {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.done
}

// Status returns only mechanical child-process observations.
func (s *Supervisor) Status() Status {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.status
}

func (s *Supervisor) monitor(process Process) {
	restarts := 0
	for {
		err := process.Wait()
		s.mu.Lock()
		stopping := s.stopping
		if s.process == process {
			s.process = nil
		}
		s.status.PID = 0
		s.mu.Unlock()

		if stopping {
			s.emit(Event{Kind: "explicit_stop_completed", PID: process.PID(), Message: errorText(err)})
			s.finish("stopped", nil)
			return
		}

		s.emit(Event{Kind: "unexpected_exit", PID: process.PID(), Restart: restarts, Message: errorText(err)})
		for {
			if restarts >= s.config.MaxRestarts {
				s.emit(Event{Kind: "restart_limit_reached", PID: processPID(process), Restart: restarts, Message: errorText(err)})
				s.finish("restart_limit_reached", err)
				return
			}

			backoff := s.config.BaseBackoff << restarts
			restarts++
			s.mu.Lock()
			s.status = Status{State: "backing_off", RestartCount: restarts, LastError: errorText(err)}
			stopSignal := s.stopSignal
			s.mu.Unlock()
			s.emit(Event{Kind: "restart_backoff", Restart: restarts, Backoff: backoff.String(), Message: errorText(err)})

			select {
			case <-time.After(backoff):
			case <-stopSignal:
				s.emit(Event{Kind: "explicit_stop_completed", Restart: restarts, Message: "stop during backoff"})
				s.finish("stopped", nil)
				return
			}

			var startErr error
			process, startErr = s.startOne(context.Background())
			if startErr == nil {
				break
			}

			s.mu.RLock()
			stopping = s.stopping
			s.mu.RUnlock()
			if stopping {
				s.emit(Event{Kind: "explicit_stop_completed", Restart: restarts, Message: "stop during startup"})
				s.finish("stopped", nil)
				return
			}
			err = startErr
			s.emit(Event{Kind: "restart_start_failed", Restart: restarts, Message: startErr.Error()})
		}
	}
}

func (s *Supervisor) startOne(ctx context.Context) (Process, error) {
	process, err := s.config.Launch(ctx)
	if err != nil {
		return nil, fmt.Errorf("supervisor: launch child: %w", err)
	}

	s.mu.Lock()
	stopping := s.stopping
	if !stopping {
		s.process = process
		s.status.State = "health_checking"
		s.status.PID = process.PID()
	}
	s.mu.Unlock()
	if stopping {
		_ = process.Kill()
		return nil, errors.New("supervisor: stopped while launching child")
	}

	s.emit(Event{Kind: "agent_started", PID: process.PID()})
	if err := s.waitForHealth(ctx); err != nil {
		_ = process.Kill()
		_ = process.Wait()
		s.mu.Lock()
		if s.process == process {
			s.process = nil
		}
		s.mu.Unlock()
		return nil, err
	}

	s.mu.Lock()
	s.status = Status{State: "healthy", PID: process.PID(), RestartCount: s.status.RestartCount}
	s.mu.Unlock()
	s.emit(Event{Kind: "health_check_passed", PID: process.PID()})
	return process, nil
}

func (s *Supervisor) waitForHealth(parent context.Context) error {
	if s.config.CheckHealth == nil {
		return nil
	}
	ctx, cancel := context.WithTimeout(parent, s.config.HealthTimeout)
	defer cancel()
	var lastErr error
	for {
		if err := s.config.CheckHealth(ctx); err == nil {
			return nil
		} else {
			lastErr = err
		}
		select {
		case <-ctx.Done():
			return fmt.Errorf("supervisor: health check timed out: %w", lastErr)
		case <-time.After(s.config.HealthRetryInterval):
		}
	}
}

func (s *Supervisor) finish(state string, err error) {
	s.mu.Lock()
	if !s.running {
		s.mu.Unlock()
		return
	}
	s.running = false
	s.status.State = state
	s.status.PID = 0
	s.status.LastError = errorText(err)
	done := s.done
	s.mu.Unlock()
	close(done)
}

func (s *Supervisor) emit(event Event) {
	if s.config.OnEvent == nil {
		return
	}
	event.Time = time.Now().UTC()
	s.config.OnEvent(event)
}

func processPID(process Process) int {
	if process == nil {
		return 0
	}
	return process.PID()
}

func errorText(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}
