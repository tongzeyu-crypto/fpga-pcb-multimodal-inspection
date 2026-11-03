"""Offline tests of real adapters, route control and exact report boundaries.

The GRBL process and ADC writer below are deliberate IPC fixtures. They never
open a physical device and are never selected by production launchers.
"""
from pathlib import Path
import hashlib,json,struct,subprocess,sys,tempfile,time,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from demo.runtime.scan_demo import ScanScheduler,SimulatedMotion,report_route
from runtime.motion import GrblMotion
from runtime.adc_sampler import AdcSampler

class Clock:
    def __init__(self):self.t=0
    def monotonic(self):return self.t
    def sleep(self,s):self.t+=s

class Compute:
    def run_three(self,frames):
        assert len(frames)==3 and all(len(f)==4096 for f in frames)
        return dict(output=[1<<40]*2049,metadata=dict(unit='PSD_Q40'))

class Sampler:
    def capture(self,p,i):return dict(source_xy_mm=p['xy_mm'],fresh_capture=True,samples=[0]*4096,samples_channels=[[0]*4096,[0]*4096],source_point_index=p['point_index'])

HELPER=r'''
import json,sys,time,threading,queue
q=queue.Queue();xy=[0.,0.];configured=False;pending=None;ack=0
def reader():
 for line in sys.stdin:q.put(line)
threading.Thread(target=reader,daemon=True).start()
def emit(id=0,status='Idle',error=''):
 print(json.dumps(dict(type='state',id=id,ok=not bool(error),configured=configured,error=error,status=status,local_x=xy[0],local_y=xy[1],monotonic_s=time.monotonic(),position_age_s=0)),flush=True)
emit(error='controller_reset');configured=True;emit()
while True:
 try:line=q.get(timeout=.02)
 except queue.Empty:line=None
 if line:
  words=line.split();id=int(words[0]);cmd=words[1]
  if cmd=='QUIT':emit(id);break
  if cmd=='MOVE':pending=(id,[float(words[2]),float(words[3])],time.monotonic()+.08);emit(status='Jog')
  elif cmd=='CANCEL':pending=None;emit(id,error='jog_canceled')
  else:emit(id)
 if pending:
  if time.monotonic()>=pending[2]:ack=pending[0];xy=pending[1];pending=None;emit(ack)
  else:emit(status='Jog')
 else:emit()
'''

