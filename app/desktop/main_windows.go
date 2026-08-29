//go:build windows

// ADHD 执行支持系统 v0.1 桌面宿主（薄宿主，ADR-0008）。
// 宿主只做三件事：守护智能体核心进程、桥接 OS 界面与生命周期能力、
// 把核心连接信息安全下发给前端；它不拥有任何执行状态或支持决策。
package main

import (
	"bytes"
	"context"
	"embed"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/Annzival/ADHD-Support-System/app/desktop/internal/coreproc"
	"github.com/Annzival/ADHD-Support-System/app/desktop/internal/supervisor"
	"github.com/wailsapp/wails/v3/pkg/application"
	"github.com/wailsapp/wails/v3/pkg/events"
	"github.com/wailsapp/wails/v3/pkg/icons"
	"github.com/wailsapp/wails/v3/pkg/services/notifications"
)

const (
	applicationName  = "执行支持"
	singleInstanceID = "org.annzival.adhd-support-system.v01"
	autostartID      = "ADHDSupportSystemV01"
)

//go:embed all:frontend
var embeddedAssets embed.FS

type runConfig struct {
	PythonExecutable string `json:"pythonExecutable"`
	CoreDir          string `json:"coreDir"`
	DatabasePath     string `json:"databasePath"`
	DataDir          string `json:"dataDir"`
}

type eventLogger struct {
	mu   sync.Mutex
	path string
}

