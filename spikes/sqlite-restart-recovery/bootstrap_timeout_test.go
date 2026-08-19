package main

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

func TestStartCoreCommandTimesOutWhenLiveCoreDoesNotPublishBootstrap(t *testing.T) {
	if testing.Short() {
		t.Skip("starts a helper Core process")
	}

	temporaryDirectory := t.TempDir()
	handoffDirectory := filepath.Join(temporaryDirectory, "handoff", "run-timeout")
	if err := os.MkdirAll(handoffDirectory, 0o700); err != nil {
		t.Fatalf("create handoff directory: %v", err)
	}
	bootstrapPath := filepath.Join(handoffDirectory, "handoff.json")
	startedPath := filepath.Join(temporaryDirectory, "live-core-started")
	command := exec.Command(os.Args[0], "-test.run=^TestBootstrapTimeoutHelperProcess$", "--")
	command.Env = append(os.Environ(),
		"V03_TEST_LIVE_CORE_WITHOUT_BOOTSTRAP=1",
		"V03_TEST_LIVE_CORE_STARTED_PATH="+startedPath,
	)
	t.Cleanup(func() {
		if command.Process != nil && (command.ProcessState == nil || !command.ProcessState.Exited()) {
			_ = command.Process.Kill()
		}
	})

	const handshakeTimeout = 500 * time.Millisecond
	parent, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	startedAt := time.Now()
	core, _, err := startCoreCommand(
		parent,
		command,
		nil,
		bootstrapPath,
		handoffDirectory,
		handshakeTimeout,
	)
	elapsed := time.Since(startedAt)

	if !errors.Is(err, errBootstrapTimeout) {
		t.Fatalf("expected errBootstrapTimeout, got %v", err)
	}
	if core != nil {
		t.Fatal("timed-out Core must not be returned as active")
	}
	if elapsed < handshakeTimeout || elapsed > 2*time.Second {
		t.Fatalf("bootstrap wait duration %s is outside the configured bounded interval", elapsed)
	}
	if _, err := os.Stat(startedPath); err != nil {
		t.Fatalf("helper Core did not become live before timeout: %v", err)
	}
	if command.ProcessState == nil || !command.ProcessState.Exited() {
		t.Fatal("timed-out Core process was not reaped")
	}
	if _, err := os.Stat(handoffDirectory); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("timed-out handoff directory remains after cleanup: %v", err)
	}
}

func TestBootstrapTimeoutHelperProcess(t *testing.T) {
	if os.Getenv("V03_TEST_LIVE_CORE_WITHOUT_BOOTSTRAP") != "1" {
		return
	}
	if err := os.WriteFile(os.Getenv("V03_TEST_LIVE_CORE_STARTED_PATH"), []byte("live"), 0o600); err != nil {
		os.Exit(2)
	}
	select {}
}
