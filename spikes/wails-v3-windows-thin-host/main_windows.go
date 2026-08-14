//go:build windows

package main

import (
	"bytes"
	"context"
	"embed"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"time"

	"github.com/Annzival/ADHD-Support-System/spikes/wails-v3-windows-thin-host/internal/supervisor"
	"github.com/wailsapp/wails/v3/pkg/application"
	"github.com/wailsapp/wails/v3/pkg/events"
	"github.com/wailsapp/wails/v3/pkg/icons"
	"github.com/wailsapp/wails/v3/pkg/services/notifications"
)

const (
	applicationName  = "ADHD Support System V-01 Spike"
	singleInstanceID = "org.annzival.adhd-support-system.v01-spike"
	autostartID      = "ADHDSupportSystemV01Spike"
	defaultCorePort  = 18765
	demoContextID    = "v01-demo-context-001"
)

//go:embed all:frontend
var assets embed.FS

type runConfig struct {
	PythonExecutable    string `json:"pythonExecutable"`
	WebView2BrowserPath string `json:"webView2BrowserPath"`
	EvidenceDirectory   string `json:"evidenceDirectory"`
	CorePort            int    `json:"corePort"`
}

// eventLogger writes only mechanical validation events. It does not contain
// user plan, execution, scheduling, or other product-domain data.
type eventLogger struct {
	mu   sync.Mutex
	path string
}

func (l *eventLogger) record(kind string, fields map[string]any) {
	l.mu.Lock()
	defer l.mu.Unlock()
	if err := os.MkdirAll(filepath.Dir(l.path), 0o755); err != nil {
		log.Printf("create evidence directory: %v", err)
		return
	}
	entry := map[string]any{"time": time.Now().UTC().Format(time.RFC3339Nano), "kind": kind}
	for key, value := range fields {
		entry[key] = value
	}
	line, err := json.Marshal(entry)
	if err != nil {
		log.Printf("marshal event %q: %v", kind, err)
		return
	}
	f, err := os.OpenFile(l.path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		log.Printf("open event log: %v", err)
		return
	}
	defer f.Close()
	if _, err := f.Write(append(line, '\n')); err != nil {
		log.Printf("write event log: %v", err)
	}
}

type execProcess struct {
	cmd       *exec.Cmd
	closeLogs func()
	once      sync.Once
}

func (p *execProcess) PID() int { return p.cmd.Process.Pid }

func (p *execProcess) Wait() error {
	err := p.cmd.Wait()
	p.once.Do(p.closeLogs)
	return err
}

func (p *execProcess) Kill() error {
	if p.cmd.Process == nil {
		return nil
	}
	return p.cmd.Process.Kill()
}

type host struct {
	app           *application.App
	mainWindow    *application.WebviewWindow
	overlay       *application.WebviewWindow
	notifications *notifications.NotificationService
	supervisor    *supervisor.Supervisor
	root          string
	config        runConfig
	logger        *eventLogger
	httpClient    *http.Client
}

