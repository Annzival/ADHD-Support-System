package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"sync"
	"time"
)

var errBootstrapTimeout = errors.New("bootstrap was not published before timeout")

type bootstrapRecord struct {
	Endpoint string `json:"endpoint"`
	PortMode string `json:"portMode"`
	Token    string `json:"token"`
}

type coreProcess struct {
	cmd      *exec.Cmd
	details  bootstrapRecord
	done     chan struct{}
	mu       sync.Mutex
	waitErr  error
	stopOnce sync.Once
	stopErr  error
}

func (p *coreProcess) wait(ctx context.Context) error {
	select {
	case <-p.done:
		p.mu.Lock()
		defer p.mu.Unlock()
		return p.waitErr
	case <-ctx.Done():
		return ctx.Err()
	}
}

func (p *coreProcess) hasExited() bool {
	select {
	case <-p.done:
		return true
	default:
		return false
	}
}

func (p *coreProcess) stop() error {
	p.stopOnce.Do(func() {
		if !p.hasExited() && p.cmd.Process != nil {
			_ = p.cmd.Process.Kill()
		}
		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()
		p.stopErr = p.wait(ctx)
	})
	return p.stopErr
}

// startCoreCommand is the process-lifecycle seam shared by the Windows host
// and the portable timeout regression test. It owns cleanup only before a
// bootstrap record has been consumed; the host owns cleanup after success.
func startCoreCommand(
	parent context.Context,
	command *exec.Cmd,
	output io.Closer,
	bootstrapPath string,
	handoffDirectory string,
	handshakeTimeout time.Duration,
) (*coreProcess, bootstrapRecord, error) {
	if handshakeTimeout <= 0 {
		if output != nil {
			_ = output.Close()
		}
		_ = os.RemoveAll(handoffDirectory)
		return nil, bootstrapRecord{}, errors.New("bootstrap timeout must be positive")
	}
	if err := command.Start(); err != nil {
		if output != nil {
			_ = output.Close()
		}
		_ = os.RemoveAll(handoffDirectory)
		return nil, bootstrapRecord{}, err
	}

	core := &coreProcess{cmd: command, done: make(chan struct{})}
	go func() {
		err := command.Wait()
		if output != nil {
			_ = output.Close()
		}
		core.mu.Lock()
		core.waitErr = err
		core.mu.Unlock()
		close(core.done)
	}()

	bootstrapContext, cancel := context.WithTimeout(parent, handshakeTimeout)
	defer cancel()
	record, err := waitForBootstrap(bootstrapContext, bootstrapPath)
	if err == nil {
		return core, record, nil
	}

	cleanupErr := cleanupFailedBootstrap(core, handoffDirectory)
	if errors.Is(err, context.DeadlineExceeded) && parent.Err() == nil {
		if cleanupErr == nil {
			return nil, bootstrapRecord{}, errBootstrapTimeout
		}
		return nil, bootstrapRecord{}, errors.Join(errBootstrapTimeout, cleanupErr)
	}
	if cleanupErr != nil {
		return nil, bootstrapRecord{}, errors.Join(err, cleanupErr)
	}
	return nil, bootstrapRecord{}, err
}

func cleanupFailedBootstrap(core *coreProcess, handoffDirectory string) error {
	_ = core.stop()
	if !core.hasExited() {
		return errors.New("Core process did not exit after bootstrap failure")
	}
	if err := os.RemoveAll(handoffDirectory); err != nil {
		return fmt.Errorf("remove failed bootstrap handoff: %w", err)
	}
	return nil
}

func waitForBootstrap(ctx context.Context, path string) (bootstrapRecord, error) {
	for {
		raw, err := os.ReadFile(path)
		if err == nil {
			var record bootstrapRecord
			if err := json.Unmarshal(raw, &record); err != nil {
				return bootstrapRecord{}, fmt.Errorf("parse bootstrap: %w", err)
			}
			return record, nil
		}
		if !errors.Is(err, os.ErrNotExist) {
			return bootstrapRecord{}, err
		}
		select {
		case <-ctx.Done():
			return bootstrapRecord{}, ctx.Err()
		case <-time.After(30 * time.Millisecond):
		}
	}
}
