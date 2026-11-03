from pathlib import Path
import argparse,json,subprocess,shutil
import numpy as np
import cv2
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser();p.add_argument('--cxx',type=Path,required=True);p.add_argument('--work',type=Path,required=True);a=p.parse_args();e=ROOT/'evidence/native-frame';e.mkdir(exist_ok=True)
    shutil.copytree(ROOT/'runtime/display',a.work/'src',dirs_exist_ok=True);shutil.copyfile(ROOT/'runtime/pcb_ai.cpp',a.work/'pcb_ai.cpp');shutil.copyfile(ROOT/'tests/native_frame_test.cpp',a.work/'native_frame_test.cpp')
    exe=a.work/'native_frame_test.exe';r=subprocess.run([str(a.cxx),'-std=c++14','-O2','-static',str(a.work/'native_frame_test.cpp'),'-o',str(exe)],capture_output=True);(e/'build.log').write_bytes(r.stdout+r.stderr)
    if r.returncode:raise RuntimeError('native frame helper compile')
    prefix=a.work/'frame';proc=subprocess.Popen([str(a.work/'reference.exe'),str(a.work/'assets'),str(prefix)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=(e/'reference-stderr.log').open('wb'),text=True,encoding='utf8')
    cases=[]
    for mode in [0,3]:
        for pose,yaw in [('source',.55),('target',.5575)]:
            proc.stdin.write(f'app raw_board 1 mode {mode} hud 0 cursor_visible 0 yaw {yaw} polar .9 base 1\n');proc.stdin.flush();record=json.loads(proc.stdout.readline())
            if 'error'in record:raise RuntimeError(record['error'])
            for suffix in ['.argb','.depth.u16','.u16','.matrix']:shutil.copyfile(str(prefix)+suffix,str(a.work/pose)+suffix)
        output=a.work/'synthetic.argb';r=subprocess.run([str(exe),str(ROOT/'models/frame/model.pai'),str(a.work/'source'),str(a.work/'target'),str(output),'1'],capture_output=True)
        (e/(f'mode-{mode}.log')).write_bytes(r.stdout+r.stderr)
        if r.returncode:raise RuntimeError('native frame inference failed')
        record=json.loads(r.stdout)
        if not record['accepted'] or record['neural_changed_pixels']<=0:raise RuntimeError('native neural frame did not generate pixels')
        truth=np.fromfile(str(a.work/'target')+'.argb',np.uint8).reshape(720,1280,4);warp=np.fromfile(output,np.uint8).reshape(720,1280,4);ids=np.fromfile(str(a.work/'target')+'.u16',np.uint16).reshape(720,1280);dep=np.fromfile(str(a.work/'target')+'.depth.u16',np.uint16).reshape(720,1280);mask=(ids<64000)&(dep<65535);err=np.abs(warp[...,:3].astype(float)-truth[...,:3]).mean(2)
        record.update(mode=mode,resolution=[1280,720],truth='complete fixed-point FullReference renderer, retained prebuilt mesh or real ADC terrain',full_frame_mae=float(err.mean()),geometry_mae=float(err[mask].mean()),geometry_error_p95=float(np.percentile(err[mask],95)),physical_board_tested=False,board_speedup=None)
        for name,im in [('truth',truth),('reprojected',warp),('error',np.clip(err*5,0,255).astype(np.uint8))]:(e/f'mode-{mode}-{name}.png').write_bytes(cv2.imencode('.png',im)[1].tobytes())
        cases.append(record)
    proc.stdin.close();proc.wait(timeout=10);(e/'result.json').write_text(json.dumps({'cases':cases,'backend':'explicit C++ offline INT8 reference; same layers submitted to PL in production','gui_source_adapter_present':True,'board_verified':False},indent=2));print(json.dumps(cases,indent=2))
if __name__=='__main__':main()