func main() {
	root := resolveRoot()
	config, err := loadRunConfig(root)
	if err != nil {
		log.Fatal(err)
	}
	if config.CorePort == 0 {
		config.CorePort = defaultCorePort
	}
	if config.PythonExecutable == "" {
		config.PythonExecutable = "python"
	}
	if config.EvidenceDirectory == "" {
		config.EvidenceDirectory = filepath.Join(root, ".evidence", "unconfigured")
	}

	h := &host{
		root:       root,
		config:     config,
		logger:     &eventLogger{path: filepath.Join(config.EvidenceDirectory, "host-events.jsonl")},
		httpClient: &http.Client{Timeout: 3 * time.Second},
	}
	h.logger.record("host_starting", map[string]any{"root": root, "corePort": config.CorePort})

	if err := h.configureSupervisor(); err != nil {
		log.Fatal(err)
	}

	h.notifications = notifications.New()
	h.app = application.New(application.Options{
		Name:        applicationName,
		Description: "V-01 Wails v3 Windows thin-host validation only",
		Assets: application.AssetOptions{
			Handler: application.BundledAssetFileServer(assets),
		},
		Services: []application.Service{application.NewService(h.notifications)},
		Windows: application.WindowsOptions{
			DisableQuitOnLastWindowClosed: true,
			WebviewBrowserPath:            config.WebView2BrowserPath,
		},
		SingleInstance: &application.SingleInstanceOptions{
			UniqueID: singleInstanceID,
			ExitCode: 0,
			OnSecondInstanceLaunch: func(data application.SecondInstanceData) {
				h.logger.record("second_instance_activated", map[string]any{"args": data.Args})
				h.showMainWindow()
			},
		},
	})

	h.mainWindow = h.app.Window.NewWithOptions(application.WebviewWindowOptions{
		Name:             "main",
		Title:            applicationName,
		Width:            720,
		Height:           520,
		MinWidth:         560,
		MinHeight:        400,
		BackgroundColour: application.NewRGB(250, 250, 250),
		URL:              "/",
	})
	// Cancelling the native close event and hiding the window makes this an
	// explicit tray-resident test, rather than treating the close button as a
	// request to exit the mechanical process supervisor.
	h.mainWindow.RegisterHook(events.Common.WindowClosing, func(event *application.WindowEvent) {
		event.Cancel()
		h.mainWindow.Hide()
		h.logger.record("main_window_hidden_on_close", nil)
	})

	h.overlay = h.app.Window.NewWithOptions(application.WebviewWindowOptions{
		Name:             "overlay",
		Title:            "V-01 演示小窗（非权威状态）",
		Width:            360,
		Height:           200,
		MinWidth:         360,
		MinHeight:        200,
		MaxWidth:         360,
		MaxHeight:        200,
		AlwaysOnTop:      true,
		DisableResize:    true,
		Hidden:           true,
		BackgroundColour: application.NewRGB(255, 255, 255),
		URL:              "/overlay.html",
	})

	h.configureTray()
	h.notifications.OnNotificationResponse(h.routeNotificationResponse)
	h.app.OnShutdown(func() {
		h.logger.record("host_shutdown_started", nil)
		ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
		defer cancel()
		if err := h.supervisor.Stop(ctx); err != nil {
			h.logger.record("host_shutdown_supervisor_error", map[string]any{"error": err.Error()})
		}
		h.logger.record("host_shutdown_finished", nil)
	})

	if err := h.supervisor.Start(context.Background()); err != nil {
		h.logger.record("host_initial_supervisor_start_failed", map[string]any{"error": err.Error()})
		log.Fatal(err)
	}

	if err := h.app.Run(); err != nil {
		log.Fatal(err)
	}
}

