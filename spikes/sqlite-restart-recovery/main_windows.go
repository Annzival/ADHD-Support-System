//go:build windows

package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"embed"
	"encoding/hex"
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

const applicationName = "ADHD Support System V-03 restart recovery spike"

//go:embed all:frontend
var assets embed.FS

var errBootstrapTimeout = errors.New("bootstrap was not published before timeout")

type runConfig struct {
	PythonExecutable       string `json:"pythonExecutable"`
	WebView2BrowserPath    string `json:"webView2BrowserPath"`
	EvidenceDirectory      string `json:"evidenceDirectory"`
	DatabasePath           string `json:"databasePath"`
	InjectedClock          string `json:"injectedClock"`
	ReadyHoldMilliseconds  int    `json:"readyHoldMilliseconds"`
	HandshakeTimeoutMillis int    `json:"handshakeTimeoutMillis"`
}

type bootstrapRecord struct {
	Endpoint string `json:"endpoint"`
	PortMode string `json:"portMode"`
	Token    string `json:"token"`
}

type eventLogger struct {
	mu   sync.Mutex
	path string
}

// record accepts only host operational diagnostics. The temporary token is
// deliberately rejected here so ordinary host logs cannot include it.
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

// coreSummary is returned by the Python Core. The host copies this already
// sanitised payload; it does not calculate any synthetic recovery outcome.
type coreSummary struct {
	CandidateStatus          string            `json:"candidateStatus"`
	DatabaseIdentity         string            `json:"databaseIdentity"`
	DatabaseFileSHA256       string            `json:"databaseFileSha256"`
	Checks                   map[string]string `json:"checks"`
	InjectedClock            string            `json:"injectedClock"`
	SyntheticAuthority       map[string]any    `json:"syntheticAuthority"`
	SyntheticSchedules       []map[string]any  `json:"syntheticSchedules"`
	SyntheticObservableCount map[string]int    `json:"syntheticObservableCounts"`
	FirstRecoveryScan        map[string]int    `json:"firstRecoveryScan"`
	RepeatRecoveryScan       map[string]int    `json:"repeatRecoveryScan"`
}

