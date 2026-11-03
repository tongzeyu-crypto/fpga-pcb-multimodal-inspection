"""Interactive integration of the small PL demo; no device transports exist here."""
from pathlib import Path
from demo.runtime.hashutil import sha256
import json
import threading
import time

from demo.runtime.backend import RtlReplay
from demo.runtime.scan_demo import ScanScheduler, SimulatedMotion, RawReplaySampler, serpentine

ROOT = Path(__file__).resolve().parents[1]
STATES = ['READY', 'ROUTE', 'MOVE', 'WAIT_ARRIVAL', 'SETTLE', 'CAPTURE', 'ASSOCIATE', 'DONE', 'FAULT', 'CANCELED']


def atomic_snapshot(path, payload):
    """Windows ifstream briefly holds the old file without delete sharing."""
    temporary = path.with_suffix('.tmp')
    temporary.write_text(payload, encoding='ascii')
    for attempt in range(101):
        try:
            temporary.replace(path)
            return attempt
        except PermissionError:
            if attempt == 100:
                raise
            # The renderer closes its small snapshot after each read. Keep the
            # old complete file visible until the atomic rename can succeed.
            time.sleep(.005)


class Canceled(Exception):
    pass


class DemoClock:
    def __init__(self, cancel):
        self.cancel = cancel

    def monotonic(self):
        if self.cancel.is_set():
            raise Canceled('demo canceled')
        return time.monotonic()

    def sleep(self, seconds):
        if self.cancel.wait(seconds):
            raise Canceled('demo canceled')


class PacedSampler(RawReplaySampler):
    def __init__(self, clock):
        super().__init__()
        self.clock = clock

    def capture(self, point, frame_index):
        self.clock.sleep(.15)
        return super().capture(point, frame_index)


class DemoSession:
    """One cancelable scan per application; snapshots publish atomically."""
    def __init__(self, display_root, output, settle_s=.7):
        self.display_root, self.output = Path(display_root), Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.inputs = json.loads((ROOT/'demo/inputs/demo-inputs.json').read_text())
        self.route = serpentine(self.inputs['points'])
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.worker = None
        self.settle_s = settle_s
        self.revision = 0
        self.snapshot_retries = 0
        self.reset()

    def reset(self):
        self.stop()
        with self.lock:
            self.pl = RtlReplay()
            self.thermal = self.pl.run(2, self.inputs['thermal']['raw_kelvin16'])
            self.rgb = self.pl.run(3, self.inputs['rgb']['rgb888'])
            self.thermal_int8 = self.pl.run(3, self.inputs['thermal']['raw_kelvin16'], {'mode': 1})
            self.state, self.ordinal, self.frames = 'READY', 0, 0
            self.records, self.events, self.error = [], [], ''
            self.run_id = str(time.monotonic_ns())
            self.publish()

    def stop(self):
        self.cancel.set()
        if self.worker and self.worker is not threading.current_thread():
            self.worker.join(timeout=5)
            if self.worker.is_alive():
                raise RuntimeError('previous demo scan did not stop')
        self.worker = None

    def start(self):
        with self.lock:
            if self.worker and self.worker.is_alive():
                return False
        self.reset()
        self.cancel.clear()
        self.worker = threading.Thread(target=self._run, name='offline-demo-scan', daemon=True)
        self.worker.start()
        return True

    def on_event(self, event):
        with self.lock:
            self.events.append(event)
            self.state = event['state']
            self.ordinal = event.get('ordinal', self.ordinal)
            if self.state == 'MOVE': self.frames = 0
            if self.state == 'CAPTURE': self.frames = event['frame_index']
            if self.state == 'ASSOCIATE': self.frames = 3
            self.publish()

    def on_point(self, record):
        with self.lock:
            self.records.append(record)
            self.publish()

    def _run(self):
        clock = DemoClock(self.cancel)
        scheduler = ScanScheduler(SimulatedMotion(clock), PacedSampler(clock), self.pl,
                                  clock=clock, settle_s=self.settle_s, poll_s=.08,
                                  on_event=self.on_event, on_point=self.on_point)
        try:
            scheduler.run(self.inputs['points'])
        except Canceled:
            with self.lock: self.state = 'CANCELED'
        except Exception as exc:
            with self.lock: self.state, self.error = 'FAULT', str(exc)
        finally:
            with self.lock:
                self.publish()
                # A new run gets a new file. Reset never reuses an old result.
                (self.output/('scan-'+self.run_id+'.json')).write_text(
                    json.dumps(self.status(), ensure_ascii=False, indent=2), encoding='utf8')

    def status(self):
        with self.lock:
            return dict(schema='IntegratedPlPsDemo/1', run_id=self.run_id,
                        state=self.state, revision=self.revision, ordinal=self.ordinal,
                        frames=self.frames, completed=len(self.records), route=self.route,
                        points=self.records, events=self.events, error=self.error,
                        thermal=self.thermal, rgb_int8=self.rgb, thermal_int8=self.thermal_int8,
                        motion_simulated=True, fresh_acquisition=False, hardware_synchronized=False,
                        pl_backend='XSim checked AXI result replay', pl_calls=list(self.pl.calls),
                        snapshot_retries=self.snapshot_retries,
                        input_sha256=sha256((ROOT/'demo/inputs/demo-inputs.json').read_bytes()).hexdigest())

    def publish(self):
        self.revision += 1
        lines = [f'PDPVIEW1 {self.revision} {STATES.index(self.state)} {len(self.records)} {self.ordinal} {self.frames}']
        ready = {r['ordinal']: r for r in self.records}
        for i, point in enumerate(self.route):
            r = ready.get(i)
            lines.append(' '.join(map(str, [*point['xy_mm'], int(r is not None), *(r['mean_power'] if r else [0]*33)])))
        stats = self.thermal['statistics']
        lines.append(' '.join(map(str, [stats['min_mc'], stats['max_mc'], stats['max_index'], stats['hot_count']])))
        for result in [self.thermal, self.rgb, self.thermal_int8]:
            lines.append(' '.join(map(str, result['output'])))
        for folder in [self.display_root, self.display_root/'dcdc']:
            if not folder.exists(): continue
            p = folder/'demo-view.txt'
            self.snapshot_retries += atomic_snapshot(p, '\n'.join(lines)+'\n')
