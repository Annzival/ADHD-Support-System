"""最小 WebSocket 服务端工具（沿用 V-02 spike 验证过的帧实现，仅服务端推送）。"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import threading
from socket import socket

WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_SERVER_FRAME = 1 << 20


def accept_key(client_key: str) -> str:
    return base64.b64encode(hashlib.sha1((client_key + WEBSOCKET_GUID).encode("ascii")).digest()).decode("ascii")


def _read_exact(connection: socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = connection.recv(size - len(data))
        if not chunk:
            raise ConnectionError("websocket peer closed")
        data.extend(chunk)
    return bytes(data)


def read_client_frame(connection: socket) -> tuple[int, bytes]:
    first, second = _read_exact(connection, 2)
    opcode = first & 0x0F
    masked = (second & 0x80) != 0
    payload_length = second & 0x7F
    if payload_length == 126:
        payload_length = struct.unpack("!H", _read_exact(connection, 2))[0]
    elif payload_length == 127:
        payload_length = struct.unpack("!Q", _read_exact(connection, 8))[0]
    if payload_length > 1_048_576:
        raise ValueError("client websocket frame is too large")
    payload = bytearray()
    if masked:
        mask = _read_exact(connection, 4)
        payload = bytearray(_read_exact(connection, payload_length))
        for index in range(len(payload)):
            payload[index] ^= mask[index % 4]
    else:
        payload = bytearray(_read_exact(connection, payload_length))
    return opcode, bytes(payload)


def encode_server_frame(opcode: int, payload: bytes) -> bytes:
    length = len(payload)
    first = 0x80 | opcode
    if length < 126:
        header = bytes((first, length))
    elif length <= 65_535:
        header = bytes((first, 126)) + struct.pack("!H", length)
    else:
        header = bytes((first, 127)) + struct.pack("!Q", length)
    return header + payload


class ConnectionRegistry:
    """跟踪活跃 WebSocket 连接并向它们广播文本事件。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._connections: dict[int, tuple[socket, threading.Lock]] = {}
        self._next_id = 0

    def register(self, connection: socket) -> int:
        with self._lock:
            handle = self._next_id
            self._next_id += 1
            self._connections[handle] = (connection, threading.Lock())
            return handle

    def unregister(self, handle: int) -> None:
        with self._lock:
            self._connections.pop(handle, None)

    def broadcast_json(self, payload: dict) -> None:
        encoded = encode_server_frame(0x1, json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8"))
        with self._lock:
            items = list(self._connections.items())
        for handle, (connection, send_lock) in items:
            try:
                with send_lock:
                    connection.sendall(encoded)
            except OSError:
                self.unregister(handle)

    def ping_all(self) -> None:
        frame = encode_server_frame(0x9, b"")
        with self._lock:
            items = list(self._connections.items())
        for handle, (connection, send_lock) in items:
            try:
                with send_lock:
                    connection.sendall(frame)
            except OSError:
                self.unregister(handle)
