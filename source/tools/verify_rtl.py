"""Build complete trained layer test vectors and run XSim. No board access."""
from pathlib import Path
import argparse,json,shutil,subprocess,os,sys,hashlib
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime.integer_reference import run_model,conv
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--vivado-bin',type=Path,required=True);ap.add_argument('--work',type=Path,required=True);a=ap.parse_args();a.work.mkdir(parents=True,exist_ok=True)
    os.environ['TEMP']=os.environ['TMP']=str(a.work)
    words=[];cases=[]
    def cmd(op,addr=0,data=0):words.extend([op,addr,data&0xffffffff])
    def wr(addr,data):cmd(1,addr,int(data))
    def layer_case(name,task,x,y,d,w=None,b=None):
        wr(0,2);c,h,width=x.shape;oc,oh,ow=y.shape
        for addr,val in [(12,task),(16,width),(20,h),(24,c),(28,oc),(32,d.get('kernel',1)),(36,d.get('stride',1)),(40,d.get('padding',0)),(44,d.get('shift',0)),(48,int(d.get('relu',False))),(52,int(d['op']=='gap')),(56,ow),(60,oh)]:wr(addr,val)
        for i,v in enumerate(x.ravel()):wr(0x10000+4*i,v)
        if w is not None:
            for i,v in enumerate(w.ravel()):wr(0x30000+4*i,v)
            for i,v in enumerate(b):wr(0x38000+4*i,v)
        wr(0,1);cmd(3)
        for i,v in enumerate(y.ravel()):cmd(2,0x20000+4*i,int(v)&0xffffffff)
        cmd(4,len(cases));cases.append({'name':name,'input':list(x.shape),'output':list(y.shape),'output_elements':y.size,'expected_sha256':hashlib.sha256(y.tobytes()).hexdigest()})
    for kind in ['registration','frame']:
        folder=ROOT/'models'/kind;desc=json.loads((folder/'model.json').read_text());weights=np.load(folder/'int8.npz');data=np.load(folder/'validation-inputs.npz')['x'][0]
        x=np.clip(np.rint(data*128),-128,127).astype(np.int8);ys=run_model(folder,x)
        for i,(d,y) in enumerate(zip(desc['layers'],ys)):
            layer_case(kind+'/'+str(i),desc['task_id'],x,y,d,weights[d['weight_key']] if d['op']=='conv' else None,weights[d['bias_key']] if d['op']=='conv' else None);x=y
    rng=np.random.default_rng(18)
    for i,(k,st,pad,rel,shift) in enumerate([(1,1,0,False,0),(3,2,1,True,7),(3,1,1,False,4)]):
        x=rng.integers(-128,128,(3,5,7),dtype=np.int8);w=rng.integers(-128,128,(2,3,k,k),dtype=np.int8);b=np.array([2147483600,-2147483600],np.int32) if i==0 else np.array([100,-100],np.int32)
        y=conv(x,w,b,st,pad,shift,rel);d={'op':'conv','kernel':k,'stride':st,'padding':pad,'relu':rel,'shift':shift};layer_case('edge/'+str(i),1,x,y,d,w,b)
    cmd(5);cmd(0)
    (a.work/'commands.hex').write_text('\n'.join(f'{v:08x}' for v in words)+'\n')
    (a.work/'command_count.vh').write_text(f'localparam COMMAND_WORDS={len(words)};\n')
    for p in (ROOT/'rtl').glob('pcb_ai*.sv'):shutil.copyfile(p,a.work/p.name)
    shutil.copyfile(ROOT/'tests/tb_ai.sv',a.work/'tb_ai.sv')
    report={'cases':cases,'board_accessed':False,'simulation':False,'model_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for kind in ['registration','frame'] for p in (ROOT/'models'/kind).glob('*') if p.name in {'model.json','int8.npz','validation-inputs.npz'}}}
    for name,args in [('compile',['xvlog.bat','--sv','pcb_ai_core.sv','pcb_ai_axi.sv','tb_ai.sv']),('elaborate',['xelab.bat','tb_ai','-s','ai_sim','--timescale','1ns/1ps']),('simulate',['xsim.bat','ai_sim','-tclbatch','simulate.tcl'])]:
        (a.work/'simulate.tcl').write_text('run all\nquit\n')
        with (a.work/(name+'.log')).open('wb') as f:r=subprocess.run([str(a.vivado_bin/args[0])]+args[1:],cwd=a.work,stdout=f,stderr=subprocess.STDOUT)
        shutil.copyfile(a.work/(name+'.log'),ROOT/'evidence'/('rtl-'+name+'.log'))
        if r.returncode:report['failed_stage']=name;break
    else:report['simulation']='ALL_AI_PASS' in (a.work/'simulate.log').read_text(errors='replace')
    (ROOT/'evidence/rtl-verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2));return 0 if report['simulation'] else 1
if __name__=='__main__':raise SystemExit(main())
