package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

type endpoint struct {
	Endpoint string `json:"endpoint"`
	Token    string `json:"token"`
}
type bridge struct {
	mu      sync.RWMutex
	current endpoint
	client  *http.Client
}

func newBridge() *bridge             { return &bridge{client: &http.Client{Timeout: 3 * time.Second}} }
func (b *bridge) set(value endpoint) { b.mu.Lock(); defer b.mu.Unlock(); b.current = value }
func (b *bridge) get() endpoint      { b.mu.RLock(); defer b.mu.RUnlock(); return b.current }
func (b *bridge) request(method, path string, body []byte) (int, []byte, error) {
	material := b.get()
	if material.Endpoint == "" {
		return 503, nil, errors.New("core unavailable")
	}
	req, err := http.NewRequest(method, material.Endpoint+path, bytes.NewReader(body))
	if err != nil {
		return 503, nil, err
	}
	req.Header.Set("Authorization", "Bearer "+material.Token)
	req.Header.Set("Content-Type", "application/json")
	resp, err := b.client.Do(req)
	if err != nil {
		return 503, nil, errors.New("core unavailable")
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	return resp.StatusCode, data, err
}
func (b *bridge) command(kind, target string, version int, payload any, id string) bool {
	data, _ := json.Marshal(map[string]any{"kind": kind, "target": target, "version": version, "payload": payload, "command_id": id})
	status, _, err := b.request("POST", "/v1/commands", data)
	return err == nil && status == 200
}
func (b *bridge) serve(w http.ResponseWriter, r *http.Request) {
	allowed := map[string]string{"/api/state": "GET", "/api/commands": "POST", "/api/context": "POST"}
	if allowed[r.URL.Path] != r.Method || r.Header.Get("X-I01-Client") != "1" {
		http.Error(w, "invalid embedded client request", 403)
		return
	}
	var data []byte
	var err error
	if r.Body != nil {
		data, err = io.ReadAll(http.MaxBytesReader(w, r.Body, 16384))
	}
	if err != nil {
		http.Error(w, "invalid body", 400)
		return
	}
	status, result, err := b.request(r.Method, strings.Replace(r.URL.Path, "/api/", "/v1/", 1), data)
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	if err != nil {
		status = 503
		result = []byte(`{"error":"core_unavailable_retry_same_command"}`)
	}
	w.WriteHeader(status)
	_, _ = w.Write(result)
}

// Mechanical process ownership only. No database access or domain recovery here.
type process struct {
	command *exec.Cmd
	done    chan struct{}
}

func (p *process) stop() {
	select {
	case <-p.done:
		return
	default:
	}
	_ = p.command.Process.Kill()
	<-p.done
}
func launch(ctx context.Context, python, root, data string, timeout time.Duration) (*process, endpoint, error) {
	handoff, err := os.MkdirTemp(data, "handoff-")
	if err != nil {
		return nil, endpoint{}, err
	}
	defer os.RemoveAll(handoff)
	path := filepath.Join(handoff, "bootstrap.json")
	command := exec.Command(python, "-m", "agent_core", "serve", "--data-dir", data, "--bootstrap", path)
	command.Dir = root
	// Do not pass runtime material into arguments, environment overrides or logs.
	if err = command.Start(); err != nil {
		return nil, endpoint{}, err
	}
	p := &process{command: command, done: make(chan struct{})}
	go func() { _ = command.Wait(); close(p.done) }()
	deadline, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	ticker := time.NewTicker(30 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-deadline.Done():
			p.stop()
			return nil, endpoint{}, errors.New("bootstrap timeout")
		case <-p.done:
			return nil, endpoint{}, errors.New("core exited before bootstrap")
		case <-ticker.C:
			raw, readErr := os.ReadFile(path)
			if os.IsNotExist(readErr) {
				continue
			}
			if readErr != nil {
				p.stop()
				return nil, endpoint{}, readErr
			}
			var value endpoint
			if json.Unmarshal(raw, &value) != nil {
				p.stop()
				return nil, endpoint{}, errors.New("invalid bootstrap")
			}
			parsed, parseErr := url.Parse(value.Endpoint)
			if parseErr != nil || parsed.Scheme != "http" || parsed.Hostname() != "127.0.0.1" || parsed.Port() == "" || len(value.Token) < 32 || parsed.Path != "" || parsed.User != nil {
				p.stop()
				return nil, endpoint{}, errors.New("invalid bootstrap endpoint")
			}
			return p, value, nil
		}
	}
}
