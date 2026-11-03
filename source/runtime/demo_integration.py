"""Full-sized signal/image processing demonstration with an explicit compute backend."""
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
    def __init__(self, display_root, output, settle_s=.5,backend_factory=RtlReplay,motion_config=None,capture_bundle=None,processing=None,board_id='dcdc'):
        self.display_root, self.output = Path(display_root), Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.capture_bundle=Path(capture_bundle).resolve() if capture_bundle else None
        self.processing=Path(processing).resolve() if processing else None
        self.board_id=board_id;self.map_manifest=None
        if motion_config and not self.capture_bundle:raise ValueError('live scan requires its actual board capture bundle')
        if self.capture_bundle:
            from .capture_bundle import load
            bundle=load(self.capture_bundle,board_id);self.capture=bundle
            raw=(self.capture_bundle.parent/bundle['raw']['thermal'][0]['path']).read_bytes()
            import struct
            self.inputs={'thermal':{'shape':[192,256],'raw_kelvin16':list(struct.unpack('<49152H',raw[98304:]))},'rgb':{'shape':[192,256]},'points':[]}
            self.input_digest=sha256(self.capture_bundle.read_bytes()).hexdigest()
        else:
            self.inputs=json.loads((ROOT/'demo/inputs/full-inputs.json').read_text());self.input_digest=sha256((ROOT/'demo/inputs/full-inputs.json').read_bytes()).hexdigest()
        self.backend_factory=backend_factory
        self.motion_config=dict(motion_config) if motion_config else None;self.motion=None
        from demo.runtime.scan_demo import report_route
        self.scan_config={key:(motion_config or {}).get(key,default) for key,default in [('width',70),('height',44),('step_x',5),('step_y',5),('feed',120)]}
        self.planned_route=report_route(**{k:self.scan_config[k] for k in ('width','height','step_x','step_y')})
        self.route = self.planned_route if motion_config else serpentine(self.inputs['points'])
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
            self.pl = self.backend_factory()
            self.thermal = self.pl.run(2, self.inputs['thermal']['raw_kelvin16'])
            if self.capture_bundle:
                if self.processing is None:raise ValueError('matching processing record required for captured scan preview')
                record=json.loads(self.processing.read_text());path=self.processing.parent/'rgb-preview.i8'
                if record['capture_id']!=self.capture['capture_id'] or sha256(path.read_bytes()).hexdigest()!=record['output_sha256'].get(path.name):raise ValueError('captured RGB preview identity')
                import struct
                self.rgb={'output':list(struct.unpack('<49152b',path.read_bytes())),'metadata':{'source':'PL processed RGB preview'},'backend':self.pl.backend}
            else:self.rgb = self.pl.run(3, self.inputs['rgb']['rgb888'])
            self.thermal_int8 = self.pl.run(3, self.inputs['thermal']['raw_kelvin16'], {'mode': 1})
            stats=self.thermal['statistics']
            if self.pl.backend=='PDP3 MMIO':
                self.palette=self.pl.image_words('color',self.thermal['output'],256,192,low=stats['min_mc'],high=stats['max_mc'])
            else:
                from demo.runtime.report_reference import image_words
                self.palette=image_words(10,self.thermal['output'],low=stats['min_mc'],high=stats['max_mc'])
            self.state, self.ordinal, self.frames = 'READY', 0, 0
            self.records, self.events, self.error = [], [], ''
            self.run_id = str(time.monotonic_ns())
            self.publish()

    def stop(self):
        self.cancel.set()
        if self.motion is not None:self.motion.cancel()
        if self.worker and self.worker is not threading.current_thread():
            self.worker.join(timeout=20)
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

    def pause(self):
        """Stop motion and retain the completed point records for inspection."""
        self.stop()
        with self.lock:self.state='CANCELED';self.publish()

    def validate_configuration(self,settings):
        from demo.runtime.scan_demo import report_route
        with self.lock:
            if self.worker and self.worker.is_alive():raise RuntimeError('stop scan before changing the route')
            proposed=dict(self.scan_config)
            if any(k not in proposed for k in settings):raise ValueError('unknown scan setting')
            proposed.update({k:float(v) for k,v in settings.items()})
            if not 1<=proposed['feed']<=120:raise ValueError('scan feed must be 1..120')
            plan=report_route(**{k:proposed[k] for k in ('width','height','step_x','step_y')})
            return proposed,plan

    def configure(self,settings):
        with self.lock:
            proposed,plan=self.validate_configuration(settings)
            self.scan_config=proposed;self.planned_route=plan
            if self.motion_config:self.route=plan;self.motion_config.update(proposed)
            self.publish()
            return {'settings':proposed,'planned_points':len(plan),'historical_replay_uses_source_coordinates':not bool(self.motion_config)}

    def on_event(self, event):
        with self.lock:
            self.events.append(event)
            self.state = 'ASSOCIATE' if event['state']=='DONE' else event['state']
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
        try:
            if self.motion_config:
                from .motion import GrblMotion
                from .adc_sampler import AdcSampler
                config=dict(self.motion_config);config.update(self.scan_config);device=config.pop('device');config.pop('step_x',None);config.pop('step_y',None)
                self.motion=GrblMotion(device,**config)
                sampler=AdcSampler(self.motion,self.pl,self.output/('raw-'+self.run_id))
            else:self.motion=SimulatedMotion(clock);sampler=PacedSampler(clock)
            scheduler = ScanScheduler(self.motion,sampler,self.pl,clock=clock,settle_s=self.settle_s,poll_s=.08,on_event=self.on_event,on_point=self.on_point)
            scheduler.run(self.route)
            from .scan_results import publish_scan
            calibration=json.loads(self.processing.read_text()).get('calibration_source') if self.processing else None
            self.map_manifest=publish_scan(self.display_root,self.board_id,self.records,self.run_id,self.capture_bundle,calibration)
            with self.lock:self.state='DONE'
        except Canceled:
            with self.lock: self.state = 'CANCELED'
        except Exception as exc:
            with self.lock: self.state, self.error = 'FAULT', str(exc)
        finally:
            if self.motion is not None and hasattr(self.motion,'close'):self.motion.close()
            self.motion=None
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
                        board_id=self.board_id,scan_config=self.scan_config,planned_route=self.planned_route,map_publication=self.map_manifest,
                        motion_simulated=not bool(self.motion_config),fresh_acquisition=bool(self.motion_config),hardware_synchronized=False,
                        adc_position_associated=bool(self.motion_config),thermal_source='active board capture' if self.capture_bundle else 'historical fixture',
                        pl_backend=self.pl.backend, pl_calls=list(self.pl.calls),
                        snapshot_retries=self.snapshot_retries,
                        input_sha256=self.input_digest)

    def publish(self):
        self.revision += 1
        lines = [f'PDPVIEW3 {self.revision} {STATES.index(self.state)} {len(self.records)} {self.ordinal} {self.frames} {len(self.route)} {int(bool(self.motion_config))} '+' '.join(str(self.scan_config[k]) for k in ('width','height','step_x','step_y','feed'))]
        ready = {r['ordinal']: r for r in self.records}
        for i, point in enumerate(self.route):
            r = ready.get(i)
            values=r['mean_power'] if r else []
            preview=[max(values[i*len(values)//33:(i+1)*len(values)//33] or [0]) for i in range(33)] if values else [0]*33
            lines.append(' '.join(map(str, [*point['xy_mm'], int(r is not None), *preview])))
        stats = self.thermal['statistics']
        lines.append(' '.join(map(str, [stats['min_mc'], stats['max_mc'], stats['max_index'], stats['hot_count']])))
        for result,shape in zip([self.thermal,self.rgb,self.thermal_int8],[self.inputs['thermal']['shape'],self.inputs['rgb']['shape'],self.inputs['thermal']['shape']]):
            h,w=shape;values=result['output'];preview=[values[(y*h//16)*w+x*w//16] for y in range(16) for x in range(16)]
            lines.append(' '.join(map(str,preview)))
        h,w=self.inputs['thermal']['shape']
        lines.append(' '.join(str(self.palette[(y*h//16)*w+x*w//16]&0xffffffff) for y in range(16) for x in range(16)))
        lines.append('BACKEND '+str(int(self.pl.backend=='PDP3 MMIO')))
        for folder in [self.display_root/('dcdc' if self.board_id=='dcdc' else '')]:
            if not folder.exists(): continue
            p = folder/'demo-view.txt'
            self.snapshot_retries += atomic_snapshot(p, '\n'.join(lines)+'\n')
