"""Actual AXI regression for every new PL operator specified by 技术文档2."""
from pathlib import Path
import argparse,hashlib,json,math,os,random,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT.parent))
from demo.runtime.fixed_reference import spectrum
from demo.runtime.report_reference import image_words,psd_q40,band_rms_q16,decode_adc_words
from runtime.numerics import read_adc

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--vivado-bin',type=Path,required=True);ap.add_argument('--work',type=Path,required=True);a=ap.parse_args();a.work.mkdir(parents=True,exist_ok=True)
    commands=[];generation=0;jobs=[];rng=random.Random(702003)
    def cmd(op,address=0,data=0):commands.append([op,address,int(data)&0xffffffff]);return len(commands)-1
    def wr(ad,v):return cmd(1,ad,v)
    def check(ad,v):return cmd(2,ad,v)
    def run(name,task,values,expected,*,mode=0,config=None,physical_values=True,count=None):
        nonlocal generation
        config=config or {};wr(12,task);wr(16,count or len(values));wr(24,mode);wr(20,config.get('threshold',30));wr(96,config.get('normalizer',1));wr(100,config.get('low',0));wr(104,config.get('high',100000));wr(72,config.get('offset',0))
        if physical_values:
            for i,v in enumerate(values):wr(0x1000+4*i,v)
        wr(0,1);cmd(3);generation+=1;check(52,generation);check(92,len(expected));reads=[]
        for i,v in enumerate(expected):reads.append((check(0x8000+8*i,v),check(0x8004+8*i,(v&((1<<64)-1))>>32)))
        jobs.append(dict(name=name,task=task,output_reads=reads,expected=expected,config=config,mode=mode))
    check(8,0x50445033);check(56,4096)
    for n in (64,4096):
        accumulated=[0]*(n//2+1)
        for frame in range(3):
            values=[round(100+1700*math.sin(2*math.pi*5*k/n+frame*.1)) for k in range(n)]
            power,energy=spectrum(values);accumulated=[x+y for x,y in zip(accumulated,power)]
            run('fft-%d-%d'%(n,frame),1,values,accumulated,mode=1 if frame==0 else 3)
        bands=[(0,n//2+1),(1,n//4),(n//4,n//2),(2,2)]
        wr(84,50000000);wr(88,len(bands))
        for i,(lo,hi) in enumerate(bands):wr(0x100+8*i,lo);wr(0x104+8*i,hi)
        psd=psd_q40(accumulated,n,energy,3,50000000);run('PL-PSD-and-RMS-%d'%n,5,[],psd,physical_values=False,count=n)
        for i,v in enumerate(band_rms_q16(psd,n,50000000,bands)):check(0x180+4*i,v)
    words=read_adc(ROOT.parent/'data/raw/dcdc-adc/points/point-00000/capture_00.csv').tolist();expected=decode_adc_words(words)
    for start in range(0,16384,4096):run('raw-extraction-%d'%start,4,words[start:start+4096],expected[start:start+4096],mode=2 if start else 0,config={'offset':start})
    check(108,16384)
    for i in range(4):check(112+4*i,4096)
    resize=[]
    for _ in range(400):resize += [rng.randrange(-30000,50000) for _ in range(4)]+[rng.randrange(4096)|(rng.randrange(4096)<<16)]
    run('bilinear-resize',6,resize,image_words(6,resize))
    for mode in range(6):
        width=25 if mode>=4 else 9;values=[rng.randrange(256) for _ in range(width*120)]
        run('neighborhood-%d'%mode,7,values,image_words(7,values,mode),mode=mode)
    for den in (1,127,10000,0xffffffff):
        values=[0,1,2,126,127,128,9999,10000,10001,123456,0x7fffffff]
        run('normalization-%d'%den,8,values,image_words(8,values,normalizer=den),config={'normalizer':den})
    values=[]
    for _ in range(400):values += [rng.randrange(-10000,10000),rng.randrange(-10000,10000),rng.randrange(2)]
    run('difference-threshold-valid',9,values,image_words(9,values,threshold=300),config={'threshold':300})
    values=[-10000,0,1,25000,39999,40000,100000]+[rng.randrange(100000) for _ in range(300)]
    run('pseudocolor',10,values,image_words(10,values,low=0,high=40000),config={'low':0,'high':40000})
    run('pseudocolor-flat-range',10,[12345]*5,image_words(10,[12345]*5,low=12345,high=12345),config={'low':12345,'high':12345})
    # Malformed raw transport must fail, and abort must not advance generation.
    for kind in ('marker','heartbeat','overrange','endpoint'):
        v=words[:16];bad=next(i for i in range(4,16) if ((v[i]>>15)&3)==1);v[bad]=v[bad]&~(1<<19) if kind=='marker' else v[bad]^(1<<20) if kind=='heartbeat' else v[bad]|(1<<14) if kind=='overrange' else (v[bad]&~16383)|8191
        wr(0,2);wr(12,4);wr(16,len(v));wr(24,0);wr(72,0)
        for i,x in enumerate(v):wr(0x1000+i*4,x)
        wr(0,1);cmd(4,0,200);check(4,6);generation+=1;check(52,generation)
    wr(0,2);wr(12,8);wr(16,1);wr(96,0);wr(0,1);check(4,4);check(52,generation)
    for p in (ROOT/'rtl').glob('*.sv'):shutil.copyfile(p,a.work/p.name)
    shutil.copyfile(ROOT/'tests/tb_demo.sv',a.work/'tb_demo.sv');(a.work/'commands.mem').write_text('\n'.join(f'{v:08x}' for row in commands for v in row)+'\n');(a.work/'fixture_count.svh').write_text('localparam integer TOTAL=%d;\n'%len(commands));(a.work/'run.tcl').write_text('run all\nquit\n')
    log=b''
    for command in [['xvlog.bat','--sv','pcb_scalar.sv','pcb_demo_coeff.sv','pcb_demo_core.sv','pcb_demo_axi.sv','tb_demo.sv'],['xelab.bat','tb_demo','-s','report','--timescale','1ns/1ps'],['xsim.bat','report','-tclbatch','run.tcl']]:
        result=subprocess.run([str(a.vivado_bin/command[0])]+command[1:],cwd=a.work,capture_output=True);log+=result.stdout+result.stderr
        if result.returncode:break
    dest=ROOT/'evidence';(dest/'report-pipeline.log').write_bytes(log);passed=result.returncode==0 and b'PL_PS_DEMO_RTL_PASS' in log and b'Fatal:' not in log
    report=dict(passed=passed,job_count=len(jobs),checked_output_elements=sum(len(j['expected']) for j in jobs),fixture_commands=len(commands),board_tested=False,source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'rtl').glob('*.sv')})
    if passed:
        actual={int(l.split()[0],16):int(l.split()[1],16) for l in (a.work/'actual.txt').read_text().splitlines()}
        for job in jobs:
            values=[actual[lo]|(actual[hi]<<32) for lo,hi in job['output_reads']]
            if job['task'] not in (1,5):values=[v-(1<<64) if v>=1<<63 else v for v in values]
            assert values==job['expected']
    (dest/'report-pipeline.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2));return 0 if passed else 1
if __name__=='__main__':raise SystemExit(main())
