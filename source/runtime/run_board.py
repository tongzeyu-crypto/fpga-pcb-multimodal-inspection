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
    from .service import process
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);p.add_argument('--reference',type=Path);p.add_argument('--state',type=Path,default=Path('/tmp/pcb-submission'));p.add_argument('--tag',required=True);p.add_argument('--board',choices=['stm32','dcdc'],default='dcdc');a=p.parse_args()
    # Fresh directory prevents accidentally reading previous per-board results.
    state=a.state/str(time.monotonic_ns());record=process(a.bundle,state/'computed',a.reference,offline_test=False)
    cmd=[sys.executable,str(ROOT/'tools/build_display_assets.py'),'--bundle',str(a.bundle),'--output',str(state/'display'),'--processing',str(state/'computed/processing.json')]
    if a.reference:cmd+=['--reference',str(a.reference)]
    subprocess.run(cmd,check=True);binary=ROOT/'bin/hdmi_full_runtime'
    os.execv(str(binary),[str(binary),str(state/'display'),'--tag',a.tag,'--board','1' if a.board=='dcdc' else '0','--log',str(state/'display-run'),'--release-assets','0','--ai-model',str(ROOT/'models/frame/model.pai')])
if __name__=='__main__':main()