func (l *eventLogger) record(kind string, fields map[string]any) {
	l.mu.Lock()
	defer l.mu.Unlock()
	if err := os.MkdirAll(filepath.Dir(l.path), 0o755); err != nil {
		return
	}
	entry := map[string]any{"time": time.Now().UTC().Format(time.RFC3339Nano), "kind": kind}
	for key, value := range fields {
		entry[key] = value
	}
	line, err := json.Marshal(entry)
	if err != nil {
		return
	}
	f, err := os.OpenFile(l.path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	_, _ = f.Write(append(line, '\n'))
}

type supervisedCore struct {
	pid  int
	wait func() error
	kill func() error
}

func (p *supervisedCore) PID() int    { return p.pid }
func (p *supervisedCore) Wait() error { return p.wait() }
func (p *supervisedCore) Kill() error { return p.kill() }

type host struct {
	app           *application.App
	mainWindow    *application.WebviewWindow
	overlay       *application.WebviewWindow
	notifications *notifications.NotificationService
	supervisor    *supervisor.Supervisor
	manager       *coreproc.Manager
	config        runConfig
	logger        *eventLogger
	httpClient    *http.Client
	assetsInner   http.Handler
}

func main() {
	root := resolveRoot()
	config := loadRunConfig(root)
	h := &host{
		config:     config,
		logger:     &eventLogger{path: filepath.Join(config.DataDir, "host-events.jsonl")},
		httpClient: &http.Client{Timeout: 4 * time.Second},
	}
	h.logger.record("host_starting", map[string]any{"root": root})

	inner, err := fs.Sub(embeddedAssets, "frontend")
	if err != nil {
		log.Fatal(err)
	}
	h.assetsInner = http.FileServer(http.FS(inner))

	h.manager = coreproc.NewManager(coreproc.Options{
		PythonExecutable: config.PythonExecutable,
		CoreDir:          config.CoreDir,
		DatabasePath:     config.DatabasePath,
		BootstrapTimeout: 20 * time.Second,
		OnEvent: func(kind string, fields map[string]any) {
			h.logger.record(kind, fields)
		},
	})
	if err := h.configureSupervisor(); err != nil {
		log.Fatal(err)
	}

	h.notifications = notifications.New()
	h.app = application.New(application.Options{
		Name:        applicationName,
		Description: "ADHD 执行支持系统：恢复优先的主动执行循环",
		Assets: application.AssetOptions{
			Handler: http.HandlerFunc(h.serveAssets),
		},
		Services: []application.Service{application.NewService(h.notifications)},
		Windows: application.WindowsOptions{
			DisableQuitOnLastWindowClosed: true,
		},
		SingleInstance: &application.SingleInstanceOptions{
			UniqueID: singleInstanceID,
			ExitCode: 0,
			OnSecondInstanceLaunch: func(data application.SecondInstanceData) {
				h.showMainWindow()
			},
		},
	})

	h.mainWindow = h.app.Window.NewWithOptions(application.WebviewWindowOptions{
		Name:             "main",
		Title:            applicationName,
		Width:            980,
		Height:           720,
		MinWidth:         720,
		MinHeight:        520,
		BackgroundColour: application.NewRGB(247, 248, 251),
		URL:              "/",
	})
	h.mainWindow.RegisterHook(events.Common.WindowClosing, func(event *application.WindowEvent) {
		event.Cancel()
		h.mainWindow.Hide()
		h.logger.record("main_window_hidden_on_close", nil)
	})

	h.overlay = h.app.Window.NewWithOptions(application.WebviewWindowOptions{
		Name:             "overlay",
		Title:            "执行上下文",
		Width:            380,
		Height:           220,
		MinWidth:         380,
		MinHeight:        220,
		MaxWidth:         380,
		MaxHeight:        220,
		AlwaysOnTop:      true,
		DisableResize:    true,
		Hidden:           true,
		BackgroundColour: application.NewRGB(255, 255, 255),
		URL:              "/overlay.html",
	})
	h.overlay.RegisterHook(events.Common.WindowClosing, func(event *application.WindowEvent) {
		event.Cancel()
		h.overlay.Hide()
	})

	h.configureTray()
	h.notifications.OnNotificationResponse(func(result notifications.NotificationResult) {
		if result.Error != nil {
			h.logger.record("notification_response_failed", map[string]any{"error": result.Error.Error()})
			return
		}
		// 通知只是辅助跳转：点击后回到主窗口首页（V-05 载体映射）。
		h.showMainWindow()
	})

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
	config := supervisor.Config{
		Launch: func(ctx context.Context) (supervisor.Process, error) {
			pid, wait, kill, err := h.manager.Launch(ctx)
			if err != nil {
				return nil, err
			}
			return &supervisedCore{pid: pid, wait: wait, kill: kill}, nil
		},
		CheckHealth: h.checkCoreHealth,
		RequestGracefulStop: func(ctx context.Context) error {
			record := h.manager.Connection()
			if record == nil {
				return nil
			}
			return h.postCore(record, "/api/shutdown", map[string]string{"reason": "host_exit"})
		},
		MaxRestarts:         5,
		BaseBackoff:         time.Second,
		HealthTimeout:       25 * time.Second,
		HealthRetryInterval: 300 * time.Millisecond,
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
	tray.SetTooltip("执行支持")
	menu := h.app.NewMenu()
	menu.Add("显示主窗口").OnClick(func(*application.Context) { h.showMainWindow() })
	menu.AddSeparator()
	menu.Add("启用开机自启").OnClick(func(*application.Context) {
		if err := h.app.Autostart.EnableWithOptions(application.AutostartOptions{Identifier: autostartID}); err != nil {
			h.logger.record("autostart_enable_failed", map[string]any{"error": err.Error()})
			return
		}
		h.logger.record("autostart_enabled", nil)
	})
	menu.Add("禁用开机自启").OnClick(func(*application.Context) {
		if err := h.app.Autostart.Disable(); err != nil {
			h.logger.record("autostart_disable_failed", map[string]any{"error": err.Error()})
			return
		}
		h.logger.record("autostart_disabled", nil)
	})
	menu.AddSeparator()
	menu.Add("退出").OnClick(func(*application.Context) { h.app.Quit() })
	tray.SetMenu(menu)
}

func (h *host) showMainWindow() {
	h.mainWindow.Show().Focus()
}

// ---------------------------------------------------------------------------
// 资产中间件：前端与宿主之间仅有的两条内部通道。

type runtimeConfig struct {
	Endpoint    string `json:"endpoint"`
	Token       string `json:"token"`
	CoreRunning bool   `json:"coreRunning"`
}

func (h *host) serveAssets(w http.ResponseWriter, r *http.Request) {
	switch r.URL.Path {
	case "/runtime-config.json":
		record := h.manager.Connection()
		payload := runtimeConfig{CoreRunning: record != nil}
		if record != nil {
			payload.Endpoint = record.Endpoint
			payload.Token = record.Token
		}
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		w.Header().Set("Cache-Control", "no-store")
		_ = json.NewEncoder(w).Encode(payload)
		return
	case "/host-command":
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var command struct {
			Kind  string `json:"kind"`
			Title string `json:"title"`
			Body  string `json:"body"`
		}
		if err := json.NewDecoder(io.LimitReader(r.Body, 1<<16)).Decode(&command); err != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		h.handleHostCommand(command.Kind, command.Title, command.Body)
		w.WriteHeader(http.StatusNoContent)
		return
	default:
		h.assetsInner.ServeHTTP(w, r)
	}
}

func (h *host) handleHostCommand(kind, title, body string) {
	h.logger.record("host_command", map[string]any{"kind": kind})
	switch kind {
	case "show_main":
		h.showMainWindow()
	case "show_overlay":
		h.overlay.SetAlwaysOnTop(true)
		h.overlay.Show()
	case "hide_overlay":
		h.overlay.Hide()
	case "notify":
		category := notifications.NotificationCategory{
			ID: "open-main",
			Actions: []notifications.NotificationAction{
				{ID: "OPEN_MAIN", Title: "打开"},
			},
		}
		if err := h.notifications.RegisterNotificationCategory(category); err != nil {
			h.logger.record("notification_category_failed", map[string]any{"error": err.Error()})
			return
		}
		if err := h.notifications.SendNotificationWithActions(notifications.NotificationOptions{
			ID:         "intervention-" + time.Now().UTC().Format("20060102T150405.000000000"),
			Title:      title,
			Body:       body,
			CategoryID: category.ID,
		}); err != nil {
			h.logger.record("notification_send_failed", map[string]any{"error": err.Error()})
		}
	default:
		h.logger.record("host_command_unknown", map[string]any{"kind": kind})
	}
}

// ---------------------------------------------------------------------------

func (h *host) checkCoreHealth(ctx context.Context) error {
	// 健康检查期间 bootstrap 可能刚完成；直接读当前连接。
	record := h.manager.Connection()
	if record == nil {
		return fmt.Errorf("core connection not ready")
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, record.Endpoint+"/api/health", nil)
	if err != nil {
		return err
	}
	response, err := h.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	_, _ = io.Copy(io.Discard, response.Body)
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("health endpoint returned %s", response.Status)
	}
	return nil
}

func (h *host) postCore(record *coreproc.Record, path string, payload any) error {
	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	request, err := http.NewRequest(http.MethodPost, record.Endpoint+path, bytes.NewReader(body))
	if err != nil {
		return err
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Authorization", "Bearer "+record.Token)
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

func resolveRoot() string {
	if fromEnv := os.Getenv("ADHD_APP_ROOT"); fromEnv != "" {
		return filepath.Clean(fromEnv)
	}
	if executable, err := os.Executable(); err == nil {
		// <root>/desktop/bin/xxx.exe → 逐级上溯到 app/ 目录。
		candidate := filepath.Dir(filepath.Dir(filepath.Dir(executable)))
		if _, err := os.Stat(filepath.Join(candidate, "agent_core", "agent_core")); err == nil {
			return candidate
		}
	}
	return cwdRoot()
}

func cwdRoot() string {
	working, err := os.Getwd()
	if err != nil {
		log.Fatal(err)
	}
	return working
}

func loadRunConfig(root string) runConfig {
	config := runConfig{}
	path := filepath.Join(root, ".run", "run-config.json")
	if contents, err := os.ReadFile(path); err == nil {
		contents = bytes.TrimPrefix(contents, []byte{0xef, 0xbb, 0xbf})
		_ = json.Unmarshal(contents, &config)
	}
	if config.DataDir == "" {
		config.DataDir = filepath.Join(root, ".run")
	}
	if config.CoreDir == "" {
		config.CoreDir = filepath.Join(root, "agent_core")
	}
	if config.DatabasePath == "" {
		config.DatabasePath = filepath.Join(config.DataDir, "agent_core.sqlite3")
	}
	if config.PythonExecutable == "" {
		if venvPython := filepath.Join(config.CoreDir, ".venv", "Scripts", "python.exe"); fileExists(venvPython) {
			config.PythonExecutable = venvPython
		} else {
			config.PythonExecutable = "python"
		}
	}
	_ = os.MkdirAll(config.DataDir, 0o755)
	return config
}

func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}