func (h *host) configureSupervisor() error {
	agentLogPath := filepath.Join(h.config.EvidenceDirectory, "agent-core.log")
	config := supervisor.Config{
		Launch: func(context.Context) (supervisor.Process, error) {
			if err := os.MkdirAll(filepath.Dir(agentLogPath), 0o755); err != nil {
				return nil, err
			}
			logFile, err := os.OpenFile(agentLogPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
			if err != nil {
				return nil, err
			}
			coreLogPath := filepath.Join(h.config.EvidenceDirectory, "agent-core-events.jsonl")
			cmd := exec.Command(
				h.config.PythonExecutable,
				filepath.Join(h.root, "agent_core", "agent_core_stub.py"),
				"--port", fmt.Sprint(h.config.CorePort),
			)
			cmd.Dir = h.root
			cmd.Stdout = logFile
			cmd.Stderr = logFile
			cmd.Env = append(os.Environ(), "SPIKE_CORE_EVENT_LOG="+coreLogPath)
			if err := cmd.Start(); err != nil {
				logFile.Close()
				return nil, err
			}
			return &execProcess{cmd: cmd, closeLogs: func() { _ = logFile.Close() }}, nil
		},
		CheckHealth: h.checkCoreHealth,
		RequestGracefulStop: func(context.Context) error {
			return h.postCore("/control/exit", map[string]string{"reason": "host_explicit_exit"})
		},
		MaxRestarts:         3,
		BaseBackoff:         time.Second,
		HealthTimeout:       8 * time.Second,
		HealthRetryInterval: 250 * time.Millisecond,
		OnEvent: func(event supervisor.Event) {
			h.logger.record("supervisor_"+event.Kind, map[string]any{
				"pid": event.PID, "restart": event.Restart, "backoff": event.Backoff, "message": event.Message,
			})
		},
	}
	value, err := supervisor.New(config)
	if err != nil {
		return err
	}
	h.supervisor = value
	return nil
}

func (h *host) configureTray() {
	tray := h.app.SystemTray.New()
	tray.SetIcon(icons.SystrayLight)
	tray.SetTooltip("V-01 Wails v3 Windows 薄桌面宿主验证")
	menu := h.app.NewMenu()
	menu.Add("显示主窗口").OnClick(func(*application.Context) { h.showMainWindow() })
	menu.Add("显示置顶演示小窗").OnClick(func(*application.Context) { h.showOverlay() })
	menu.Add("隐藏置顶演示小窗").OnClick(func(*application.Context) { h.hideOverlay() })
	menu.AddSeparator()
	menu.Add("发送带操作的演示通知").OnClick(func(*application.Context) { h.sendDemoNotification() })
	menu.Add("触发一次智能体核心测试替身异常").OnClick(func(*application.Context) { h.triggerCrash("single") })
	menu.AddSeparator()
	menu.Add("启用开机启动（下次登录）").OnClick(func(*application.Context) { h.enableAutostart() })
	menu.Add("禁用开机启动").OnClick(func(*application.Context) { h.disableAutostart() })
	menu.Add("记录当前机械进程状态").OnClick(func(*application.Context) {
		status := h.supervisor.Status()
		h.logger.record("supervisor_status_requested", map[string]any{"status": status})
	})
	menu.AddSeparator()
	menu.Add("退出验证宿主").OnClick(func(*application.Context) { h.app.Quit() })
	tray.SetMenu(menu)
}

func (h *host) showMainWindow() {
	h.mainWindow.Show().Focus()
	h.logger.record("main_window_shown", nil)
}

func (h *host) showOverlay() {
	h.overlay.SetAlwaysOnTop(true)
	h.overlay.Show().Focus()
	h.logger.record("overlay_shown", map[string]any{"alwaysOnTop": true})
}

func (h *host) hideOverlay() {
	h.overlay.Hide()
	h.logger.record("overlay_hidden", nil)
}

func (h *host) enableAutostart() {
	err := h.app.Autostart.EnableWithOptions(application.AutostartOptions{
		Identifier: autostartID,
		Arguments:  []string{"--spike-autostart"},
	})
	if err != nil {
		h.logger.record("autostart_enable_failed", map[string]any{"error": err.Error()})
		return
	}
	status, statusErr := h.app.Autostart.Status()
	h.logger.record("autostart_enabled", map[string]any{"status": status, "statusError": errorString(statusErr)})
}

func (h *host) disableAutostart() {
	err := h.app.Autostart.Disable()
	if err != nil {
		h.logger.record("autostart_disable_failed", map[string]any{"error": err.Error()})
		return
	}
	status, statusErr := h.app.Autostart.Status()
	h.logger.record("autostart_disabled", map[string]any{"status": status, "statusError": errorString(statusErr)})
}

func (h *host) sendDemoNotification() {
	category := notifications.NotificationCategory{
		ID: "v01-demo-actions",
		Actions: []notifications.NotificationAction{
			{ID: "OPEN_CONTEXT", Title: "打开演示上下文"},
		},
	}
	if err := h.notifications.RegisterNotificationCategory(category); err != nil {
		h.logger.record("notification_category_failed", map[string]any{"error": err.Error()})
		return
	}
	err := h.notifications.SendNotificationWithActions(notifications.NotificationOptions{
		ID:         "v01-demo-notification-" + time.Now().UTC().Format("20060102T150405.000000000Z"),
		Title:      "V-01 演示通知",
		Body:       "选择“打开演示上下文”，验证通知回调只转交上下文标识。",
		CategoryID: category.ID,
		Data: map[string]interface{}{
			"demoContextID": demoContextID,
		},
	})
	if err != nil {
		h.logger.record("notification_send_failed", map[string]any{"error": err.Error()})
		return
	}
	h.logger.record("notification_sent", map[string]any{"contextID": demoContextID})
}

func (h *host) routeNotificationResponse(result notifications.NotificationResult) {
	if result.Error != nil {
		h.logger.record("notification_response_failed", map[string]any{"error": result.Error.Error()})
		return
	}
	contextID, _ := result.Response.UserInfo["demoContextID"].(string)
	h.logger.record("notification_response_received", map[string]any{
		"action": result.Response.ActionIdentifier, "contextID": contextID,
	})
	if contextID == "" {
		h.logger.record("notification_context_missing", nil)
		return
	}
	if err := h.postCore("/demo/notification-context", map[string]string{
		"contextID": contextID,
		"action":    result.Response.ActionIdentifier,
	}); err != nil {
		h.logger.record("notification_context_route_failed", map[string]any{"error": err.Error(), "contextID": contextID})
		return
	}
	h.showMainWindow()
	h.logger.record("notification_context_routed", map[string]any{"contextID": contextID})
}

func (h *host) triggerCrash(scenario string) {
	if err := h.postCore("/control/crash", map[string]string{"scenario": scenario}); err != nil {
		h.logger.record("crash_trigger_failed", map[string]any{"error": err.Error(), "scenario": scenario})
		return
	}
	h.logger.record("crash_triggered", map[string]any{"scenario": scenario})
}

func (h *host) checkCoreHealth(ctx context.Context) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, h.coreURL("/health"), nil)
	if err != nil {
		return err
	}
	response, err := h.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("health endpoint returned %s", response.Status)
	}
	return nil
}

