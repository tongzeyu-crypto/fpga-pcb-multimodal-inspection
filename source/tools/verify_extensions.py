from pathlib import Path
import argparse,json,os,shutil,subprocess,hashlib
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser();p.add_argument('--vivado-bin',type=Path,required=True);p.add_argument('--work',type=Path,required=True);a=p.parse_args();a.work.mkdir(parents=True,exist_ok=True);os.environ['TEMP']=os.environ['TMP']=str(a.work);report={}
    for name,sources,marker in [('depth',[ROOT/'graphics/rtl/g3_pkg.sv',ROOT/'graphics/rtl/g3_resolve.sv',ROOT/'tests/tb_depth.sv'],'DEPTH_PASS'),('adc',[ROOT/'rtl/pcb_adc_capture.sv',ROOT/'tests/tb_adc.sv'],'ADC_PASS')]:
        dest=a.work/name;dest.mkdir(exist_ok=True)
        for src in sources:shutil.copyfile(src,dest/src.name)
        (dest/'run.tcl').write_text('run all\nquit\n');ok=False
        commands=[['xvlog.bat','--sv']+[src.name for src in sources],['xelab.bat','tb_'+name,'-s',name+'_sim','--timescale','1ns/1ps'],['xsim.bat',name+'_sim','-tclbatch','run.tcl']]
        logs=ROOT/'evidence'/('extension-'+name);logs.mkdir(exist_ok=True)
        for index,cmd in enumerate(commands):
            with (logs/(str(index)+'.log')).open('wb') as f:r=subprocess.run([str(a.vivado_bin/cmd[0])]+cmd[1:],cwd=dest,stdout=f,stderr=subprocess.STDOUT)
            if r.returncode:break
        else:ok=marker in (logs/'2.log').read_text(errors='replace')
        report[name]={'passed':ok,'board_tested':False,'last_stage':index,'source_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}
    (ROOT/'evidence/extensions.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
if __name__=='__main__':main()
