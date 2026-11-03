from pathlib import Path
import copy,hashlib,json,sys,tempfile,unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime.capture_bundle import load,Session,MissingInput
from runtime.numerics import thermal_decode,read_adc,adc_decode,periodogram
from runtime.frame_synthesis import FrameGate
from runtime.registration import query_temperature
from runtime.pl_backend import infer
class RuntimeChecks(unittest.TestCase):
    def setUp(self):self.path=ROOT/'data/raw/dcdc.bundle.json';self.b=json.loads(self.path.read_text())
    def test_real_manifest(self):self.assertEqual(len(load(self.path,'dcdc')['raw']['adc']),450)
    def test_switch_clears_all_derived_and_frames(self):
        s=Session();s.select('dcdc');s.attach(self.path);s.derived['temperature']='test';s.render_history.append('test');s.select('stm32');self.assertEqual(s.derived,{});self.assertEqual(s.render_history,[])
        with self.assertRaises(MissingInput):s.measurement('rgb')
        with self.assertRaises(ValueError):s.attach(self.path)
    def test_external_windows_test_rejected(self):
        b=copy.deepcopy(self.b);b['raw']['rgb'][0]['source']='WINDOWS_USB_DIRECT'
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.json';p.write_text(json.dumps(b))
            with self.assertRaisesRegex(ValueError,'non-Zynq'):load(p)
    def test_path_and_hash_rejected(self):
        for field,value in [('path','../escape.jpg'),('sha256','0'*64)]:
            b=copy.deepcopy(self.b);b['raw']['rgb'][0][field]=value
            # Same directory preserves relative source lookup; remove test manifest afterwards.
            p=self.path.parent/'invalid-test-only.bundle.json'
            try:
                p.write_text(json.dumps(b))
                with self.assertRaises(ValueError):load(p)
            finally:p.unlink(missing_ok=True)
    def test_thermal_inverse_queries_original_matrix(self):
        _,temp=thermal_decode((self.path.parent/self.b['raw']['thermal'][0]['path']).read_bytes());mat=np.array([[2.,0,10],[0,3.,20],[0,0,1]])
        q=query_temperature(temp,mat,[10+2*111,20+3*84]);self.assertEqual(q['temperature_c'],float(temp[84,111]));self.assertEqual(q['raw_thermal_xy'],[111,84]);self.assertIsNone(query_temperature(temp,mat,[-1000,-1000]))
    def test_adc_integrity_and_frequency_preservation(self):
        path=self.path.parent/self.b['raw']['adc'][0]['path'];raw=read_adc(path);x=adc_decode(raw);self.assertEqual(x.shape,(2,4096));p=periodogram(x);self.assertEqual(p.shape,(2,2049));self.assertGreater(p[:,-20:].sum(),0)
        bad=raw.copy();bad[6]^=1<<20
        with self.assertRaises(ValueError):adc_decode(bad)
    def test_no_silent_pc_inference(self):
        import platform
        if platform.system()=='Windows':
            with self.assertRaisesRegex(RuntimeError,'board Linux'):infer('registration',np.zeros((2,48,64),np.float32))
    def test_single_insert_and_invalidation(self):
        gate=FrameGate();self.assertFalse(gate.allow('capture-A',0,.01,1,.99));self.assertTrue(gate.allow('capture-A',0,.01,1,.99));self.assertFalse(gate.allow('capture-A',0,.01,1,.99));self.assertFalse(gate.allow('capture-A',0,.01,1,.99))
        gate.real_frame('capture-A');self.assertFalse(gate.allow('capture-A',12,.01,1,.99));self.assertFalse(gate.allow('capture-B',0,.01,1,.99));self.assertFalse(gate.allow('capture-B',0,.1,1,.99));self.assertFalse(gate.allow('capture-B',0,.01,.8,.99));self.assertFalse(gate.allow('capture-B',0,.01,1,.2))
    def test_aoi_self_comparison_is_only_no_change_regression(self):
        from runtime.aoi_rules import detect
        raw=(self.path.parent/self.b['raw']['rgb'][0]['path']).read_bytes();r=detect(raw,raw);self.assertEqual(r['regions'],[]);self.assertFalse(r['internal_solder_joints_tested']);self.assertFalse(r['electrical_continuity_tested'])
if __name__=='__main__':unittest.main(verbosity=2)
