"""Launch the native PL-backed UI plus the explicitly simulated scan page."""
import argparse
import platform
from pathlib import Path
import signal
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board-demo', action='store_true', required=True)
    parser.add_argument('--display', type=Path, required=True)
    parser.add_argument('--state', type=Path, default=Path('/tmp/pcb-board-demo'))
    parser.add_argument('--tag', required=True)
    parser.add_argument('--port', type=int, default=8686)
    args = parser.parse_args()
    if platform.system() != 'Linux' or not platform.machine().startswith('arm'):
        parser.error('board demo requires ARM Linux and actual PL devices')
    display, state = args.display.resolve(), args.state.resolve()
    if not str(display).startswith('/tmp/') or not str(state).startswith('/tmp/'):
        parser.error('display snapshots and runtime state must be in /tmp RAM storage')
    if not (display/'generation.json').is_file():
        parser.error('source-recomputed display assets required')
    if not Path('/dev/pcb_ai').exists() or not Path('/dev/pcb-gfx3').exists():
        parser.error('matching PL design, device tree and drivers must be loaded first')
    state.mkdir(parents=True, exist_ok=True)
    stopped = threading.Event()
    for name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(name, lambda *_: stopped.set())
    children = []
    try:
        with (state/'native.log').open('wb') as native_log, (state/'scan.log').open('wb') as scan_log:
            native = subprocess.Popen([
                str(ROOT/'bin/hdmi_full_runtime'), str(display), '--tag', args.tag,
                '--board', '1', '--single-plane', '1', '--port', str(args.port),
                '--log', str(state/'native'), '--release-assets', '0',
                '--ai-model', str(ROOT/'models/frame/model.pai')],
                stdout=native_log, stderr=subprocess.STDOUT)
            children.append(native)
            scan = subprocess.Popen([
                sys.executable or '/usr/bin/python3', '-m', 'runtime.demo_board', '--replay',
                '--display', str(display), '--output', str(state/'scan-sessions'),
                '--port', str(args.port)], cwd=str(ROOT),
                stdout=scan_log, stderr=subprocess.STDOUT)
            children.append(scan)
            print('BOARD_DEMO native_PL_AI=true scan_motion=simulated storage=RAM', flush=True)
            while not stopped.wait(.25):
                if native.poll() is not None:
                    if native.returncode:
                        raise RuntimeError('native UI exited; inspect ' + str(state/'native.log'))
                    break
                if scan.poll() is not None:
                    raise RuntimeError('scan replay exited; inspect ' + str(state/'scan.log'))
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in reversed(children):
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == '__main__':
    main()
