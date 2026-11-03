"""Run the simulated scan page on ARM using only the local native UI API.

The replay flag is mandatory. No motor, camera, ADC or PL demo transport is
opened; neural inference in the native renderer remains a separate PL task.
"""
import argparse
import json
from pathlib import Path
import signal
import threading
import subprocess

from .demo_integration import DemoSession


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', required=True, action='store_true')
    parser.add_argument('--display', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--port', type=int, default=8686)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535 or not args.display.is_dir():
        parser.error('existing display directory and valid local port required')
    stopped = threading.Event()
    for name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(name, lambda *_: stopped.set())

    def request(path, body=None):
        # The vendor image splits out Python's socket extension. Its installed
        # wget performs the local HTTP exchange without replacing system Python.
        command = ['wget', '-q', '-T', '2', '-O', '-']
        if body is not None:
            command += ['--post-data=' + body]
        command += ['http://127.0.0.1:' + str(args.port) + path]
        result = subprocess.run(command, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=4, check=True)
        return json.loads(result.stdout)

    demo = DemoSession(args.display, args.output)
    seen = None
    revision = -1
    previous_error = None
    print('BOARD_SCAN_DEMO replay=true motion=simulated acquisition=historical', flush=True)
    try:
        while not stopped.wait(.2):
            try:
                app = request('/status')['app']
                if seen is None:
                    seen = app['demo_command']
                if app['demo_command'] != seen:
                    seen = app['demo_command']
                    if app['demo_request'] == 1 and app['raw_board']:
                        demo.start()
                    elif app['demo_request'] == 2:
                        demo.reset()
                with demo.lock:
                    current = demo.revision
                if app['mode'] == 16 and current != revision:
                    request('/app', 'demo_point ' + str(app['demo_point']))
                    revision = current
                if previous_error:
                    print('BOARD_SCAN_DEMO UI reconnected', flush=True)
                previous_error = None
            except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
                if str(exc) != previous_error:
                    print('BOARD_SCAN_DEMO waiting: ' + str(exc), flush=True)
                previous_error = str(exc)
    finally:
        demo.stop()
        (args.output/'last-status.json').write_text(
            json.dumps(demo.status(), ensure_ascii=False, indent=2), encoding='utf8')


if __name__ == '__main__':
    main()
