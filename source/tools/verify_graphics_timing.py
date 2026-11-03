"""Arithmetic, hazards, credit/backpressure and reset regressions for timing RTL."""
from pathlib import Path
import argparse, hashlib, json, os, shutil, subprocess, sys
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--vivado-bin',type=Path,required=True);p.add_argument('--work',type=Path,required=True);p.add_argument('--top',choices=['tb_shader_pair','tb_shader_credit','tb_shader_stream','tb_store','tb_store_stream','tb_cache_dual','tb_device_generation']);a=p.parse_args()
    a.work.mkdir(parents=True,exist_ok=True);os.environ['TEMP']=os.environ['TMP']=str(a.work)
    out=ROOT/'evidence/graphics-timing';out.mkdir(exist_ok=True)
    sys.path.insert(0,str(ROOT/'tests/graphics/reference'))
    from shader_stream_fixture import generate as shader_vectors
    from store_vectors import generate as store_vectors
    tops=['tb_shader_pair','tb_shader_credit','tb_shader_stream','tb_store','tb_store_stream','tb_cache_dual','tb_device_generation']
    if a.top:tops=[a.top]
    results={}
    source_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'graphics/rtl').glob('*.sv')}
    previous=out/'result.json'
    if a.top and previous.exists():
        old=json.loads(previous.read_text())
        if old.get('source_sha256')==source_hashes:results=old['cases']
    for top in tops:
        work=a.work/top;work.mkdir(exist_ok=True)
        shutil.copytree(ROOT/'graphics/rtl',work/'rtl',dirs_exist_ok=True)
        shutil.copytree(ROOT/'tests/graphics/sim',work/'sim',dirs_exist_ok=True)
        if top in ('tb_shader_credit','tb_shader_stream'):shader_vectors(work)
        if top=='tb_store_stream':store_vectors(work)
        if top=='tb_device_generation':
            from fixtures import generate
            count=generate(work)
            tb=work/'sim/tb_device_generation.sv'
            tb.write_text(tb.read_text().replace('FIXTURE_ROOT',work.as_posix()).replace('write_reg(12,7);',f'write_reg(12,{count});'))
        for tb in (work/'sim').glob('*.sv'):
            tb.write_text(tb.read_text().replace('$readmemh("sim/','$readmemh("'+work.as_posix()+'/sim/'))
        sources=sorted((work/'rtl').glob('*.sv'),key=lambda f:(f.name!='g3_pkg.sv',f.name))
        sources+=[work/'sim'/(top+'.sv')]
        commands=[['xvlog.bat','--sv']+[str(f) for f in sources],['xelab.bat',top,'-s','regression','--timescale','1ns/1ps'],['xsim.bat','regression','-tclbatch','run.tcl']]
        (work/'run.tcl').write_text('run all\nquit\n')
        log=b'';code=0
        for cmd in commands:
            run=subprocess.run([str(a.vivado_bin/cmd[0])]+cmd[1:],cwd=work,capture_output=True)
            log+=run.stdout+run.stderr;code=run.returncode
            if code:break
        marker=(top.upper()+'_PASS').encode()
        ok=code==0 and marker in log and b'Fatal:' not in log and b'cannot be opened for reading' not in log
        (out/(top+'.log')).write_bytes(log)
        results[top]={'passed':ok,'exit_code':code,'board_run':False}
        print(top,results[top],flush=True)
    result={'cases':results,'passed':all(v['passed'] for v in results.values()),'board_run':False,'source_sha256':source_hashes}
    (out/'result.json').write_text(json.dumps(result,indent=2))
    return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
