"""Cross compile and host-verify without running anything on a board."""
from pathlib import Path
import argparse,hashlib,json,subprocess,sys,shutil,tempfile
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser();p.add_argument('--cxx',type=Path,required=True);p.add_argument('--host-cxx',type=Path);p.add_argument('--work',type=Path);a=p.parse_args();out=ROOT/'bin';out.mkdir(exist_ok=True);e=ROOT/'evidence/arm';e.mkdir(exist_ok=True);results={};work=Path(a.work or tempfile.mkdtemp(prefix='pcb-arm-'));work.mkdir(parents=True,exist_ok=True);shutil.copytree(ROOT/'runtime',work/'runtime',dirs_exist_ok=True);staged=work/'bin';staged.mkdir(exist_ok=True)
    for name,src,flags in [('pl_demo',ROOT/'runtime/pl_compute.cpp',[]),('pl_image',ROOT/'runtime/pl_image.cpp',[]),('pcb_ai',ROOT/'runtime/pcb_ai.cpp',[]),('pcb_adc',ROOT/'runtime/pcb_adc.cpp',[]),('camera_stream',ROOT/'runtime/camera_stream.c',[]),('camera_capture',ROOT/'runtime/camera_capture.c',[]),('grbl_control',ROOT/'runtime/grbl_control.c',['-lm']),('hdmi_full_runtime',ROOT/'runtime/display/driver/gfx3_runtime.cpp',['-pthread','-ldl'])]:
        original=src;src=work/src.relative_to(ROOT)
        cmd=[str(a.cxx),'-std=c++14','-O2','-Wall','-Wextra','-Wno-misleading-indentation','-Wno-psabi','-mcpu=cortex-a9','-mfpu=neon','-mfloat-abi=hard',str(src),'-o',str(staged/name)]+flags
        if src.suffix=='.c':cmd[1:2]=['-x','c','-std=c11']
        r=subprocess.run(cmd,capture_output=True);(e/(name+'.log')).write_bytes(r.stdout+r.stderr);results[name]={'exit_code':r.returncode,'sha256':hashlib.sha256((staged/name).read_bytes()).hexdigest() if r.returncode==0 else None,'board_executed':False}
        if r.returncode==0:
            shutil.copyfile(staged/name,out/name)
            results[name]['sha256']=hashlib.sha256((out/name).read_bytes()).hexdigest()
            elf=(out/name).read_bytes();valid=elf[:6]==b'\x7fELF\x01\x01' and elf[18:20]==b'\x28\x00';results[name]['elf32_little_endian_arm']=valid
            if not valid:results[name]['exit_code']=1
    if a.host_cxx:
        host=staged/'pcb_ai_offline.exe';r=subprocess.run([str(a.host_cxx),'-std=c++14','-O2','-static',str(work/'runtime/pcb_ai.cpp'),'-o',str(host)],capture_output=True);(e/'host-ai.log').write_bytes(r.stdout+r.stderr);results['host_ai_build']=r.returncode
        if r.returncode==0:
            sys.path.insert(0,str(ROOT));import numpy as np
            from runtime.integer_reference import run_model
            for task in ['registration','frame']:
                d=work/'models'/task;shutil.copytree(ROOT/'models'/task,d,dirs_exist_ok=True);r=subprocess.run([str(host),'--'+task,str(d/'model.pai'),str(d/'test-input.i8'),str(work/(task+'.i8')),'--offline-test'],capture_output=True);(e/('host-'+task+'.log')).write_bytes(r.stdout+r.stderr)
                desc=json.loads((d/'model.json').read_text());x=np.fromfile(d/'test-input.i8',np.int8).reshape(desc['input_shape']);expected=run_model(d,x)[-1].tobytes();results['host_'+task]={'exit_code':r.returncode,'integer_equal':r.returncode==0 and (work/(task+'.i8')).read_bytes()==expected}
    if a.host_cxx and host.exists():shutil.copyfile(host,out/'pcb_ai_offline.exe')
    results['source_sha256']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'runtime').rglob('*') if p.suffix in {'.c','.cpp','.h','.py'}}
    (e/'result.json').write_text(json.dumps(results,indent=2));print(json.dumps({k:v for k,v in results.items() if k!='source_sha256'},indent=2))
    return int(any(v['exit_code'] for v in results.values() if isinstance(v,dict) and 'exit_code'in v))
if __name__=='__main__':raise SystemExit(main())