type validationResult struct {
	SchemaVersion      int               `json:"schemaVersion"`
	Spike              string            `json:"spike"`
	GeneratedAt        string            `json:"generatedAt"`
	CandidateStatus    string            `json:"candidateStatus"`
	HandshakeMethod    string            `json:"handshakeMethod"`
	HostChecks         map[string]string `json:"hostChecks"`
	InitialCoreSummary coreSummary       `json:"initialCoreSummary"`
	CoreSummary        coreSummary       `json:"coreSummary"`
	EndpointFamilies   []string          `json:"endpointFamilies"`
	FirstEndpointHash  string            `json:"firstEndpointHash"`
	SecondEndpointHash string            `json:"secondEndpointHash"`
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
	if config.PythonExecutable == "" || config.WebView2BrowserPath == "" || config.EvidenceDirectory == "" || config.DatabasePath == "" || config.InjectedClock == "" {
		log.Fatal("run configuration is incomplete")
	}
	if config.HandshakeTimeoutMillis <= 0 {
		config.HandshakeTimeoutMillis = 900
	}
	if config.ReadyHoldMilliseconds <= 0 {
		config.ReadyHoldMilliseconds = 1500
	}

	h := &host{
		root:   root,
		config: config,
		logger: &eventLogger{path: filepath.Join(config.EvidenceDirectory, "host-events.jsonl")},
	}
	h.logger.record("host_starting", map[string]any{"mode": "synthetic_restart_validation"})
	h.app = application.New(application.Options{
		Name:        applicationName,
		Description: "V-03 synthetic restart validation only",
		Assets: application.AssetOptions{
			Handler: application.BundledAssetFileServer(assets),
		},
		Windows: application.WindowsOptions{
			WebviewBrowserPath: config.WebView2BrowserPath,
		},
	})
	h.app.Window.NewWithOptions(application.WebviewWindowOptions{
		Name:             "restart-recovery-validation",
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
	time.Sleep(500 * time.Millisecond)
	result := h.runValidation(context.Background())
	if err := h.writeCandidateResult(result); err != nil {
		log.Printf("write candidate result: %v", err)
	} else {
		h.logger.record("validation_finished", map[string]any{"candidateStatus": result.CandidateStatus})
	}
	time.Sleep(250 * time.Millisecond)
	h.app.Quit()
}

func (h *host) newResult() validationResult {
	return validationResult{
		SchemaVersion:   1,
		Spike:           "V-03",
		GeneratedAt:     time.Now().UTC().Format(time.RFC3339Nano),
		CandidateStatus: "FAIL",
		HandshakeMethod: "one_time_bootstrap_file",
		HostChecks: map[string]string{
			"first_core_bootstrap_ready":     "BLOCKED",
			"normal_core_exit":               "BLOCKED",
			"second_core_bootstrap_ready":    "BLOCKED",
			"core_restart_reacquired":        "BLOCKED",
			"ordinary_logs_exclude_material": "BLOCKED",
		},
		EndpointFamilies: []string{"127.0.0.1"},
	}
}

func (h *host) runValidation(parent context.Context) validationResult {
	result := h.newResult()
	first, err := h.startCore(parent)
	if err != nil {
		h.logger.record("first_core_start_failed", map[string]any{"diagnostic": diagnosticCode(err)})
		return result
	}
	h.setActiveCore(first)
	defer h.stopActiveCore()
	result.HostChecks["first_core_bootstrap_ready"] = "PASS"
	result.FirstEndpointHash = endpointFingerprint(first.details.Endpoint)
	if err := h.writeHostReady(); err != nil {
		h.logger.record("host_ready_write_failed", map[string]any{"diagnostic": diagnosticCode(err)})
		return result
	}
	time.Sleep(time.Duration(h.config.ReadyHoldMilliseconds) * time.Millisecond)
	firstSummary, err := h.readSummary(parent, first.details)
	if err != nil {
		h.logger.record("first_summary_failed", map[string]any{"diagnostic": diagnosticCode(err)})
		return result
	}
	if firstSummary.CandidateStatus != "PASS" {
		h.logger.record("first_summary_not_ready", map[string]any{"candidateStatus": firstSummary.CandidateStatus})
		return result
	}
	result.InitialCoreSummary = firstSummary
	if err := h.requestNormalExit(parent, first.details); err != nil {
		h.logger.record("normal_exit_request_failed", map[string]any{"diagnostic": diagnosticCode(err)})
		return result
	}
	exitContext, cancelExit := context.WithTimeout(parent, 3*time.Second)
	exitErr := first.wait(exitContext)
	cancelExit()
	if exitErr != nil {
		h.logger.record("normal_exit_wait_failed", map[string]any{"diagnostic": diagnosticCode(exitErr)})
		return result
	}
	h.clearActiveCore(first)
	result.HostChecks["normal_core_exit"] = "PASS"

	second, err := h.startCore(parent)
	if err != nil {
		h.logger.record("second_core_start_failed", map[string]any{"diagnostic": diagnosticCode(err)})
		return result
	}
	h.setActiveCore(second)
	result.HostChecks["second_core_bootstrap_ready"] = "PASS"
	result.SecondEndpointHash = endpointFingerprint(second.details.Endpoint)
	secondSummary, err := h.readSummary(parent, second.details)
	if err != nil {
		h.logger.record("second_summary_failed", map[string]any{"diagnostic": diagnosticCode(err)})
		return result
	}
	result.CoreSummary = secondSummary
	if first.details.Token != second.details.Token && endpointIsLoopback(first.details.Endpoint) && endpointIsLoopback(second.details.Endpoint) {
		result.HostChecks["core_restart_reacquired"] = "PASS"
	} else {
		result.HostChecks["core_restart_reacquired"] = "FAIL"
	}
	if h.logsExcludeMaterials(first.details.Token, second.details.Token) {
		result.HostChecks["ordinary_logs_exclude_material"] = "PASS"
	} else {
		result.HostChecks["ordinary_logs_exclude_material"] = "FAIL"
	}
	if secondSummary.CandidateStatus != "PASS" {
		return result
	}
	for _, status := range result.HostChecks {
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

func (h *host) startCore(ctx context.Context) (*coreProcess, error) {
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
		filepath.Join(h.root, "agent_core", "synthetic_core.py"),
		"--mode", "serve",
		"--database", h.config.DatabasePath,
		"--bootstrap-file", bootstrapPath,
		"--clock", h.config.InjectedClock,
		"--event-log", coreLogPath,
	}
	command := exec.Command(h.config.PythonExecutable, args...)
	command.Dir = h.root
	command.Stdout = output
	command.Stderr = output
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
			return nil, errBootstrapTimeout
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
	h.logger.record("bootstrap_consumed", map[string]any{"endpointFamily": "127.0.0.1", "deleted": true})
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
		status, _, err := h.httpRequest(ctx, record, http.MethodGet, "/spike/health")
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

func (h *host) readSummary(ctx context.Context, record bootstrapRecord) (coreSummary, error) {
	status, body, err := h.httpRequest(ctx, record, http.MethodGet, "/spike/summary")
	if err != nil {
		return coreSummary{}, err
	}
	if status != http.StatusOK {
		return coreSummary{}, fmt.Errorf("summary status=%d", status)
	}
	var summary coreSummary
	if err := json.Unmarshal(body, &summary); err != nil {
		return coreSummary{}, err
	}
	return summary, nil
}

func (h *host) requestNormalExit(ctx context.Context, record bootstrapRecord) error {
	status, body, err := h.httpRequest(ctx, record, http.MethodPost, "/spike/control/normal-exit")
	if err != nil {
		return err
	}
	if status != http.StatusAccepted || !bytes.Equal(body, []byte("{\"accepted\":true}")) {
		return fmt.Errorf("normal exit status=%d", status)
	}
	return nil
}

func (h *host) httpRequest(ctx context.Context, record bootstrapRecord, method, path string) (int, []byte, error) {
	request, err := http.NewRequestWithContext(ctx, method, record.Endpoint+path, nil)
	if err != nil {
		return 0, nil, err
	}
	request.Header.Set("Authorization", "Bearer "+record.Token)
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

func (h *host) writeHostReady() error {
	payload := map[string]any{
		"schemaVersion":   1,
		"hostStatus":      "ready",
		"endpointFamily":  "127.0.0.1",
		"handshakeMethod": "one_time_bootstrap_file",
	}
	encoded, err := json.MarshalIndent(payload, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(h.config.EvidenceDirectory, "host-ready.json"), append(encoded, '\n'), 0o600)
}

func (h *host) writeCandidateResult(result validationResult) error {
	encoded, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(h.config.EvidenceDirectory, "candidate-results.json"), append(encoded, '\n'), 0o600)
}

func resolveRoot() string {
	if root := os.Getenv("SPIKE_ROOT"); root != "" {
		return root
	}
	if executable, err := os.Executable(); err == nil {
		candidate := filepath.Dir(filepath.Dir(executable))
		if _, err := os.Stat(filepath.Join(candidate, "agent_core", "synthetic_core.py")); err == nil {
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

func endpointFingerprint(endpoint string) string {
	digest := sha256.Sum256([]byte(endpoint))
	return hex.EncodeToString(digest[:])
}

func diagnosticCode(err error) string {
	if err == nil {
		return "none"
	}
	if errors.Is(err, errBootstrapTimeout) || errors.Is(err, context.DeadlineExceeded) {
		return "bootstrap_timeout"
	}
	var netError net.Error
	if errors.As(err, &netError) {
		return "network_error"
	}
	return "validation_error"
}