func (h *host) postCore(path string, payload any) error {
	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	request, err := http.NewRequest(http.MethodPost, h.coreURL(path), bytes.NewReader(body))
	if err != nil {
		return err
	}
	request.Header.Set("Content-Type", "application/json")
	response, err := h.httpClient.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	_, _ = io.Copy(io.Discard, response.Body)
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return fmt.Errorf("%s returned %s", path, response.Status)
	}
	return nil
}

func (h *host) coreURL(path string) string {
	return fmt.Sprintf("http://127.0.0.1:%d%s", h.config.CorePort, path)
}

func resolveRoot() string {
	if fromEnv := os.Getenv("SPIKE_ROOT"); fromEnv != "" {
		return fromEnv
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
	config := runConfig{
		PythonExecutable:    os.Getenv("SPIKE_PYTHON_EXE"),
		WebView2BrowserPath: os.Getenv("SPIKE_WEBVIEW2_BROWSER_PATH"),
		EvidenceDirectory:   os.Getenv("SPIKE_EVIDENCE_DIR"),
		CorePort:            defaultCorePort,
	}
	contents, err := os.ReadFile(filepath.Join(root, ".spike-run.json"))
	if err != nil {
		return config, fmt.Errorf("read required .spike-run.json: %w", err)
	}
	// Windows PowerShell 5.1 writes a UTF-8 BOM for -Encoding UTF8. Accept
	// it here as a defensive boundary, even though Start-Spike.ps1 writes the
	// file without a BOM, so the running host never silently loses its pinned
	// runtime paths or evidence directory.
	contents = bytes.TrimPrefix(contents, []byte{0xef, 0xbb, 0xbf})
	if err := json.Unmarshal(contents, &config); err != nil {
		return config, fmt.Errorf("parse required .spike-run.json: %w", err)
	}
	return config, nil
}

func errorString(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}
