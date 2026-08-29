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

// coreExited 表示核心在握手完成前就退出了。它携带退出码与核心日志尾部，
// 使"另一个核心正在运行"这类情况立刻可读，而不是退化成一次无信息的超时。
type coreExited struct {
	Code    int
	LogTail string
}

func (e *coreExited) Error() string {
	message := fmt.Sprintf("agent core exited during handshake with code %d", e.Code)
	if e.LogTail != "" {
		message += "\n核心日志尾部:\n" + e.LogTail
	}
	return message
}

func tailLines(path string, limit int) string {
	contents, err := os.ReadFile(path)
	if err != nil || len(contents) == 0 {
		return ""
	}
	lines := strings.Split(strings.ReplaceAll(string(contents), "\r\n", "\n"), "\n")
	if len(lines) > limit {
		lines = lines[len(lines)-limit:]
	}
	trimmed := make([]string, 0, len(lines))
	for _, line := range lines {
		if strings.TrimSpace(line) != "" {
			trimmed = append(trimmed, line)
		}
	}
	return strings.Join(trimmed, "\n")
}

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
	coreLogPath := filepath.Join(filepath.Dir(m.opts.DatabasePath), "agent-core.log")
	logFile, err := os.OpenFile(coreLogPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
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

	// 把核心（含 venv 启动器派生出的解释器子进程）纳入作业，保证退出时整棵树一起终止。
	releaseJob, jobErr := attachToKillOnCloseJob(cmd.Process.Pid)
	if jobErr != nil {
		// 作业对象不可用只降低清理强度，不阻止启动；该事件会被记录下来供排查。
		m.opts.OnEvent("job_object_unavailable", map[string]any{"sequence": seq, "error": jobErr.Error()})
	} else {
		m.opts.OnEvent("job_object_attached", map[string]any{"sequence": seq, "pid": cmd.Process.Pid})
	}

	// cmd.Wait 只能调用一次；这里统一收敛，既被握手等待复用，也供后续生命周期使用。
	var (
		waitOnce    sync.Once
		procExitErr error
		exited      = make(chan struct{})
	)
	waitFn := func() error {
		waitOnce.Do(func() {
			procExitErr = cmd.Wait()
			// 核心已退出，主动释放作业句柄；句柄泄漏会让作业一直存在。
			if releaseJob != nil {
				releaseJob()
			}
		})
		return procExitErr
	}
	go func() {
		waitOnce.Do(func() {
			procExitErr = cmd.Wait()
			if releaseJob != nil {
				releaseJob()
			}
		})
		close(exited)
	}()

	// 核心提前退出时带上退出码与日志尾部，避免退化成一次无信息的超时。
	describeExit := func(fallback error) error {
		if procExitErr == nil {
			return fallback
		}
		code := -1
		var exitErr *exec.ExitError
		if errors.As(procExitErr, &exitErr) {
			code = exitErr.ExitCode()
		}
		return &coreExited{Code: code, LogTail: tailLines(coreLogPath, 12)}
	}

	record, handshakeErr := m.waitForBootstrap(ctx, bootstrapPath, exited, describeExit)
	// 无论成功与否都立即消费 bootstrap 文件与其临时目录。
	_ = os.Remove(bootstrapPath)
	_ = os.Remove(handoffDir)
	m.mu.Lock()
	m.handoff = ""
	m.mu.Unlock()

	if handshakeErr != nil {
		logFile.Close()
		// 关闭作业句柄会终止整棵进程树，避免 venv 启动器的子进程残留。
		if releaseJob != nil {
			releaseJob()
		}
		_ = cmd.Process.Kill()
		_ = waitFn()
		return 0, nil, nil, handshakeErr
	}
	m.mu.Lock()
	m.record = record
	m.mu.Unlock()
	m.opts.OnEvent("bootstrap_consumed", map[string]any{"sequence": seq, "portMode": record.PortMode})
	logFile.Close()

	killFn := func() error {
		// 先关闭作业句柄以终止整棵进程树，再兜底杀掉启动器进程。
		if releaseJob != nil {
			releaseJob()
		}
		if cmd.Process == nil {
			return nil
		}
		return cmd.Process.Kill()
	}
	return cmd.Process.Pid, waitFn, killFn, nil
}

// waitForBootstrap 轮询 bootstrap 文件；若核心进程提前退出则立即返回描述性错误，
// 不再空等到超时。describeExit 负责把退出码与核心日志尾部拼进错误信息。
func (m *Manager) waitForBootstrap(
	ctx context.Context,
	path string,
	exited <-chan struct{},
	describeExit func(error) error,
) (*Record, error) {
	deadline := time.Now().Add(m.opts.BootstrapTimeout)
	poll := time.NewTicker(50 * time.Millisecond)
	defer poll.Stop()

	// check 执行一次探测；done 为真时其返回值即为最终结果。
	check := func() (*Record, error, bool) {
		select {
		case <-exited:
			return nil, describeExit(errors.New("agent core exited during handshake")), true
		default:
		}
		if ctx.Err() != nil {
			return nil, ctx.Err(), true
		}
		contents, err := os.ReadFile(path)
		if err == nil {
			if record, parseErr := parseRecord(contents); parseErr == nil {
				return record, nil, true
			} else {
				m.opts.OnEvent("bootstrap_parse_failed", map[string]any{"error": parseErr.Error()})
			}
		}
		return nil, nil, false
	}

	if record, err, done := check(); done {
		return record, err
	}
	for range poll.C {
		if record, err, done := check(); done {
			return record, err
		}
		if time.Now().After(deadline) {
			return nil, errHandshakeTimeout
		}
	}
	return nil, errHandshakeTimeout
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
