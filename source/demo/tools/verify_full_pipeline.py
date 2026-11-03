"""Execute AXI transactions against PDP3 RTL, including full-sized source data."""
from pathlib import Path
import argparse,hashlib,json,math,os,random,shutil,struct,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT.parent))
from demo.runtime.fixed_reference import spectrum,psd
from demo.runtime.reference import thermal,preprocess

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--vivado-bin',type=Path,required=True);ap.add_argument('--work',type=Path,required=True);a=ap.parse_args()
    a.work.mkdir(parents=True,exist_ok=True);os.environ['TEMP']=os.environ['TMP']=str(a.work)
    commands=[];jobs=[];generation=0;acc=[];frames=0;stats=None;errors=[]
    input_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'inputs').glob('*.json')}
    def cmd(op,address=0,data=0):commands.append([op,address,int(data)&0xffffffff]);return len(commands)-1
    def wr(ad,v):return cmd(1,ad,v)
    def check(ad,v):return cmd(2,ad,v)
    def job(name,task,values,config=None,record=True):
        nonlocal generation,acc,frames,stats
        config=config or {};mode=config.get('mode',1 if task==1 else 0)
        wr(12,task);wr(16,len(values));wr(20,config.get('threshold_mc',40000));wr(24,mode);wr(28,config.get('base',4370));wr(32,config.get('shift',2));wr(72,config.get('offset',0))
        for i,x in enumerate(values):wr(0x1000+4*i,x)
        wr(0,1);cmd(3);generation+=1;check(52,generation)
        if task==1:
            output,energy=spectrum(values,bool(mode&1));acc=[x+y for x,y in zip(acc,output)] if mode&2 else output;frames=frames+1 if mode&2 else 1
            output=acc[:];check(60,frames);check(64,energy&0xffffffff);check(68,energy>>32);statistics={}
        elif task==2:
            output,current=thermal(values,config.get('threshold_mc',40000));current['max_index']+=config.get('offset',0)
            if mode&2:
                current=dict(min_mc=min(stats['min_mc'],current['min_mc']),max_mc=max(stats['max_mc'],current['max_mc']),max_index=current['max_index'] if current['max_mc']>stats['max_mc'] else stats['max_index'],hot_count=stats['hot_count']+current['hot_count'])
            stats=statistics=current
            check(76,config.get('offset',0)+len(values))
        else:
            output=preprocess(values,mode,config.get('base',4370),config.get('shift',2));statistics={}
        reads=[]
        for i,x in enumerate(output):reads.append((check(0x8000+8*i,x),check(0x8004+8*i,(x&((1<<64)-1))>>32)))
        sr={k:check(ad,statistics[k]) for k,ad in [('min_mc',36),('max_mc',40),('max_index',44),('hot_count',48)]} if statistics else {}
        key=hashlib.sha256(json.dumps([task,values,config],separators=(',',':')).encode()).hexdigest()
        metadata=dict(frames=frames,length=len(values),window_energy_q28=energy) if task==1 else {}
        jobs.append(dict(name=name,key=key,task=task,output_reads=reads,stats_reads=sr,expected=output,config=config,record=record,metadata=metadata))
        return output
    check(8,0x50445033);check(56,4096);check(4,0)
    fixtures=json.loads((ROOT/'inputs/demo-inputs.json').read_text())
    for p in fixtures['points']:
        for n,f in enumerate(p['frames']):job('ui-point-%s-%s'%(p['point_index'],n),1,f['samples'])
    full=json.loads((ROOT/'inputs/full-inputs.json').read_text())
    for p in full['points']:
        for n,f in enumerate(p['frames']):job('full-ui-point-%s-%s'%(p['point_index'],n),1,f['samples'],{} if n==0 else {'mode':3})
    job('ui-thermal',2,fixtures['thermal']['raw_kelvin16'])
    job('ui-rgb',3,fixtures['rgb']['rgb888'])
    job('ui-thermal-quant',3,fixtures['thermal']['raw_kelvin16'],{'mode':1})
    rng=random.Random(7020)
    for n in (64,128,256,512,1024,2048,4096):
        job('fft-length-%d'%n,1,[rng.randrange(-8192,8192) for _ in range(n)],{'mode':0})
    job('fft-constant-4096',1,[777]*4096)
    job('fft-constant-adc-max',1,[8191]*4096)
    job('fft-constant-adc-min',1,[-8192]*4096)
    job('fft-adc14-extremes',1,[-8192,8191]*2048)
    for frame in range(3):
        x=[round(123+3000*math.sin(2*math.pi*317*k/4096)+200*math.cos(2*math.pi*57*k/4096+frame)) for k in range(4096)]
        power=job('fft-4096-hann-accum-%d'%frame,1,x,{'mode':1 if frame==0 else 3})
    # Independent floating-point quality check, in addition to exact RTL equality.
    import numpy as np
    from runtime.numerics import adc_decode,read_adc,periodogram
    total=np.zeros(2049);exact=[]
    for frame in range(3):
        x=np.array([round(123+3000*math.sin(2*math.pi*317*k/4096)+200*math.cos(2*math.pi*57*k/4096+frame)) for k in range(4096)])
        total+=periodogram(x)/3
    actual=np.array(psd(power,4096,spectrum(x.tolist())[1],3,50_000_000))
    errors.append(dict(name='three-tone-frames',relative_l2=float(np.linalg.norm(actual-total)/np.linalg.norm(total)),relative_energy=float(abs(actual.sum()-total.sum())/total.sum())))
    source_files=sorted((ROOT.parent/'data/raw/dcdc-adc/points/point-00000').glob('capture_*.csv'))
    if len(source_files)!=3:raise ValueError('full source ADC frames missing')
    for channel in range(2):
        floats=[]
        for frame,path in enumerate(source_files):
            x=adc_decode(read_adc(path))[channel];floats.append(periodogram(x))
            power=job('source-adc-channel-%d-frame-%d'%(channel,frame),1,x.tolist(),{'mode':1 if frame==0 else 3})
        expected=np.mean(floats,axis=0);actual=np.array(psd(power,4096,spectrum(x.tolist())[1],3,50_000_000))
        errors.append(dict(name='source-adc-channel-%d'%channel,relative_l2=float(np.linalg.norm(actual-expected)/np.linalg.norm(expected)),relative_energy=float(abs(actual.sum()-expected.sum())/expected.sum())))
    raw=(ROOT.parent/'data/raw/dcdc-rgb-thermal/thermal.raw').read_bytes();pixels=list(struct.unpack('<49152H',raw[98304:]))
    for start in range(0,len(pixels),4096):job('full-thermal-%d'%start,2,pixels[start:start+4096],{'mode':0 if start==0 else 2,'offset':start})
    for start in range(0,len(pixels),4096):job('full-thermal-quant-%d'%start,3,pixels[start:start+4096],{'mode':1})
    rgb=full['rgb']['rgb888']
    for start in range(0,len(rgb),4096):job('full-rgb-quant-%d'%start,3,rgb[start:start+4096])
    job('pixel-boundaries',2,[0,1,4370,4371,65535],{'threshold_mc':25000})
    job('rgb-boundaries',3,[0,0xff0000,0xff00,0xff,0xffffff])
    job('gray-u8-boundaries',3,[0,0xff0000,0xff00,0xff,0xffffff],{'mode':2})
    job('thermal-quant-boundaries',3,[0,4369,4370,4373,4374,5390,65535],{'mode':1})
    # Invalid operation/length, stale accumulation and abort must not complete.
    wr(0,2);wr(12,1);wr(16,4096);wr(24,3);wr(0,1);check(4,4);check(52,generation)
    wr(24,1);wr(16,4095);wr(0,1);check(4,4);check(52,generation)
    wr(16,4096);wr(0,1);cmd(4,0,5);wr(0,2);check(4,0);check(52,generation)
    wr(12,99);wr(0,1);check(4,4);cmd(5);check(4,0);check(52,0)
    for p in (ROOT/'rtl').glob('*.sv'):shutil.copyfile(p,a.work/p.name)
    shutil.copyfile(ROOT/'tests/tb_demo.sv',a.work/'tb_demo.sv')
    (a.work/'commands.mem').write_text('\n'.join(f'{v:08x}' for row in commands for v in row)+'\n');(a.work/'fixture_count.svh').write_text('localparam integer TOTAL=%d;\n'%len(commands));(a.work/'run.tcl').write_text('run all\nquit\n')
    log=b''
    for command in [['xvlog.bat','--sv','pcb_scalar.sv','pcb_demo_coeff.sv','pcb_demo_core.sv','pcb_demo_axi.sv','tb_demo.sv'],['xelab.bat','tb_demo','-s','demo','--timescale','1ns/1ps'],['xsim.bat','demo','-tclbatch','run.tcl']]:
        r=subprocess.run([str(a.vivado_bin/command[0])]+command[1:],cwd=a.work,capture_output=True);log+=r.stdout+r.stderr
        if r.returncode:break
    evidence=ROOT/'evidence';evidence.mkdir(exist_ok=True);(evidence/'full-pipeline.log').write_bytes(log)
    passed=r.returncode==0 and b'PL_PS_DEMO_RTL_PASS' in log and b'Fatal:' not in log
    result=dict(passed=passed,job_count=len(jobs),checked_output_elements=sum(len(j['expected']) for j in jobs),axi_commands=len(commands),board_connected=False,algorithm='PDP3 radix-2 DIF Q16 FFT; Q14 Hann; 64-bit one-sided power accumulation',numeric_quality=errors,input_sha256=input_hashes,source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'rtl').glob('*.sv')})
    if passed:
        actual={int(l.split()[0],16):int(l.split()[1],16) for l in (a.work/'actual.txt').read_text().splitlines()};returned=[]
        for job_info in jobs:
            output=[actual[lo]|(actual[hi]<<32) for lo,hi in job_info['output_reads']]
            if job_info['task']!=1:output=[v-(1<<64) if v>=1<<63 else v for v in output]
            assert output==job_info['expected']
            statistics={k:actual[v]-(1<<32) if k in ('min_mc','max_mc') and actual[v]>=1<<31 else actual[v] for k,v in job_info['stats_reads'].items()}
            returned.append(dict(name=job_info['name'],key=job_info['key'],task=job_info['task'],output=output,statistics=statistics,metadata=job_info['metadata']))
        (evidence/'rtl-results.json').write_text(json.dumps(dict(backend='XSim PDP3 AXI results',source_sha256=result['source_sha256'],input_sha256=input_hashes,jobs=returned),indent=2))
    (evidence/'full-pipeline.json').write_text(json.dumps(result,indent=2));(evidence/'rtl-verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2));return 0 if passed else 1
if __name__=='__main__':raise SystemExit(main())
