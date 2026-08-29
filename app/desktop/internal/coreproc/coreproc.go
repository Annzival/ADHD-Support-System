// Package coreproc 启动 Python 智体核心并完成一次性 bootstrap 文件握手。
// 端点与临时令牌只保存在宿主内存中；本包不解析任何领域数据。
package coreproc

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

var errHandshakeTimeout = errors.New("bootstrap was not published before timeout")

type Record struct {
	Endpoint string `json:"endpoint"`
	PortMode string `json:"portMode"`
	Token    string `json:"token"`
}

type Options struct {
	PythonExecutable string
	CoreDir          string // agent_core 包所在目录（python -m agent_core 的工作目录）
	DatabasePath     string
	BootstrapTimeout time.Duration
	OnEvent          func(kind string, fields map[string]any)
}

// Manager 保存最近一次握手得到的连接信息，供资产中间件安全下发给前端。
type Manager struct {
	opts Options

	mu       sync.RWMutex
	record   *Record
	handoff  string // 当前尚未删除的 handoff 目录（崩溃恢复清理用）
	sequence int
}

func NewManager(opts Options) *Manager {
	if opts.BootstrapTimeout <= 0 {
		opts.BootstrapTimeout = 15 * time.Second
	}
	if opts.OnEvent == nil {
		opts.OnEvent = func(string, map[string]any) {}
	}
	return &Manager{opts: opts}
}

// Connection 返回当前连接信息（可能为 nil）；仅由宿主进程内读取。
func (m *Manager) Connection() *Record {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.record
}

// Launch 实现 supervisor.Launcher：启动核心、等待 bootstrap、读取后立即删除。
func (m *Manager) Launch(ctx context.Context) (pid int, wait func() error, kill func() error, err error) {
	m.mu.Lock()
	m.sequence++
	seq := m.sequence
	m.mu.Unlock()

	handoffRoot := filepath.Join(os.TempDir(), "adhd-support-system-handoff")
	if err := os.MkdirAll(handoffRoot, 0o700); err != nil {
		return 0, nil, nil, err
	}
	handoffDir, err := os.MkdirTemp(handoffRoot, "run-")
	if err != nil {
		return 0, nil, nil, err
	}
	bootstrapPath := filepath.Join(handoffDir, "handoff.json")

	m.mu.Lock()
	m.handoff = handoffDir
	m.mu.Unlock()

	if err := os.MkdirAll(filepath.Dir(m.opts.DatabasePath), 0o755); err != nil {
		return 0, nil, nil, err
	}
	logFile, err := os.OpenFile(filepath.Join(filepath.Dir(m.opts.DatabasePath), "agent-core.log"),
		os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return 0, nil, nil, err
	}

	cmd := exec.CommandContext(ctx, m.opts.PythonExecutable, "-m", "agent_core",
		"--bootstrap-file", bootstrapPath,
		"--database", m.opts.DatabasePath,
	)
	cmd.Dir = m.opts.CoreDir
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	// 隔离用户 shell 中可能存在的代理变量：核心只允许回环通信。
	cmd.Env = append(os.Environ(), "NO_PROXY=127.0.0.1,localhost", "no_proxy=127.0.0.1,localhost")
	if err := cmd.Start(); err != nil {
		logFile.Close()
		_ = os.RemoveAll(handoffDir)
		return 0, nil, nil, fmt.Errorf("start agent core: %w", err)
	}
	m.opts.OnEvent("core_process_started", map[string]any{"pid": cmd.Process.Pid, "sequence": seq})

	record, waitErr := m.waitForBootstrap(ctx, bootstrapPath)
	// 无论成功与否都立即消费 bootstrap 文件与其临时目录。
	_ = os.Remove(bootstrapPath)
	_ = os.Remove(handoffDir)
	m.mu.Lock()
	m.handoff = ""
	m.mu.Unlock()

	if waitErr != nil {
		logFile.Close()
		_ = cmd.Process.Kill()
		_, _ = cmd.Process.Wait()
		return 0, nil, nil, waitErr
	}
	m.mu.Lock()
	m.record = record
	m.mu.Unlock()
	m.opts.OnEvent("bootstrap_consumed", map[string]any{"sequence": seq, "portMode": record.PortMode})
	logFile.Close()

	waitFn := func() error { return cmd.Wait() }
	killFn := func() error {
		if cmd.Process == nil {
			return nil
		}
		return cmd.Process.Kill()
	}
	return cmd.Process.Pid, waitFn, killFn, nil
}

func (m *Manager) waitForBootstrap(ctx context.Context, path string) (*Record, error) {
	deadline := time.Now().Add(m.opts.BootstrapTimeout)
	for {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		contents, err := os.ReadFile(path)
		if err == nil {
			record, parseErr := parseRecord(contents)
			if parseErr == nil {
				return record, nil
			}
			m.opts.OnEvent("bootstrap_parse_failed", map[string]any{"error": parseErr.Error()})
		}
		if time.Now().After(deadline) {
			return nil, errHandshakeTimeout
		}
		time.Sleep(50 * time.Millisecond)
	}
}

func parseRecord(contents []byte) (*Record, error) {
	// 容忍可能的 UTF-8 BOM。
	contents = []byte(strings.TrimPrefix(string(contents), "\ufeff"))
	var record Record
	if err := json.Unmarshal(contents, &record); err != nil {
		return nil, err
	}
	if !endpointIsLoopback(record.Endpoint) || record.PortMode != "dynamic" || record.Token == "" {
		return nil, errors.New("bootstrap did not contain a dynamic loopback endpoint")
	}
	return &record, nil
}

func endpointIsLoopback(endpoint string) bool {
	return strings.HasPrefix(endpoint, "http://127.0.0.1:") || strings.HasPrefix(endpoint, "http://localhost:")
}
