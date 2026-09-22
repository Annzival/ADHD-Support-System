package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestBridgeForwardsCoreStatusAndNeverReportsUnavailableAsSuccess(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer private-run-token" || r.URL.Path != "/v1/commands" {
			t.Error("wrong Core request")
		}
		w.WriteHeader(409)
		_, _ = w.Write([]byte(`{"error":"stale_context"}`))
	}))
	defer upstream.Close()
	bridge := newBridge()
	bridge.set(endpoint{Endpoint: upstream.URL, Token: "private-run-token"})
	request := httptest.NewRequest("POST", "/api/commands", strings.NewReader(`{"kind":"start"}`))
	request.Header.Set("X-I01-Client", "1")
	response := httptest.NewRecorder()
	bridge.serve(response, request)
	if response.Code != 409 || strings.Contains(response.Body.String(), "private-run-token") {
		t.Fatal("status or material boundary violated")
	}
	bridge.set(endpoint{})
	request = httptest.NewRequest("GET", "/api/state", nil)
	request.Header.Set("X-I01-Client", "1")
	response = httptest.NewRecorder()
	bridge.serve(response, request)
	if response.Code != 503 {
		t.Fatal("unavailable Core appeared ready")
	}
}

func TestBootstrapTimeoutReapsChildAndRemovesHandoff(t *testing.T) {
	if os.Getenv("I01_TIMEOUT_CHILD") == "1" {
		time.Sleep(30 * time.Second)
		return
	}
	// The test binary ignores Core arguments and deliberately never publishes a bootstrap.
	t.Setenv("I01_TIMEOUT_CHILD", "1")
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	// A small shell-free helper executable uses the same child mode on either OS.
	// TestMain below detects the launch arguments before testing parses flags.
	start := time.Now()
	directory := t.TempDir()
	process, _, err := launch(context.Background(), executable, directory, directory, 100*time.Millisecond)
	if err == nil || process != nil || time.Since(start) > 3*time.Second {
		t.Fatal("timeout did not stop child")
	}
	entries, _ := os.ReadDir(directory)
	if len(entries) != 0 {
		t.Fatal("handoff leaked")
	}
}

func TestMain(m *testing.M) {
	if os.Getenv("I01_TIMEOUT_CHILD") == "1" && len(os.Args) > 1 && os.Args[1] == "-m" {
		time.Sleep(30 * time.Second)
		os.Exit(0)
	}
	os.Exit(m.Run())
}

func TestBootstrapRealCoreConsumesMaterialAndPreservesState(t *testing.T) {
	python := os.Getenv("I01_TEST_PYTHON")
	if python == "" {
		python = "python3"
	}
	if _, err := exec.LookPath(python); err != nil {
		t.Skip("set I01_TEST_PYTHON to locked Python")
	}
	root, err := filepath.Abs("..")
	if err != nil {
		t.Fatal(err)
	}
	data := filepath.Join(t.TempDir(), "data")
	seed := exec.Command(python, "-m", "agent_core", "seed", "--data-dir", data, "--confirm-development-fixture")
	seed.Dir = root
	if output, err := seed.CombinedOutput(); err != nil {
		t.Fatalf("seed: %s", output)
	}
	process, material, err := launch(context.Background(), python, root, data, 3*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	defer process.stop()
	entries, _ := filepath.Glob(filepath.Join(data, "handoff-*"))
	if len(entries) != 0 {
		t.Fatal("bootstrap not consumed")
	}
	b := newBridge()
	b.set(material)
	status, raw, err := b.request("GET", "/v1/state", nil)
	if err != nil || status != 200 {
		t.Fatal("Core not connected")
	}
	var state map[string]any
	if json.Unmarshal(raw, &state) != nil || state["database_id"] == nil {
		t.Fatal("missing authority")
	}
	old := material
	process.stop()
	process, material, err = launch(context.Background(), python, root, data, 3*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	defer process.stop()
	if old.Token == material.Token {
		t.Fatal("run credential reused")
	}
	b.set(endpoint{Endpoint: material.Endpoint, Token: old.Token})
	status, _, _ = b.request("GET", "/v1/state", nil)
	if status != 401 {
		t.Fatal("old credential accepted")
	}
	b.set(material)
	status, raw, _ = b.request("GET", "/v1/state", nil)
	var recovered map[string]any
	_ = json.Unmarshal(raw, &recovered)
	if status != 200 || recovered["database_id"] != state["database_id"] {
		t.Fatal("authority identity changed")
	}
}
