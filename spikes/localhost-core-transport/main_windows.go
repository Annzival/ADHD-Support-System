//go:build windows

package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha1"
	"embed"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/wailsapp/wails/v3/pkg/application"
)

const (
	applicationName = "ADHD Support System V-02 transport spike"
	fakeContextID   = "v02-fake-context-0001"
	fakeContextKind = "v02_fake_context"
	websocketGUID   = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
)

//go:embed all:frontend
var assets embed.FS

var errHandshakeTimeout = errors.New("bootstrap was not published before timeout")

type runConfig struct {
	PythonExecutable    string `json:"pythonExecutable"`
	WebView2BrowserPath string `json:"webView2BrowserPath"`
	EvidenceDirectory   string `json:"evidenceDirectory"`
	HandshakeTimeoutMS  int    `json:"handshakeTimeoutMs"`
}

type bootstrapRecord struct {
	Endpoint string `json:"endpoint"`
	PortMode string `json:"port_mode"`
	Token    string `json:"token"`
}

type eventLogger struct {
	mu   sync.Mutex
	path string
}

// record accepts only operational diagnostics. The temporary credential is
// deliberately rejected here so it cannot reach ordinary host logs.
func (l *eventLogger) record(kind string, fields map[string]any) {
	for key := range fields {
		normalized := strings.ToLower(key)
		if strings.Contains(normalized, "token") || strings.Contains(normalized, "credential") || strings.Contains(normalized, "authorization") {
			log.Printf("refused a sensitive field for event %q", kind)
			return
		}
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	if err := os.MkdirAll(filepath.Dir(l.path), 0o700); err != nil {
		log.Printf("create event directory: %v", err)
		return
	}
	entry := map[string]any{
		"time": time.Now().UTC().Format(time.RFC3339Nano),
		"kind": kind,
	}
	for key, value := range fields {
		entry[key] = value
	}
	encoded, err := json.Marshal(entry)
	if err != nil {
		log.Printf("marshal event %q: %v", kind, err)
		return
	}
	handle, err := os.OpenFile(l.path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o600)
	if err != nil {
		log.Printf("open event log: %v", err)
		return
	}
	defer handle.Close()
	if _, err := handle.Write(append(encoded, '\n')); err != nil {
		log.Printf("write event log: %v", err)
	}
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

type websocketClient struct {
	connection net.Conn
	reader     *bufio.Reader
}

func (c *websocketClient) close() {
	if c != nil && c.connection != nil {
		_ = c.connection.Close()
	}
}

type validationResult struct {
	SchemaVersion    int               `json:"schemaVersion"`
	Spike            string            `json:"spike"`
	GeneratedAt      string            `json:"generatedAt"`
	CandidateStatus  string            `json:"candidateStatus"`
	Checks           map[string]string `json:"checks"`
	DiagnosticCodes  []string          `json:"diagnosticCodes"`
	HandshakeMethod  string            `json:"handshakeMethod"`
	FakeContextID    string            `json:"fakeContextId"`
	EndpointFamilies []string          `json:"endpointFamilies"`
}

type host struct {
	app    *application.App
	root   string
	config runConfig
	logger *eventLogger

	activeMu sync.Mutex
	active   *coreProcess
}

func main() {
	root := resolveRoot()
	config, err := loadRunConfig(root)
	if err != nil {
		log.Fatal(err)
	}
	if config.PythonExecutable == "" || config.WebView2BrowserPath == "" || config.EvidenceDirectory == "" {
		log.Fatal("run configuration must provide Python, fixed WebView2, and an evidence directory")
	}
	if config.HandshakeTimeoutMS <= 0 {
		config.HandshakeTimeoutMS = 900
	}

	h := &host{
		root:   root,
		config: config,
		logger: &eventLogger{path: filepath.Join(config.EvidenceDirectory, "host-events.jsonl")},
	}
	h.logger.record("host_starting", map[string]any{"mode": "automatic_transport_validation"})

	h.app = application.New(application.Options{
		Name:        applicationName,
		Description: "V-02 localhost transport validation only",
		Assets: application.AssetOptions{
			Handler: application.BundledAssetFileServer(assets),
		},
		Windows: application.WindowsOptions{
			WebviewBrowserPath: config.WebView2BrowserPath,
		},
	})
	h.app.Window.NewWithOptions(application.WebviewWindowOptions{
		Name:             "transport-validation",
		Title:            applicationName,
		Width:            620,
		Height:           360,
		MinWidth:         620,
		MinHeight:        360,
		BackgroundColour: application.NewRGB(250, 250, 250),
		URL:              "/",
	})
	h.app.OnShutdown(func() {
		h.stopActiveCore()
		h.logger.record("wails_shutdown", map[string]any{})
	})

	go h.runThenQuit()
	if err := h.app.Run(); err != nil {
		log.Fatal(err)
	}
}

func (h *host) runThenQuit() {
	// Let Wails initialise its real Windows/WebView2 application before the
	// automatic host-to-Core checks begin.
	time.Sleep(500 * time.Millisecond)
	result := h.runValidation(context.Background())
	if err := h.writeCandidateResult(result); err != nil {
		log.Printf("write candidate result: %v", err)
	} else {
		h.logger.record("validation_finished", map[string]any{"candidate_status": result.CandidateStatus})
	}
	time.Sleep(250 * time.Millisecond)
	h.app.Quit()
}

func (h *host) newResult() validationResult {
	return validationResult{
		SchemaVersion:   1,
		Spike:           "V-02",
		GeneratedAt:     time.Now().UTC().Format(time.RFC3339Nano),
		CandidateStatus: "FAIL",
		Checks: map[string]string{
			"loopback_dynamic_endpoint":           "BLOCKED",
			"bootstrap_timeout_is_not_ready":      "BLOCKED",
			"bootstrap_deleted_after_read":        "BLOCKED",
			"authenticated_http_round_trip":       "BLOCKED",
			"authenticated_websocket_round_trip":  "BLOCKED",
			"http_missing_rejected":               "BLOCKED",
			"websocket_missing_rejected":          "BLOCKED",
			"http_incorrect_rejected":             "BLOCKED",
			"websocket_incorrect_rejected":        "BLOCKED",
			"core_unavailable_is_not_ready":       "BLOCKED",
			"old_websocket_invalid_after_restart": "BLOCKED",
			"new_run_material_changed":            "BLOCKED",
			"http_previous_run_rejected":          "BLOCKED",
			"websocket_previous_run_rejected":     "BLOCKED",
			"reconnected_http_round_trip":         "BLOCKED",
			"reconnected_websocket_round_trip":    "BLOCKED",
			"ordinary_logs_exclude_material":      "BLOCKED",
		},
		HandshakeMethod:  "one_time_bootstrap_file",
		FakeContextID:    fakeContextID,
		EndpointFamilies: []string{"127.0.0.1"},
	}
}

func (h *host) runValidation(parent context.Context) validationResult {
	result := h.newResult()
	timeoutContext, cancelTimeout := context.WithTimeout(parent, time.Duration(h.config.HandshakeTimeoutMS)*time.Millisecond)
	_, timeoutErr := h.startCore(timeoutContext, 2*time.Second)
	cancelTimeout()
	if errors.Is(timeoutErr, errHandshakeTimeout) {
		result.Checks["bootstrap_timeout_is_not_ready"] = "PASS"
		result.DiagnosticCodes = append(result.DiagnosticCodes, "bootstrap_timeout_not_ready")
		h.logger.record("bootstrap_timeout", map[string]any{"ready": false})
	} else {
		result.Checks["bootstrap_timeout_is_not_ready"] = "FAIL"
		result.DiagnosticCodes = append(result.DiagnosticCodes, diagnosticCode(timeoutErr))
	}

	coreOne, err := h.startCore(parent, 0)
	if err != nil {
		result.DiagnosticCodes = append(result.DiagnosticCodes, diagnosticCode(err))
		return result
	}
	h.setActiveCore(coreOne)
	defer h.stopActiveCore()

	if coreOne.details.PortMode == "dynamic" && endpointIsLoopback(coreOne.details.Endpoint) {
		result.Checks["loopback_dynamic_endpoint"] = "PASS"
	} else {
		result.Checks["loopback_dynamic_endpoint"] = "FAIL"
	}
	result.Checks["bootstrap_deleted_after_read"] = "PASS"

	if err := h.httpEcho(parent, coreOne.details.Endpoint, coreOne.details.Token); err == nil {
		result.Checks["authenticated_http_round_trip"] = "PASS"
	} else {
		result.Checks["authenticated_http_round_trip"] = "FAIL"
		result.DiagnosticCodes = append(result.DiagnosticCodes, diagnosticCode(err))
	}

	liveWebsocket, err := h.openWebsocket(coreOne.details.Endpoint, coreOne.details.Token)
	if err == nil {
		err = liveWebsocket.roundTrip()
	}
	if err == nil {
		result.Checks["authenticated_websocket_round_trip"] = "PASS"
	} else {
		result.Checks["authenticated_websocket_round_trip"] = "FAIL"
		result.DiagnosticCodes = append(result.DiagnosticCodes, diagnosticCode(err))
	}

	if h.httpRejected(parent, coreOne.details.Endpoint, "") {
		result.Checks["http_missing_rejected"] = "PASS"
	} else {
		result.Checks["http_missing_rejected"] = "FAIL"
	}
	if h.websocketRejected(coreOne.details.Endpoint, "") {
		result.Checks["websocket_missing_rejected"] = "PASS"
	} else {
		result.Checks["websocket_missing_rejected"] = "FAIL"
	}
	if h.httpRejected(parent, coreOne.details.Endpoint, "v02-intentionally-incorrect") {
		result.Checks["http_incorrect_rejected"] = "PASS"
	} else {
		result.Checks["http_incorrect_rejected"] = "FAIL"
	}
	if h.websocketRejected(coreOne.details.Endpoint, "v02-intentionally-incorrect") {
		result.Checks["websocket_incorrect_rejected"] = "PASS"
	} else {
		result.Checks["websocket_incorrect_rejected"] = "FAIL"
	}

	if err := h.requestRestart(parent, coreOne.details.Endpoint, coreOne.details.Token); err != nil {
		result.DiagnosticCodes = append(result.DiagnosticCodes, diagnosticCode(err))
		return result
	}
	exitContext, cancelExit := context.WithTimeout(parent, 3*time.Second)
	exitErr := coreOne.wait(exitContext)
	cancelExit()
	if exitErr != nil {
		result.DiagnosticCodes = append(result.DiagnosticCodes, diagnosticCode(exitErr))
		return result
	}
	h.clearActiveCore(coreOne)

	if err := h.httpUnavailable(parent, coreOne.details.Endpoint, coreOne.details.Token); err != nil {
		result.Checks["core_unavailable_is_not_ready"] = "PASS"
		result.DiagnosticCodes = append(result.DiagnosticCodes, "core_unavailable_not_ready")
		h.logger.record("core_unavailable", map[string]any{"ready": false})
	} else {
		result.Checks["core_unavailable_is_not_ready"] = "FAIL"
	}

	if liveWebsocket != nil {
		if err := liveWebsocket.roundTrip(); err != nil {
			result.Checks["old_websocket_invalid_after_restart"] = "PASS"
		} else {
			result.Checks["old_websocket_invalid_after_restart"] = "FAIL"
		}
		liveWebsocket.close()
	} else {
		result.Checks["old_websocket_invalid_after_restart"] = "FAIL"
	}

	coreTwo, err := h.startCore(parent, 0)
	if err != nil {
		result.DiagnosticCodes = append(result.DiagnosticCodes, diagnosticCode(err))
		return result
	}
	h.setActiveCore(coreTwo)
	if !sameMaterial(coreOne.details.Token, coreTwo.details.Token) {
		result.Checks["new_run_material_changed"] = "PASS"
	} else {
		result.Checks["new_run_material_changed"] = "FAIL"
	}
	if h.httpRejected(parent, coreTwo.details.Endpoint, coreOne.details.Token) {
		result.Checks["http_previous_run_rejected"] = "PASS"
	} else {
		result.Checks["http_previous_run_rejected"] = "FAIL"
	}
	if h.websocketRejected(coreTwo.details.Endpoint, coreOne.details.Token) {
		result.Checks["websocket_previous_run_rejected"] = "PASS"
	} else {
		result.Checks["websocket_previous_run_rejected"] = "FAIL"
	}
	if err := h.httpEcho(parent, coreTwo.details.Endpoint, coreTwo.details.Token); err == nil {
		result.Checks["reconnected_http_round_trip"] = "PASS"
	} else {
		result.Checks["reconnected_http_round_trip"] = "FAIL"
		result.DiagnosticCodes = append(result.DiagnosticCodes, diagnosticCode(err))
	}
	reconnectedWebsocket, err := h.openWebsocket(coreTwo.details.Endpoint, coreTwo.details.Token)
	if err == nil {
		err = reconnectedWebsocket.roundTrip()
		reconnectedWebsocket.close()
	}
	if err == nil {
		result.Checks["reconnected_websocket_round_trip"] = "PASS"
	} else {
		result.Checks["reconnected_websocket_round_trip"] = "FAIL"
		result.DiagnosticCodes = append(result.DiagnosticCodes, diagnosticCode(err))
	}
	if h.logsExcludeMaterials(coreOne.details.Token, coreTwo.details.Token) {
		result.Checks["ordinary_logs_exclude_material"] = "PASS"
	} else {
		result.Checks["ordinary_logs_exclude_material"] = "FAIL"
	}

	for _, status := range result.Checks {
		if status != "PASS" {
			return result
		}
	}
	result.CandidateStatus = "PASS"
	return result
}

func (h *host) setActiveCore(core *coreProcess) {
	h.activeMu.Lock()
	defer h.activeMu.Unlock()
	h.active = core
}

func (h *host) clearActiveCore(core *coreProcess) {
	h.activeMu.Lock()
	defer h.activeMu.Unlock()
	if h.active == core {
		h.active = nil
	}
}

func (h *host) stopActiveCore() {
	h.activeMu.Lock()
	core := h.active
	h.active = nil
	h.activeMu.Unlock()
	if core != nil {
		_ = core.stop()
	}
}

func (h *host) startCore(ctx context.Context, bootstrapDelay time.Duration) (*coreProcess, error) {
	handoffRoot := filepath.Join(h.config.EvidenceDirectory, "handoff")
	if err := os.MkdirAll(handoffRoot, 0o700); err != nil {
		return nil, err
	}
	handoffDirectory, err := os.MkdirTemp(handoffRoot, "run-")
	if err != nil {
		return nil, err
	}
	bootstrapPath := filepath.Join(handoffDirectory, "handoff.json")
	coreLogPath := filepath.Join(h.config.EvidenceDirectory, "core-events.jsonl")
	outputPath := filepath.Join(h.config.EvidenceDirectory, "core-output.log")
	output, err := os.OpenFile(outputPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o600)
	if err != nil {
		_ = os.RemoveAll(handoffDirectory)
		return nil, err
	}
	args := []string{
		filepath.Join(h.root, "agent_core", "agent_core_stub.py"),
		"--bootstrap-file",
		bootstrapPath,
	}
	if bootstrapDelay > 0 {
		args = append(args, "--bootstrap-delay-seconds", strconv.FormatFloat(bootstrapDelay.Seconds(), 'f', 3, 64))
	}
	command := exec.Command(h.config.PythonExecutable, args...)
	command.Dir = h.root
	command.Stdout = output
	command.Stderr = output
	command.Env = append(os.Environ(), "SPIKE_CORE_EVENT_LOG="+coreLogPath)
	if err := command.Start(); err != nil {
		_ = output.Close()
		_ = os.RemoveAll(handoffDirectory)
		return nil, err
	}
	core := &coreProcess{cmd: command, done: make(chan struct{})}
	go func() {
		err := command.Wait()
		_ = output.Close()
		core.mu.Lock()
		core.waitErr = err
		core.mu.Unlock()
		close(core.done)
	}()

	record, err := waitForBootstrap(ctx, bootstrapPath)
	if err != nil {
		_ = core.stop()
		_ = os.RemoveAll(handoffDirectory)
		if errors.Is(err, context.DeadlineExceeded) {
			return nil, errHandshakeTimeout
		}
		return nil, err
	}
	if !endpointIsLoopback(record.Endpoint) || record.PortMode != "dynamic" || record.Token == "" {
		_ = core.stop()
		_ = os.RemoveAll(handoffDirectory)
		return nil, errors.New("bootstrap did not contain a dynamic loopback endpoint")
	}
	if err := os.Remove(bootstrapPath); err != nil {
		_ = core.stop()
		_ = os.RemoveAll(handoffDirectory)
		return nil, fmt.Errorf("delete consumed bootstrap: %w", err)
	}
	if err := os.Remove(handoffDirectory); err != nil {
		_ = core.stop()
		return nil, fmt.Errorf("remove consumed bootstrap directory: %w", err)
	}
	if err := h.waitForAuthenticatedHealth(ctx, record); err != nil {
		_ = core.stop()
		return nil, err
	}
	core.details = record
	h.logger.record("bootstrap_consumed", map[string]any{"endpoint_family": "127.0.0.1", "deleted": true})
	return core, nil
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

func endpointIsLoopback(endpoint string) bool {
	parsed, err := url.Parse(endpoint)
	if err != nil || parsed.Scheme != "http" || parsed.Hostname() != "127.0.0.1" {
		return false
	}
	port, err := strconv.Atoi(parsed.Port())
	return err == nil && port > 0 && parsed.Path == ""
}

func (h *host) waitForAuthenticatedHealth(parent context.Context, record bootstrapRecord) error {
	ctx, cancel := context.WithTimeout(parent, 2*time.Second)
	defer cancel()
	for {
		status, _, err := h.httpRequest(ctx, record.Endpoint, record.Token, http.MethodGet, "/spike/health")
		if err == nil && status == http.StatusOK {
			return nil
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(30 * time.Millisecond):
		}
	}
}

func (h *host) httpEcho(ctx context.Context, endpoint, material string) error {
	status, body, err := h.httpRequest(ctx, endpoint, material, http.MethodGet, "/spike/http?context_id="+url.QueryEscape(fakeContextID))
	if err != nil {
		return err
	}
	if status != http.StatusOK {
		return fmt.Errorf("http echo status=%d", status)
	}
	var response struct {
		Kind      string `json:"kind"`
		ContextID string `json:"context_id"`
	}
	if err := json.Unmarshal(body, &response); err != nil {
		return err
	}
	if response.Kind != fakeContextKind+"_echo" || response.ContextID != fakeContextID {
		return errors.New("http echo did not return the fake context")
	}
	return nil
}

func (h *host) httpRejected(ctx context.Context, endpoint, material string) bool {
	status, body, err := h.httpRequest(ctx, endpoint, material, http.MethodGet, "/spike/http?context_id="+url.QueryEscape(fakeContextID))
	return err == nil && status == http.StatusUnauthorized && bytes.Equal(body, []byte("{\"error\":\"unauthorized\"}"))
}

func (h *host) httpUnavailable(ctx context.Context, endpoint, material string) error {
	_, _, err := h.httpRequest(ctx, endpoint, material, http.MethodGet, "/spike/health")
	return err
}

func (h *host) requestRestart(ctx context.Context, endpoint, material string) error {
	status, body, err := h.httpRequest(ctx, endpoint, material, http.MethodPost, "/spike/control/restart")
	if err != nil {
		return err
	}
	if status != http.StatusAccepted || !bytes.Equal(body, []byte("{\"accepted\":true}")) {
		return fmt.Errorf("restart status=%d", status)
	}
	return nil
}

func (h *host) httpRequest(ctx context.Context, endpoint, material, method, path string) (int, []byte, error) {
	request, err := http.NewRequestWithContext(ctx, method, endpoint+path, nil)
	if err != nil {
		return 0, nil, err
	}
	if material != "" {
		request.Header.Set("Authorization", "Bearer "+material)
	}
	client := &http.Client{Timeout: 2 * time.Second}
	response, err := client.Do(request)
	if err != nil {
		return 0, nil, err
	}
	defer response.Body.Close()
	body, err := io.ReadAll(response.Body)
	if err != nil {
		return 0, nil, err
	}
	return response.StatusCode, body, nil
}

func (h *host) openWebsocket(endpoint, material string) (*websocketClient, error) {
	parsed, err := url.Parse(endpoint)
	if err != nil {
		return nil, err
	}
	connection, err := net.DialTimeout("tcp", parsed.Host, 2*time.Second)
	if err != nil {
		return nil, err
	}
	closeOnError := func(err error) (*websocketClient, error) {
		_ = connection.Close()
		return nil, err
	}
	keyBytes := make([]byte, 16)
	if _, err := rand.Read(keyBytes); err != nil {
		return closeOnError(err)
	}
	key := base64.StdEncoding.EncodeToString(keyBytes)
	request, err := http.NewRequest(http.MethodGet, endpoint+"/spike/ws", nil)
	if err != nil {
		return closeOnError(err)
	}
	request.Header.Set("Upgrade", "websocket")
	request.Header.Set("Connection", "Upgrade")
	request.Header.Set("Sec-WebSocket-Key", key)
	request.Header.Set("Sec-WebSocket-Version", "13")
	if material != "" {
		request.Header.Set("Authorization", "Bearer "+material)
	}
	if err := request.Write(connection); err != nil {
		return closeOnError(err)
	}
	reader := bufio.NewReader(connection)
	response, err := http.ReadResponse(reader, request)
	if err != nil {
		return closeOnError(err)
	}
	if response.StatusCode != http.StatusSwitchingProtocols {
		_, _ = io.Copy(io.Discard, response.Body)
		_ = response.Body.Close()
		return closeOnError(fmt.Errorf("websocket upgrade status=%d", response.StatusCode))
	}
	hasher := sha1.New()
	_, _ = hasher.Write([]byte(key + websocketGUID))
	expectedAccept := base64.StdEncoding.EncodeToString(hasher.Sum(nil))
	if response.Header.Get("Sec-WebSocket-Accept") != expectedAccept {
		return closeOnError(errors.New("websocket accept key mismatch"))
	}
	return &websocketClient{connection: connection, reader: reader}, nil
}

func (h *host) websocketRejected(endpoint, material string) bool {
	client, err := h.openWebsocket(endpoint, material)
	if client != nil {
		client.close()
	}
	return err != nil && strings.Contains(err.Error(), "status=401")
}

func (c *websocketClient) roundTrip() error {
	message, err := json.Marshal(map[string]string{"kind": fakeContextKind, "context_id": fakeContextID})
	if err != nil {
		return err
	}
	if err := c.writeText(message); err != nil {
		return err
	}
	response, err := c.readText()
	if err != nil {
		return err
	}
	var decoded struct {
		Kind      string `json:"kind"`
		ContextID string `json:"context_id"`
	}
	if err := json.Unmarshal(response, &decoded); err != nil {
		return err
	}
	if decoded.Kind != fakeContextKind+"_echo" || decoded.ContextID != fakeContextID {
		return errors.New("websocket echo did not return the fake context")
	}
	return nil
}

func (c *websocketClient) writeText(payload []byte) error {
	if len(payload) >= 126 {
		return errors.New("fake websocket payload unexpectedly large")
	}
	mask := make([]byte, 4)
	if _, err := rand.Read(mask); err != nil {
		return err
	}
	masked := make([]byte, len(payload))
	for index := range payload {
		masked[index] = payload[index] ^ mask[index%len(mask)]
	}
	frame := append([]byte{0x81, byte(0x80 | len(payload))}, mask...)
	frame = append(frame, masked...)
	_ = c.connection.SetWriteDeadline(time.Now().Add(2 * time.Second))
	_, err := c.connection.Write(frame)
	return err
}

func (c *websocketClient) readText() ([]byte, error) {
	_ = c.connection.SetReadDeadline(time.Now().Add(2 * time.Second))
	first, err := c.reader.ReadByte()
	if err != nil {
		return nil, err
	}
	second, err := c.reader.ReadByte()
	if err != nil {
		return nil, err
	}
	if first&0x0F != 0x1 {
		return nil, errors.New("websocket response was not text")
	}
	length := int(second & 0x7F)
	if length == 126 {
		var raw uint16
		if err := binary.Read(c.reader, binary.BigEndian, &raw); err != nil {
			return nil, err
		}
		length = int(raw)
	}
	if second&0x80 != 0 {
		return nil, errors.New("server websocket frame was masked")
	}
	payload := make([]byte, length)
	if _, err := io.ReadFull(c.reader, payload); err != nil {
		return nil, err
	}
	return payload, nil
}

func sameMaterial(first, second string) bool {
	return first == second
}

func (h *host) logsExcludeMaterials(materials ...string) bool {
	paths := []string{
		filepath.Join(h.config.EvidenceDirectory, "host-events.jsonl"),
		filepath.Join(h.config.EvidenceDirectory, "core-events.jsonl"),
		filepath.Join(h.config.EvidenceDirectory, "core-output.log"),
	}
	for _, path := range paths {
		raw, err := os.ReadFile(path)
		if err != nil {
			return false
		}
		for _, material := range materials {
			if material != "" && bytes.Contains(raw, []byte(material)) {
				return false
			}
		}
	}
	return true
}

func (h *host) writeCandidateResult(result validationResult) error {
	path := filepath.Join(h.config.EvidenceDirectory, "candidate-results.json")
	handle, err := os.OpenFile(path, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	defer handle.Close()
	encoder := json.NewEncoder(handle)
	encoder.SetIndent("", "  ")
	return encoder.Encode(result)
}

func resolveRoot() string {
	if root := os.Getenv("SPIKE_ROOT"); root != "" {
		return root
	}
	if executable, err := os.Executable(); err == nil {
		candidate := filepath.Dir(filepath.Dir(executable))
		if _, err := os.Stat(filepath.Join(candidate, "agent_core", "agent_core_stub.py")); err == nil {
			return candidate
		}
	}
	workingDirectory, err := os.Getwd()
	if err != nil {
		log.Fatal(err)
	}
	return workingDirectory
}

func loadRunConfig(root string) (runConfig, error) {
	raw, err := os.ReadFile(filepath.Join(root, ".spike-run.json"))
	if err != nil {
		return runConfig{}, fmt.Errorf("read required .spike-run.json: %w", err)
	}
	raw = bytes.TrimPrefix(raw, []byte{0xef, 0xbb, 0xbf})
	var config runConfig
	if err := json.Unmarshal(raw, &config); err != nil {
		return runConfig{}, fmt.Errorf("parse required .spike-run.json: %w", err)
	}
	return config, nil
}

func diagnosticCode(err error) string {
	if err == nil {
		return "none"
	}
	if errors.Is(err, errHandshakeTimeout) || errors.Is(err, context.DeadlineExceeded) {
		return "bootstrap_timeout"
	}
	var netError net.Error
	if errors.As(err, &netError) {
		return "network_error"
	}
	return "validation_error"
}
