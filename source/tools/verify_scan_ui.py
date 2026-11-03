"""Render the real 150-point scan snapshot format without opening motion."""
from pathlib import Path
import argparse,hashlib,json,shutil,sys
import cv2,numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime.demo_integration import DemoSession
from runtime.neural_frames import NativeRenderer,read_rgb
def main():
    p=argparse.ArgumentParser();p.add_argument('--assets',type=Path,required=True);p.add_argument('--work',type=Path,required=True);a=p.parse_args();a.work.mkdir(parents=True,exist_ok=True)
    assets=a.work/'assets';shutil.copytree(a.assets,assets,dirs_exist_ok=True)
    from runtime.service import process
    bundle=ROOT/'data/raw/dcdc.bundle.json';process(bundle,a.work/'computed',offline_test=True)
    session=DemoSession(assets,a.work/'sessions',motion_config={'device':'UNOPENED-TEST-FIXTURE'},capture_bundle=bundle,processing=a.work/'computed/processing.json')
    assert len(session.route)==150 and session.motion is None
    with NativeRenderer(ROOT/'bin/demo_reference.exe',assets,a.work/'render') as engine:
        result=engine.command('app raw_board 1 mode 16 demo_point 149 cursor_visible 0')
        assert result['app']['demo_point']==149
        result=engine.command('pointer 1 1200 214 0 0')
        assert result['app']['demo_point']==0
        image=read_rgb(str(engine.prefix)+'.argb');assert image.shape==(720,1280,3)
    e=ROOT/'evidence/report-scan-ui';e.mkdir(exist_ok=True)
    (e/'scan-150.png').write_bytes(cv2.imencode('.png',image)[1].tobytes())
    (e/'result.json').write_text(json.dumps(dict(passed=True,route_points=150,last_result_selectable=True,mouse_wraps_actual_route=True,motion_adapter_constructed=False,physical_board_connected=False,source_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'runtime/display/driver/full_demo.h',ROOT/'runtime/display/driver/full_state.h',ROOT/'runtime/demo_integration.py',ROOT/'tests/reference_bridge.cpp']}),indent=2))
    print('SCAN_150_UI_PASS')
if __name__=='__main__':main()
