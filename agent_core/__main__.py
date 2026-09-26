import argparse
import json
import platform
import sqlite3
import struct
import threading
import time
from pathlib import Path

from .core import Core
from .transport import Server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['seed', 'serve', 'inspect'])
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--confirm-development-fixture', action='store_true')
    parser.add_argument('--start-delay', type=int, default=45)
    parser.add_argument('--duration', type=int, default=60)
    parser.add_argument('--without-duration', action='store_true')
    parser.add_argument('--window-seconds', type=int, default=14400)
    parser.add_argument('--second-delay', type=int)
    parser.add_argument('--second-version')
    parser.add_argument('--grace-seconds', type=int, default=600)
    parser.add_argument('--bootstrap', type=Path)
    args = parser.parse_args()
    marker = args.data_dir / 'i01-development-only.json'
    if args.mode == 'seed':
        if not args.confirm_development_fixture or (args.data_dir.exists() and any(args.data_dir.iterdir())):
            parser.error('requires explicit development confirmation and a new empty directory')
        args.data_dir.mkdir(parents=True, exist_ok=True)
        core = Core(args.data_dir / 'state.sqlite3')
        start = time.time() + args.start_delay
        core.seed_fixture(confirmed=True, start=start, duration=None if args.without_duration else args.duration,
                          window_end=start + args.window_seconds if args.window_seconds else None,
                          second_start=start + args.second_delay if args.second_delay is not None else None,
                          second_version=args.second_version, grace=args.grace_seconds)
        marker.write_text(json.dumps({'purpose': 'I01_DEVELOPMENT_ONLY', 'fixture': 'P/A/a-v1', 'confirmed': True}), encoding='utf-8')
        print('Development fixture confirmed; not an import or dogfooding setup.')
        return
    if not marker.exists() or json.loads(marker.read_text(encoding='utf-8')).get('purpose') != 'I01_DEVELOPMENT_ONLY':
        parser.error('I-01 requires an isolated confirmed development fixture directory')
    core = Core(args.data_dir / 'state.sqlite3')
    if args.mode == 'inspect':
        state = core.snapshot()
        print(json.dumps({'environment': {'python': platform.python_version(), 'process_bits': struct.calcsize('P') * 8,
                                          'sqlite': sqlite3.sqlite_version}, 'state': state}, ensure_ascii=True, indent=2))
        return
    if args.bootstrap is None:
        parser.error('--bootstrap required')
    core.recover()
    server = Server(core)
    server.publish(args.bootstrap)
    scheduler = threading.Thread(target=server.schedule, daemon=True)
    scheduler.start()
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.stopped.set()
        server.server_close()


if __name__ == '__main__':
    main()
