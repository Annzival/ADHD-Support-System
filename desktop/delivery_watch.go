package main

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"time"

	"github.com/coder/websocket"
)

func watchDeliveries(ctx context.Context, material endpoint, pump *deliveryPump) {
	// HTTP retries must not hold the WebSocket heartbeat past Core's online lease.
	workCtx, stop := context.WithCancel(ctx)
	snapshots := make(chan []delivery, 1)
	done := make(chan struct{})
	go func() {
		defer close(done)
		for {
			select {
			case <-workCtx.Done():
				return
			case ds := <-snapshots:
				pump.step(ds)
			}
		}
	}()
	defer func() { stop(); <-done }()

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
				Deliveries []delivery `json:"deliveries"`
			}
			if json.Unmarshal(raw, &state) == nil {
				select {
				case <-snapshots:
				default:
				}
				select {
				case snapshots <- state.Deliveries:
				default:
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
