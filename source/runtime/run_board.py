"""Formal source-recompute entry. No network service or PC inference is used."""
from pathlib import Path
import argparse,os,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
def main():
    if '--board-demo' in sys.argv:
        from .board_demo import main as board_demo
        return board_demo()
    if '--demo' in sys.argv:
        p=argparse.ArgumentParser(description='主程序离线功能演示，不连接任何开发板');p.add_argument('--demo',action='store_true');p.add_argument('--port',type=int,default=8698);p.add_argument('--demo-work',type=Path);p.add_argument('--no-browser',action='store_true');a=p.parse_args()
        from .demo_host import serve
        return serve(a.port,a.demo_work,not a.no_browser)
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path);p.add_argument('--bundle-index',type=Path);p.add_argument('--reference',type=Path);p.add_argument('--annotations',type=Path);p.add_argument('--calibration',type=Path);p.add_argument('--state',type=Path,default=Path('/tmp/pcb-submission'));p.add_argument('--tag',required=True);p.add_argument('--board',choices=['stm32','dcdc'],default='dcdc');p.add_argument('--live-scan',action='store_true');p.add_argument('--motion-config',type=Path);p.add_argument('--capture-live',action='store_true');p.add_argument('--rgb-device',default='/dev/video0');p.add_argument('--thermal-device',default='/dev/video1');a=p.parse_args()
    if a.live_scan and not a.motion_config:p.error('live scan requires calibrated motion configuration')
    # Fresh directory prevents accidentally reading previous per-board results.
    state=a.state/str(time.monotonic_ns())
    from .board_profiles import captures
    paths=captures(a.bundle_index)
    if a.bundle:paths[a.board]=a.bundle.resolve()
    if a.capture_live:
        from .capture_live import capture
        paths[a.board]=capture(state/'fresh',a.board,a.rgb_device,a.thermal_device,a.calibration)
    from .capture_set import prepare
    display,index=prepare(paths,state,a.board,a.reference,a.annotations,a.calibration)
    command=[sys.executable,'-m','runtime.board_demo','--board-demo','--display',str(display),'--state',str(state/'ui'),'--tag',a.tag,'--board','1' if a.board=='dcdc' else '0','--capture-index',str(index)]
    if a.live_scan:command+=['--live-scan','--motion-config',str(a.motion_config.resolve())]
    os.execv(sys.executable,command)
if __name__=='__main__':main()
