"""Render all 16 board/page states using the retained fixed-point CPU reference."""
from pathlib import Path
import argparse,gzip,json,os,shutil,subprocess,sys,hashlib
import numpy as np
import cv2
ROOT=Path(__file__).resolve().parents[1]
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--cxx',type=Path,required=True);ap.add_argument('--work',type=Path,required=True);ap.add_argument('--assets',type=Path,required=True);a=ap.parse_args();a.work.mkdir(parents=True,exist_ok=True)
    assets=a.work/'assets'
    for p in a.assets.rglob('*'):
        if not p.is_file():continue
        q=assets/p.relative_to(a.assets);q.parent.mkdir(parents=True,exist_ok=True)
        if p.suffix=='.gz':q.with_suffix('').write_bytes(gzip.decompress(p.read_bytes()))
        else:shutil.copyfile(p,q)
    runtime=(ROOT/'runtime/display/driver/gfx3_runtime.cpp').read_text(encoding='utf8')
    generated=runtime[runtime.index('static void full_input_locked('):runtime.index('#include "full_mouse.h"')]+"\n"+runtime[runtime.index('static std::string full_app_json('):runtime.index('#include "bounded_workers.h"')]
    (a.work/'reference-generated.h').write_text(generated,encoding='utf8')
    s=(ROOT/'tests/reference_bridge.cpp').read_text(encoding='utf8')
    s=s.replace('FullReference renderer(argv[1]);','FullReference renderer(argv[1]);for(int bi=0;bi<2;bi++){auto &sc=*full_for(bi);View check;full_action(check,"raw_board",bi,sc.points.size());for(int mode:{0,1,3,6,12,13,14,15}){check.mode=mode;FullDraw ui(sc.glyphs);sc.hud(ui,check,"offline-layer",0,false);}if((sc.available_modalities&4)&&sc.xs.size()>1&&sc.ys.size()>1){for(size_t i=0;i<sc.points.size();i++){double u=(sc.points[i].x-sc.xs.front())/(sc.xs.back()-sc.xs.front()),v=(sc.points[i].y-sc.ys.front())/(sc.ys.back()-sc.ys.front());if(std::abs(sc.interp(sc.powers,u,v)-sc.powers[i])>std::max(1e-9,std::abs(sc.powers[i])*1e-6))throw std::runtime_error("mechanical node interpolation mismatch");}}}')
    # Legacy MinGW cannot parse UTF-8 non-ASCII names inside #include strings.
    # Stage the same headers under a short ASCII development directory.
    shutil.copytree(ROOT/'runtime/display',a.work/'src',dirs_exist_ok=True)
    (a.work/'reference.cpp').write_text(s,encoding='utf8');exe=a.work/'reference.exe'
    r=subprocess.run([str(a.cxx),'-std=c++14','-O2','-static','-finput-charset=UTF-8','-fexec-charset=UTF-8','-I',str(a.work),str(a.work/'reference.cpp'),'-o',str(exe)],capture_output=True)
    e=ROOT/'evidence/display';e.mkdir(exist_ok=True);(e/'build.log').write_bytes(r.stdout+r.stderr)
    if r.returncode:raise RuntimeError('reference compile failed')
    prefix=a.work/'frame';proc=subprocess.Popen([str(exe),str(assets),str(prefix)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=(e/'stderr.log').open('wb'),text=True,encoding='utf8')
    cases=[]
    for board in [1,0,1]:
        for mode in [0,1,3,6,12,13,14,15]:
            proc.stdin.write(f'app raw_board {board} mode {mode}\n');proc.stdin.flush();line=proc.stdout.readline();result=json.loads(line)
            if 'error'in result:raise RuntimeError(line)
            pixels=np.fromfile(str(prefix)+'.argb',np.uint8).reshape(720,1280,4)
            name=f'{"dcdc" if board else "stm32"}-mode-{mode}'
            if len(cases)<16:(e/(name+'.png')).write_bytes(cv2.imencode('.png',pixels)[1].tobytes())
            cases.append({'board':board,'mode':mode,'command_count':result['command_count'],'pixel_sha256':hashlib.sha256(pixels.tobytes()).hexdigest(),'offline_reference':True,'resolution':[1280,720],'frame_state':result['app']})
    for i in range(8):
        if cases[i]['pixel_sha256']!=cases[16+i]['pixel_sha256']:raise RuntimeError('board switch failed to restore exact same capture view')
        if cases[i]['pixel_sha256']==cases[8+i]['pixel_sha256']:raise RuntimeError('cross-board stale pixels')
    # Mouse hit tests and board-switch data isolation (last transition returns DC).
    for command in ['pointer 0 30 100 0 0','pointer 1 30 100 0 0','pointer 0 1120 20 0 0','pointer 1 1120 20 0 0']:
        proc.stdin.write(command+'\n');proc.stdin.flush();line=proc.stdout.readline()
        if 'error'in json.loads(line):raise RuntimeError(line)
    proc.stdin.close();proc.wait(timeout=10)
    # A contact sheet is for visual QA only; no runtime consumes these images.
    imgs=[]
    for board in ['dcdc','stm32']:
        row=[]
        for mode in [0,1,3,6,12,13,14,15]:
            im=cv2.imdecode(np.fromfile(e/f'{board}-mode-{mode}.png',np.uint8),cv2.IMREAD_COLOR);im=cv2.resize(im,(384,216));cv2.putText(im,f'{board} / {mode}',(10,208),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,255,255),1);row.append(im)
        imgs.extend([np.concatenate(row[:4],1),np.concatenate(row[4:],1)])
    (e/'contact-sheet.png').write_bytes(cv2.imencode('.png',np.concatenate(imgs,0))[1].tobytes())
    (e/'result.json').write_text(json.dumps({'cases':cases,'passed':True,'hardware_or_physical_display':False,'board_switch_sequence':['dcdc','stm32','dcdc'],'mouse_hit_testing':'offline reference only'},indent=2));print('display regression passed',len(cases),'states')
if __name__=='__main__':main()