class ContractTests(unittest.TestCase):
    def test_report_route_and_association(self):
        clock=Clock();motion=SimulatedMotion(clock);route=report_route();self.assertEqual(len(route),150)
        self.assertEqual(route[14]['xy_mm'],[70.,0.]);self.assertEqual(route[15]['xy_mm'],[70.,5.]);self.assertEqual(route[-1]['xy_mm'],[0.,44.])
        scheduler=ScanScheduler(motion,Sampler(),Compute(),clock=clock)
        results=scheduler.run(route)
        self.assertEqual(len(results),150)
        for r in results:
            self.assertGreaterEqual(r['settled_at']-r['arrival_confirmed_at'],.5-1e-9)
            self.assertEqual(r['reported_xy_mm'],r['xy_mm']);self.assertEqual(len(r['frames']),3);self.assertEqual(len(r['channel_spectra']),2)
            self.assertTrue(all(f['demo_sample_begin']>=r['settled_at'] for f in r['frames']))
    def test_stale_status_stops_before_capture(self):
        clock=Clock();motion=SimulatedMotion(clock);sampler=Sampler()
        motion.status=lambda:dict(ack=True,state='Idle',xy_mm=[0,0],reported_at=-10)
        with self.assertRaises(TimeoutError):ScanScheduler(motion,sampler,Compute(),clock=clock,arrival_timeout_s=.2).run(report_route()[:1])
        self.assertTrue(motion.canceled)
    def test_motion_during_settle_stops(self):
        clock=Clock();motion=SimulatedMotion(clock);original=motion.status
        def status():
            r=original()
            if motion.polls>3:r['state']='Hold'
            return r
        motion.status=status
        with self.assertRaises(RuntimeError):ScanScheduler(motion,Sampler(),Compute(),clock=clock).run(report_route()[:1])
        self.assertTrue(motion.canceled)
    def test_alarm_and_capture_timeout_cancel_motion(self):
        clock=Clock();motion=SimulatedMotion(clock)
        def alarm():raise RuntimeError('Alarm')
        motion.status=alarm
        with self.assertRaises(RuntimeError):ScanScheduler(motion,Sampler(),Compute(),clock=clock).run(report_route()[:1])
        self.assertTrue(motion.canceled)
        motion=SimulatedMotion(clock)
        class TimeoutSampler:
            def capture(self,p,i):raise subprocess.TimeoutExpired('ADC fixture',4)
        with self.assertRaises(subprocess.TimeoutExpired):ScanScheduler(motion,TimeoutSampler(),Compute(),clock=clock).run(report_route()[:1])
        self.assertTrue(motion.canceled)
    def test_real_grbl_protocol_adapter(self):
        with tempfile.TemporaryDirectory() as folder:
            helper=Path(folder)/'helper.py';helper.write_text(HELPER)
            with self.assertRaises(ValueError):GrblMotion('unused')
            with GrblMotion('unused',origin_confirmed=True,command=[sys.executable,'-u',str(helper)]) as motion:
                motion.move([5,4]);deadline=time.monotonic()+3
                while not motion.status()['ack']:
                    self.assertLess(time.monotonic(),deadline);time.sleep(.01)
                position=motion.status();self.assertFalse(position['simulated']);self.assertEqual(position['xy_mm'],[5,4]);self.assertEqual(position['state'],'Idle')
                self.assertLess(time.monotonic()-position['reported_at'],1)
                motion.move([10,4]);motion.cancel();time.sleep(.03);self.assertNotEqual(motion.status()['xy_mm'],[10,4])
    def test_fresh_adc_writer_and_reject_bad_size(self):
        class Motion:
            def status(self):return dict(ack=True,state='Idle',xy_mm=[5.,4.],reported_at=time.monotonic(),controller=dict(status='Idle'))
        class Decoder:
            def decode_adc_lists(self,words):
                if len(words)!=16384:raise ValueError('size')
                return [[0]*4096,[1]*4096]
        with tempfile.TemporaryDirectory() as folder:
            def command(path):return [sys.executable,'-c','from pathlib import Path;import sys;Path(sys.argv[1]).write_bytes(bytes(65536))',str(path)]
            sampler=AdcSampler(Motion(),Decoder(),Path(folder)/'capture',command=command)
            record=sampler.capture(dict(point_index=1,xy_mm=[5,4]),0)
            self.assertTrue(record['fresh_capture']);self.assertEqual(len(record['samples_channels']),2);self.assertEqual(record['source_xy_mm'],[5,4]);self.assertTrue(Path(record['source_path']).with_suffix('.json').exists())
            sampler.command=lambda path:[sys.executable,'-c','from pathlib import Path;import sys;Path(sys.argv[1]).write_bytes(bytes(4))',str(path)]
            with self.assertRaises(ValueError):sampler.capture(dict(point_index=1,xy_mm=[5,4]),1)
    def test_annotation_presence_and_connected_pin_bridge(self):
        import numpy as np
        import cv2
        from runtime.aoi_annotation import assess
        class ImageCompute:
            def __init__(self):self.calls=[]
            def image(self,op,a,**kw):
                self.calls.append(op)
                if op=='difference':return ((np.abs(a.astype(np.int64)-kw['second'])>kw['threshold'])&(kw['valid']>0)).astype(np.int32)*255
                if op=='sobel':return np.sqrt(cv2.Sobel(a.astype(np.float64),cv2.CV_64F,1,0)**2+cv2.Sobel(a.astype(np.float64),cv2.CV_64F,0,1)**2).astype(np.int32)
                raise AssertionError(op)
        before=np.full((512,512),30,np.uint8)
        yy,xx=np.indices((200,200));before[150:350,150:350]=np.where(((xx//5+yy//5)%2)>0,210,45)
        for x in [170,210,250,290,330]:before[115:151,x-3:x+4]=220
        annotation=dict(native_to_board=np.eye(3).tolist(),components=[dict(id='U-test',family='qfp',pins=dict(count_per_side=5),quad_px=[[150,150],[350,150],[350,350],[150,350]])])
        test=before.copy();test[130:139,167:214]=220;compute=ImageCompute()
        findings,_,_=assess(before,test,np.ones_like(test),annotation,1,np.eye(3),compute)
        self.assertTrue(any(f['kind']=='pin_bridge_candidate' for f in findings));self.assertIn('difference',compute.calls);self.assertIn('sobel',compute.calls)
        test=before.copy();test[150:350,150:350]=45
        findings,_,_=assess(before,test,np.ones_like(test),annotation,1,np.eye(3),compute)
        self.assertTrue(any(f['kind']=='component_presence_candidate' for f in findings))
        self.assertTrue(all('quad_test_native' in f and 'quad_reference_native' in f for f in findings))

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(ContractTests);result=unittest.TextTestRunner(verbosity=2).run(suite)
    evidence=ROOT/'evidence/report-contract';evidence.mkdir(exist_ok=True)
    (evidence/'result.json').write_text(json.dumps(dict(passed=result.wasSuccessful(),tests=result.testsRun,physical_devices_opened=False,source_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'runtime/motion.py',ROOT/'runtime/adc_sampler.py',ROOT/'demo/runtime/scan_demo.py',Path(__file__)]}),indent=2))
    raise SystemExit(0 if result.wasSuccessful() else 1)
