import base64
import http.client
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


def masked(payload):
    data = json.dumps(payload).encode()
    mask = b'abcd'
    return bytes((129, 128 | len(data))) + mask + bytes(v ^ mask[i % 4] for i, v in enumerate(data))


def response_frame(file):
    head = file.read(2)
    if len(head) != 2:
        raise ConnectionError('closed')
    size = head[1] & 127
    if size == 126:
        size = struct.unpack('!H', file.read(2))[0]
    elif size == 127:
        size = struct.unpack('!Q', file.read(8))[0]
    return json.loads(file.read(size))


class ProcessTransport(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.data = self.root / 'data'
        subprocess.run([sys.executable, '-m', 'agent_core', 'seed', '--data-dir', str(self.data),
                        '--confirm-development-fixture', '--start-delay', '1'], check=True, capture_output=True)
        self.process = None
        self.start()

    def tearDown(self):
        self.stop()
        self.directory.cleanup()

    def start(self):
        bootstrap = self.root / 'bootstrap.json'
        self.process = subprocess.Popen([sys.executable, '-m', 'agent_core', 'serve', '--data-dir', str(self.data),
                                         '--bootstrap', str(bootstrap)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 5
        while not bootstrap.exists():
            if self.process.poll() is not None or time.monotonic() > deadline:
                self.fail('Core did not publish bootstrap')
            time.sleep(.02)
        record = json.loads(bootstrap.read_text())
        bootstrap.unlink()
        self.port = int(record['endpoint'].rsplit(':', 1)[1])
        self.token = record['token']

    def stop(self):
        if self.process is not None:
            self.process.kill()
            self.process.wait(timeout=5)
            self.process = None

    def http(self, path='/v1/state', body=None, token=None, omit=False):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        headers = {} if omit else {'Authorization': 'Bearer ' + (token or self.token)}
        connection.request('POST' if body is not None else 'GET', path,
                           json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        status, result = response.status, json.loads(response.read())
        connection.close()
        return status, result

    def ws(self, token=None, omit=False):
        connection = socket.create_connection(('127.0.0.1', self.port), timeout=3)
        file = connection.makefile('rb')
        auth = '' if omit else f'Authorization: Bearer {token or self.token}\r\n'
        request = (f'GET /v1/events HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n'
                   'Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\n'
                   f'Sec-WebSocket-Key: {base64.b64encode(os.urandom(16)).decode()}\r\n{auth}\r\n')
        connection.sendall(request.encode())
        status = int(file.readline().split()[1])
        while file.readline() != b'\r\n':
            pass
        return connection, file, status

    def test_desk03_http_websocket_tokens_and_restart(self):
        before = self.http()[1]
        for token, omit in (('wrong', False), (None, True)):
            self.assertEqual(self.http(token=token, omit=omit)[0], 401)
            connection, file, status = self.ws(token=token, omit=omit)
            self.assertEqual(status, 401)
            file.close()
            connection.close()
        connection, file, status = self.ws()
        self.assertEqual(status, 101)
        connection.sendall(masked({'kind': 'snapshot'}))
        self.assertEqual(response_frame(file)['database_id'], before['database_id'])
        old_token = self.token
        self.stop()
        with self.assertRaises((ConnectionError, OSError)):
            connection.sendall(masked({'kind': 'snapshot'}))
            response_frame(file)
        file.close()
        connection.close()
        self.start()
        self.assertNotEqual(self.token, old_token)
        self.assertEqual(self.http(token=old_token)[0], 401)
        connection, file, status = self.ws(token=old_token)
        self.assertEqual(status, 401)
        file.close()
        connection.close()
        self.assertEqual(self.http()[1]['database_id'], before['database_id'])

    def test_real_process_golden_path_lost_response_restart_and_old_context(self):
        connection, file, status = self.ws()
        deadline = time.monotonic() + 4
        while True:
            connection.sendall(masked({'kind': 'snapshot'}))
            state = response_frame(file)
            if state['interventions']:
                break
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.1)
        self.assertEqual(state['deliveries'][0]['status'], 'pending')
        def submit(kind, target, version, payload, identity):
            return self.http('/v1/commands', dict(kind=kind, target=target, version=version, payload=payload, command_id=identity))
        self.assertEqual(submit('delivery_claim', 'delivery:arrangement-a', 1, {}, 'claim')[0], 200)
        self.assertEqual(submit('delivery_receipt', 'delivery:arrangement-a', 2, {'delivered': True}, 'receipt')[0], 200)
        valid = dict(kind='interventions', id='intervention:arrangement-a', version=1)
        self.assertTrue(self.http('/v1/context', valid)[1]['valid'])
        status, result = submit('start', valid['id'], 1, {}, 'start')
        self.assertEqual(status, 200)
        before = self.http()[1]
        file.close()
        connection.close()
        self.stop()
        self.start()
        self.assertEqual(submit('start', valid['id'], 1, {}, 'start'), (200, result))
        after = self.http()[1]
        self.assertEqual(after['sessions'], before['sessions'])
        self.assertEqual(after['checkpoints'], before['checkpoints'])
        self.assertEqual(after['events'], before['events'])
        self.assertEqual(self.http('/v1/context', valid)[0], 409)
        self.assertEqual(submit('start', valid['id'], 1, {}, 'stale')[0], 409)
        session = result['session_id']
        self.assertEqual(submit('report_complete', session, 1, {}, 'complete')[0], 200)
        self.assertEqual(submit('skip_closure', session, 2, {}, 'end')[0], 200)
        self.stop()
        self.start()
        state = self.http()[1]
        self.assertEqual(state['sessions'][0]['status'], 'ended')
        self.assertEqual(len(state['evidence']), 1)
        self.assertIsNone(state['active_session'])
