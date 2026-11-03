import unittest
from runtime.scan_demo import ScanScheduler,SimulatedMotion,RawReplaySampler,serpentine

class Clock:
    def __init__(self):self.now=10.
    def monotonic(self):return self.now
    def sleep(self,s):self.now+=s

class FakePl:
    def run_three(self,frames):return {'output':[1]*33,'metadata':{'window_energy_q28':64*(1<<28),'frames':3},'backend':'unit-test fixture only'}

def points():
    return [{'point_index':i,'xy_mm':[x,y],'frames':[{'samples':[0]*64,'source_sha256':str(i)} for _ in range(3)]} for i,(x,y) in enumerate([(0,0),(1,0),(2,0),(0,1),(1,1),(2,1)])]

class Tests(unittest.TestCase):
    def test_route_and_capture_after_settle(self):
        clock=Clock();sampler=RawReplaySampler();scan=ScanScheduler(SimulatedMotion(clock),sampler,FakePl(),clock,settle_s=.2)
        records=scan.run(points());self.assertEqual([r['xy_mm'] for r in records],[[0,0],[1,0],[2,0],[2,1],[1,1],[0,1]])
        self.assertEqual(sampler.calls,18)
        for record in records:
            self.assertGreaterEqual(record['settled_at']-record['arrival_confirmed_at'],.2-1e-9)
            self.assertTrue(all(f['demo_sample_begin']>=record['settled_at'] for f in record['frames']))
            self.assertTrue(all(f['source_point_index']==record['source_point_index'] for f in record['frames']))
    def rejection(self,kind):
        clock=Clock()
        class BadMotion(SimulatedMotion):
            def status(self):
                result=super().status()
                if kind=='stale':result['reported_at']-=3
                if kind=='wrong-position':result['xy_mm']=[99,99]
                if kind=='moving':result['state']='Jog'
                if kind=='no-ack':result['ack']=False
                return result
        motion=BadMotion(clock);sampler=RawReplaySampler();scan=ScanScheduler(motion,sampler,FakePl(),clock,arrival_timeout_s=.1)
        with self.assertRaises(TimeoutError):scan.run(points())
        self.assertEqual(sampler.calls,0);self.assertTrue(motion.canceled);self.assertEqual(scan.events[-1]['state'],'FAULT')
    def test_stale(self):self.rejection('stale')
    def test_wrong_position(self):self.rejection('wrong-position')
    def test_still_moving(self):self.rejection('moving')
    def test_no_ack(self):self.rejection('no-ack')
if __name__=='__main__':unittest.main()
