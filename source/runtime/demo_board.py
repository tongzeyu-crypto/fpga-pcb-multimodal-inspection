"""Run the simulated scan page on ARM using only the local native UI API.

Default motion/acquisition are fixtures. --live-scan with an explicit calibrated
configuration uses GRBL feedback and fresh ADC. Motion starts only on UI command.
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
    parser.add_argument('--replay', action='store_true',help='use checked simulation results explicitly; never selected automatically')
    parser.add_argument('--display', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--port', type=int, default=8686)
    parser.add_argument('--control', type=Path, help='atomic control file published by the native renderer')
    parser.add_argument('--live-scan',action='store_true')
    parser.add_argument('--motion-config',type=Path)
    parser.add_argument('--board',type=int,choices=[0,1],default=1)
    parser.add_argument('--capture-index',type=Path)
    args = parser.parse_args()
    if args.live_scan and (args.replay or not args.motion_config):parser.error('live scan requires actual PL and calibrated motion configuration')
    motion_config=json.loads(args.motion_config.read_text()) if args.live_scan else None
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

    from .compute_backend import PlCompute
    from demo.runtime.backend import RtlReplay
    captures=json.loads(args.capture_index.read_text()) if args.capture_index else {}
    def session_for(board):
        key='dcdc' if board else 'stm32';entry=captures.get(key)
        if args.live_scan and entry is None:
            path=args.display/('dcdc' if board else '')/'capture-source.json'
            entry=json.loads(path.read_text())
        return DemoSession(args.display,args.output/key,backend_factory=RtlReplay if args.replay else PlCompute,motion_config=motion_config,capture_bundle=entry['bundle'] if args.live_scan else None,processing=entry['processing'] if args.live_scan else None,board_id=key)
    active_board=args.board;demo=session_for(active_board);config_seen=0
    seen = None
    revision = -1
    previous_error = None
    session = None
    print('BOARD_SCAN compute='+demo.pl.backend+' live_scan='+str(bool(motion_config)),flush=True)
    try:
        while not stopped.wait(.2):
            try:
                app = json.loads(args.control.read_text()) if args.control else request('/status')['app']
                if args.live_scan and app['raw_board']!=active_board:
                    demo.stop();active_board=app['raw_board'];demo=session_for(active_board);demo.configure(app['scan_config']);config_seen=app.get('scan_config_revision',0);seen=app['demo_command']
                if app.get('scan_config_revision',0)!=config_seen:
                    demo.configure(app['scan_config']);config_seen=app['scan_config_revision']
                current_session = app.get('session_ns')
                if current_session != session:
                    seen = None
                    session = current_session
                if seen is None:
                    seen = app['demo_command']
                if app['demo_command'] != seen:
                    seen = app['demo_command']
                    if app['demo_request'] == 1 and (args.live_scan or app['raw_board']):
                        demo.start()
                    elif app['demo_request'] == 2:
                        demo.reset()
                    elif app['demo_request'] == 3:
                        demo.pause()
                with demo.lock:
                    current = demo.revision
                if app['mode'] == 16 and current != revision:
                    if not args.control:request('/app', 'demo_point ' + str(app['demo_point']))
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
