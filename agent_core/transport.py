"""只监听动态回环端口。运行令牌经一次性文件交接，不进入日志和数据库。"""
import base64
import hashlib
import json
import os
import secrets
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .core import Rejected, encode


def read_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            raise ConnectionError('closed')
        data.extend(chunk)
    return bytes(data)


def read_frame(stream):
    first, second = read_exact(stream, 2)
    size = second & 127
    if first & 112 or not first & 128 or not second & 128:
        raise ValueError('unsupported websocket frame')
    if size == 126:
        size = struct.unpack('!H', read_exact(stream, 2))[0]
    elif size == 127:
        size = struct.unpack('!Q', read_exact(stream, 8))[0]
    if size > 16384 or ((first & 15) >= 8 and size > 125):
        raise ValueError('frame too large')
    mask = read_exact(stream, 4)
    payload = read_exact(stream, size)
    return first & 15, bytes(value ^ mask[index % 4] for index, value in enumerate(payload))


def frame(payload, opcode=1):
    size = len(payload)
    if size < 126:
        return bytes((128 | opcode, size)) + payload
    if size <= 65535:
        return bytes((128 | opcode, 126)) + struct.pack('!H', size) + payload
    return bytes((128 | opcode, 127)) + struct.pack('!Q', size) + payload


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, core):
        self.core = core
        self.token = secrets.token_urlsafe(32)
        self.last_desktop = 0.0
        self.scheduler_error = False
        self.stopped = threading.Event()
        super().__init__(('127.0.0.1', 0), Handler)

    def schedule(self):
        last_tick = time.monotonic()
        while not self.stopped.wait(0.2):
            now = time.monotonic()
            try:
                online = now - self.last_desktop < 2 and now - last_tick < 2
                if not online:
                    for delivery in self.core.snapshot()['deliveries']:
                        if delivery['status'] in ('pending', 'claimed'):
                            try:
                                self.core.command('delivery_expire', delivery['id'], delivery['version'], {}, 'expire:' + delivery['id'])
                            except Rejected:
                                pass
                self.core.tick(desktop_online=online)
                self.scheduler_error = False
            except Exception:
                # Fail closed and expose transport unavailability, never a false ready state.
                self.scheduler_error = True
            last_tick = now

    def publish(self, path):
        path = Path(path)
        if path.exists():
            raise FileExistsError('bootstrap already exists')
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as file:
            json.dump(dict(endpoint=f'http://127.0.0.1:{self.server_port}', token=self.token), file)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *_):
        pass

    def reply(self, status, value):
        data = encode(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        if not secrets.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + self.server.token):
            self.close_connection = True
            self.reply(401, {'error': 'unauthorized'})
            return False
        # No browser-origin calls to the Core; the embedded frontend uses its host API bridge.
        if self.headers.get('Origin'):
            self.reply(403, {'error': 'browser_origin_not_allowed'})
            return False
        return True

    def do_GET(self):
        if not self.authorized():
            return
        if self.server.scheduler_error:
            self.reply(503, {'error': 'scheduler_storage_unavailable'})
            return
        if self.path == '/v1/state':
            self.reply(200, self.server.core.snapshot())
        elif self.path == '/v1/events':
            self.websocket()
        else:
            self.reply(404, {'error': 'not_found'})

    def websocket(self):
        key = self.headers.get('Sec-WebSocket-Key', '')
        try:
            valid_key = len(base64.b64decode(key, validate=True)) == 16
        except ValueError:
            valid_key = False
        if self.headers.get('Upgrade', '').lower() != 'websocket' or self.headers.get('Sec-WebSocket-Version') != '13' or not valid_key:
            self.reply(400, {'error': 'invalid_websocket_upgrade'})
            return
        accept = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
        self.send_response(101)
        self.send_header('Upgrade', 'websocket')
        self.send_header('Connection', 'Upgrade')
        self.send_header('Sec-WebSocket-Accept', accept)
        self.end_headers()
        try:
            while not self.server.stopped.is_set():
                opcode, payload = read_frame(self.rfile)
                if opcode == 8:
                    self.wfile.write(frame(payload, 8))
                    break
                if opcode == 9:
                    self.wfile.write(frame(payload, 10))
                    continue
                if opcode != 1 or json.loads(payload) != {'kind': 'snapshot'}:
                    raise ValueError('only snapshot subscription supported')
                self.server.last_desktop = time.monotonic()
                self.wfile.write(frame(encode(self.server.core.snapshot()).encode()))
                self.wfile.flush()
        except (OSError, ValueError, ConnectionError):
            pass
        finally:
            self.close_connection = True

    def do_POST(self):
        if not self.authorized():
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 16384:
                raise ValueError('invalid body size')
            body = json.loads(read_exact(self.rfile, size))
            if not isinstance(body, dict):
                raise ValueError('object required')
            if self.path == '/v1/commands':
                if body.get('kind') not in ('start', 'report_complete', 'finish_closure', 'skip_closure', 'delivery_claim', 'delivery_receipt'):
                    raise Rejected('operation_not_available_in_i01')
                if not isinstance(body.get('payload'), dict):
                    raise ValueError('payload required')
                result = self.server.core.command(body['kind'], body['target'], body['version'], body['payload'], body['command_id'])
                self.reply(200, result)
            elif self.path == '/v1/context':
                result = self.server.core.context(body['kind'], body['id'], body['version'])
                self.reply(200 if result['valid'] else 409, result)
            else:
                self.reply(404, {'error': 'not_found'})
        except Rejected as error:
            self.reply(409, {'error': str(error), 'state': self.server.core.snapshot()})
        except (ValueError, TypeError, KeyError):
            self.reply(400, {'error': 'invalid_request'})
        except Exception:
            self.reply(503, {'error': 'not_committed_retry_same_command'})
