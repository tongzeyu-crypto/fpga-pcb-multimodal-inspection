"""Run actual AXI RTL and export its checked return values for PS replay."""
from pathlib import Path
import argparse,hashlib,json,math,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime.reference import spectrum,thermal,preprocess

def key(task,values,config):
    return hashlib.sha256(json.dumps([task,values,config],separators=(',',':')).encode()).hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--vivado-bin',type=Path,required=True);p.add_argument('--work',type=Path,required=True);a=p.parse_args();a.work.mkdir(parents=True,exist_ok=True)
    os.environ['TEMP']=os.environ['TMP']=str(a.work);fixture=json.loads((ROOT/'inputs/demo-inputs.json').read_text());commands=[];jobs=[];generation=0
    def cmd(op,address=0,data=0):commands.append([op,address,int(data)&0xffffffff]);return len(commands)-1
    def wr(address,data):return cmd(1,address,data)
    def check(address,data):return cmd(2,address,data)
    check(8,0x50445031);check(4,0)
    def job(name,task,values,config=None):
        nonlocal generation
        config=config or {};wr(0,2);wr(12,task);wr(16,len(values));wr(20,config.get('threshold_mc',40000));wr(24,config.get('mode',0));wr(28,config.get('base',4370));wr(32,config.get('shift',2))
        for i,value in enumerate(values):wr(0x1000+4*i,value)
        wr(0,1);cmd(3);generation+=1;check(52,generation)
        if task==1:expected=spectrum(values);statistics={}
        elif task==2:expected,statistics=thermal(values,config.get('threshold_mc',40000))
        else:expected=preprocess(values,config.get('mode',0),config.get('base',4370),config.get('shift',2));statistics={}
        reads=[check(0x2000+4*i,v) for i,v in enumerate(expected)]
        stats_reads={name:check(address,statistics[name]) for name,address in [('min_mc',36),('max_mc',40),('max_index',44),('hot_count',48)]} if statistics else {}
        jobs.append({'name':name,'key':key(task,values,config),'task':task,'config':config,'output_reads':reads,'statistics_reads':stats_reads,'expected':expected})
    job('known-tone-bin5',1,[round(100+1000*math.sin(2*math.pi*5*n/64)) for n in range(64)])
    job('constant-after-mean-removal',1,[777]*64)
    job('adc14-boundaries',1,[-8192,8191]*32)
    for point in fixture['points']:
        for n,frame in enumerate(point['frames']):job(f"point-{point['point_index']}-frame-{n}",1,frame['samples'])
    job('thermal-real',2,fixture['thermal']['raw_kelvin16'])
    job('thermal-boundaries',2,[0,1,4370,4371,4770,5011,65535],{'threshold_mc':25000})
    job('rgb-real',3,fixture['rgb']['rgb888'])
    job('rgb-boundaries',3,[0,0xff0000,0xff00,0xff,0xffffff])
    job('thermal-preprocess-real',3,fixture['thermal']['raw_kelvin16'],{'mode':1})
    job('thermal-preprocess-boundaries',3,[0,4369,4370,4373,4374,5390,65535],{'mode':1})
    # Invalid commands and an abort must never advance generation or leak done.
    wr(0,2);wr(12,99);wr(0,1);check(4,4);check(52,generation)
    wr(0,2);wr(12,1);wr(16,64);wr(0,1);cmd(4,0,5);check(4,1);wr(0,2);check(4,0);check(52,generation)
    wr(12,2);wr(16,0);wr(0,1);check(4,4);cmd(5);check(4,0);check(52,0)
    for source in (ROOT/'rtl').iterdir():shutil.copyfile(source,a.work/source.name)
    shutil.copyfile(ROOT/'tests/tb_demo.sv',a.work/'tb_demo.sv')
    (a.work/'commands.mem').write_text('\n'.join(f'{v:08x}' for row in commands for v in row)+'\n')
    (a.work/'fixture_count.svh').write_text(f'localparam integer TOTAL={len(commands)};\n')
    (a.work/'run.tcl').write_text('run all\nquit\n')
    log=b''
    for command in [['xvlog.bat','--sv','pcb_demo_core.sv','pcb_demo_axi.sv','tb_demo.sv'],['xelab.bat','tb_demo','-s','demo','--timescale','1ns/1ps'],['xsim.bat','demo','-tclbatch','run.tcl']]:
        r=subprocess.run([str(a.vivado_bin/command[0])]+command[1:],cwd=a.work,capture_output=True);log+=r.stdout+r.stderr
        if r.returncode:break
    (ROOT/'evidence/rtl.log').write_bytes(log)
    passed=r.returncode==0 and b'PL_PS_DEMO_RTL_PASS' in log and b'Fatal:' not in log
    result={'passed':passed,'job_count':len(jobs),'checked_output_elements':sum(len(j['expected']) for j in jobs),'board_connected':False,'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'rtl').iterdir()}}
    if passed:
        actual={int(line.split()[0],16):int(line.split()[1],16) for line in (a.work/'actual.txt').read_text().splitlines()}
        returned=[]
        for job_info in jobs:
            def signed(v):return v-2**32 if v>=2**31 else v
            values=[actual[n] if job_info['task']==1 else signed(actual[n]) for n in job_info['output_reads']]
            if values!=job_info['expected']:raise ValueError('Independent extraction mismatch')
            stats={name:signed(actual[n]) for name,n in job_info['statistics_reads'].items()}
            returned.append({'name':job_info['name'],'key':job_info['key'],'task':job_info['task'],'output':values,'statistics':stats})
        (ROOT/'evidence/rtl-results.json').write_text(json.dumps({'backend':'XSim AXI transaction results','source_sha256':result['source_sha256'],'jobs':returned},indent=2))
    (ROOT/'evidence/rtl-verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2));return 0 if passed else 1
if __name__=='__main__':raise SystemExit(main())
