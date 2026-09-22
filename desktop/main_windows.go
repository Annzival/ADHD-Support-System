//go:build windows

package main

import (
	"context"
	"embed"
	"encoding/json"
	"flag"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/coder/websocket"
	"github.com/wailsapp/wails/v3/pkg/application"
	"github.com/wailsapp/wails/v3/pkg/events"
	"github.com/wailsapp/wails/v3/pkg/icons"
	"github.com/wailsapp/wails/v3/pkg/services/notifications"
)

//go:embed all:frontend
var assets embed.FS

type desktopHost struct {
	app                 *application.App
	mainWindow, overlay *application.WebviewWindow
	notifications       *notifications.NotificationService
	bridge              *bridge
	mu                  sync.Mutex
	notice              map[string]any
	evidence            string
}

func main() {
	python := flag.String("python", "", "Python 3.12.3 x64 executable")
	root := flag.String("root", "", "repository root")
	data := flag.String("data-dir", "", "isolated confirmed development data")
	runtime := flag.String("webview2", "", "fixed runtime path")
	flag.Parse()
	if *python == "" || *root == "" || *data == "" || *runtime == "" {
		log.Fatal("Explicit Python, repository, development data and fixed WebView2 paths required")
	}
	h := &desktopHost{bridge: newBridge(), evidence: filepath.Join(*data, "desktop-evidence.jsonl")}
	h.notifications = notifications.New()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	h.app = application.New(application.Options{
		Name: "ADHD Support System · I-01 开发验收", Description: "首个确定性执行闭环（隔离开发数据）",
		Assets:         application.AssetOptions{Handler: application.BundledAssetFileServer(assets), DisableLogging: true, Middleware: h.middleware},
		Services:       []application.Service{application.NewService(h.notifications)},
		Windows:        application.WindowsOptions{DisableQuitOnLastWindowClosed: true, WebviewBrowserPath: *runtime},
		SingleInstance: &application.SingleInstanceOptions{UniqueID: "a7ccfd38-3e0c-4bf0-82c1-93a7cb73ab71", OnSecondInstanceLaunch: func(application.SecondInstanceData) { h.mainWindow.Show().Focus() }},
	})
	h.mainWindow = h.app.Window.NewWithOptions(application.WebviewWindowOptions{Name: "main", Title: "执行支持 · I-01 开发验收", Width: 780, Height: 680, URL: "/"})
	h.overlay = h.app.Window.NewWithOptions(application.WebviewWindowOptions{Name: "overlay", Title: "当前行动 · 开发验收", Width: 430, Height: 580, AlwaysOnTop: true, Hidden: true, URL: "/?surface=overlay"})
	for _, window := range []*application.WebviewWindow{h.mainWindow, h.overlay} {
		w := window
		w.RegisterHook(events.Common.WindowClosing, func(event *application.WindowEvent) {
			event.Cancel()
			w.ExecJS("window.dispatchEvent(new Event('host-close'))")
		})
	}
	tray := h.app.SystemTray.New()
	tray.SetIcon(icons.SystrayLight)
	tray.SetTooltip("执行支持 · I-01 开发验收")
	menu := h.app.NewMenu()
	menu.Add("显示主窗口").OnClick(func(*application.Context) { h.mainWindow.Show().Focus() })
	menu.Add("显示当前行动").OnClick(func(*application.Context) { h.overlay.Show().Focus() })
	menu.Add("退出开发验收").OnClick(func(*application.Context) { h.app.Quit() })
	tray.SetMenu(menu)
	h.notifications.OnNotificationResponse(func(result notifications.NotificationResult) {
		if result.Error != nil {
			h.record("notification_response_failed", nil)
			return
		}
		raw, _ := json.Marshal(result.Response.UserInfo)
		status, _, err := h.bridge.request("POST", "/v1/context", raw)
		h.mu.Lock()
		h.notice = map[string]any{"valid": err == nil && status == 200, "context": result.Response.UserInfo}
		h.mu.Unlock()
		h.record("notification_opened", map[string]any{"valid": err == nil && status == 200})
		h.mainWindow.Show().Focus()
	})
	stopped := make(chan struct{})
	h.app.OnShutdown(func() { cancel(); <-stopped })
	go func() { defer close(stopped); h.supervise(ctx, *python, *root, *data) }()
	if err := h.app.Run(); err != nil {
		log.Print("desktop stopped with error")
	}
}
func (h *desktopHost) middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/api/") {
			h.bridge.serve(w, r)
			return
		}
		if strings.HasPrefix(r.URL.Path, "/ui/") {
			if r.Header.Get("X-I01-Client") != "1" {
				http.Error(w, "embedded client required", 403)
				return
			}
			if r.URL.Path == "/ui/notice" && r.Method == "GET" {
				h.mu.Lock()
				defer h.mu.Unlock()
				w.Header().Set("Content-Type", "application/json")
				_ = json.NewEncoder(w).Encode(h.notice)
				return
			}
			if r.URL.Path == "/ui/hide" && r.Method == "POST" {
				if r.URL.Query().Get("surface") == "overlay" {
					h.overlay.Hide()
				} else {
					h.mainWindow.Hide()
				}
				w.WriteHeader(204)
				return
			}
			http.NotFound(w, r)
			return
		}
		next.ServeHTTP(w, r)
	})
}
func (h *desktopHost) record(kind string, fields map[string]any) {
	h.mu.Lock()
	defer h.mu.Unlock()
	file, err := os.OpenFile(h.evidence, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0600)
	if err != nil {
		return
	}
	defer file.Close()
	// Call sites use only bounded event codes, fixture IDs and booleans.
	_ = json.NewEncoder(file).Encode(map[string]any{"time": time.Now().UTC().Format(time.RFC3339Nano), "kind": kind, "fields": fields})
}
func (h *desktopHost) supervise(ctx context.Context, python, root, data string) {
	for attempt := 0; attempt < 4; attempt++ {
		if ctx.Err() != nil {
			return
		}
		p, material, err := launch(ctx, python, root, data, 8*time.Second)
		if err != nil {
			h.record("core_bootstrap_failed", nil)
		} else {
			h.bridge.set(material)
			h.record("core_connected", nil)
			watchCtx, watchCancel := context.WithCancel(ctx)
			watchDone := make(chan struct{})
			go func() { defer close(watchDone); h.watch(watchCtx, material) }()
			select {
			case <-ctx.Done():
			case <-p.done:
			}
			h.bridge.set(endpoint{})
			watchCancel()
			p.stop()
			<-watchDone
			h.record("core_disconnected", nil)
		}
		if ctx.Err() != nil {
			return
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(time.Duration(1<<attempt) * time.Second):
		}
	}
	h.record("core_restart_limit_reached", nil)
}
func (h *desktopHost) watch(ctx context.Context, material endpoint) {
	for ctx.Err() == nil {
		connection, _, err := websocket.Dial(ctx, strings.Replace(material.Endpoint, "http:", "ws:", 1)+"/v1/events", &websocket.DialOptions{HTTPHeader: http.Header{"Authorization": []string{"Bearer " + material.Token}}})
		if err != nil {
			select {
			case <-ctx.Done():
				return
			case <-time.After(time.Second):
				continue
			}
		}
		connection.SetReadLimit(4 << 20)
		for ctx.Err() == nil {
			round, cancel := context.WithTimeout(ctx, 3*time.Second)
			err = connection.Write(round, websocket.MessageText, []byte(`{"kind":"snapshot"}`))
			var raw []byte
			if err == nil {
				_, raw, err = connection.Read(round)
			}
			cancel()
			if err != nil {
				break
			}
			var state struct {
				Deliveries []struct {
					ID            string `json:"id"`
					Version       int    `json:"version"`
					Target        string `json:"target"`
					TargetKind    string `json:"target_kind"`
					TargetVersion int    `json:"target_version"`
					Status        string `json:"status"`
				} `json:"deliveries"`
			}
			if json.Unmarshal(raw, &state) == nil {
				for _, d := range state.Deliveries {
					if d.Status != "pending" {
						continue
					}
					if !h.bridge.command("delivery_claim", d.ID, d.Version, map[string]any{}, "claim:"+d.ID) {
						continue
					}
					contextData := map[string]any{"kind": d.TargetKind, "id": d.Target, "version": d.TargetVersion}
					category := notifications.NotificationCategory{ID: "i01-open", Actions: []notifications.NotificationAction{{ID: "OPEN_CONTEXT", Title: "查看当前行动"}}}
					notificationErr := h.notifications.RegisterNotificationCategory(category)
					if notificationErr == nil {
						notificationErr = h.notifications.SendNotificationWithActions(notifications.NotificationOptions{ID: d.ID, Title: "执行支持 · 开发验收", Body: "约定的行动或检查时间已到。可在应用中查看并选择。", CategoryID: category.ID, Data: contextData})
					}
					h.overlay.Show().Focus()
					// Successful native notification submission is the transport receipt, not proof of presence.
					delivered := notificationErr == nil
					h.bridge.command("delivery_receipt", d.ID, d.Version+1, map[string]any{"delivered": delivered}, "receipt:"+d.ID)
					h.record("presentation_requested", map[string]any{"context_id": d.Target, "notification_submitted": delivered})
				}
			}
			select {
			case <-ctx.Done():
			case <-time.After(400 * time.Millisecond):
			}
		}
		_ = connection.CloseNow()
	}
}
