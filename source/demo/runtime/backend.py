"""Replay only values actually returned by the verified AXI RTL simulation."""
from pathlib import Path
import json
from .hashutil import sha256
ROOT=Path(__file__).resolve().parents[1]

def task_key(task,values,config):
    return sha256(json.dumps([task,values,config],separators=(',',':')).encode()).hexdigest()

class RtlReplay:
    backend='XSim checked AXI result replay'
    def __init__(self,path=None):
        evidence=json.loads(Path(path or ROOT/'evidence/rtl-results.json').read_text())
        for name,expected in evidence['source_sha256'].items():
            if sha256((ROOT/'rtl'/name).read_bytes()).hexdigest()!=expected:raise ValueError('RTL changed: rerun tools/verify_demo.py')
        for name,expected in evidence.get('input_sha256',{}).items():
            if sha256((ROOT/'inputs'/name).read_bytes()).hexdigest()!=expected:raise ValueError('Input fixture changed: rerun tools/verify_full_pipeline.py')
        self.jobs={job['key']:job for job in evidence['jobs']};self.calls=[]
    def run(self,task,values,config=None):
        config=config or {};key=task_key(task,values,config)
        if task!=1 and len(values)>4096:
            output=[];statistics={}
            for start in range(0,len(values),4096):
                c=dict(config)
                if task==2:c.update(mode=2 if start else 0,offset=start)
                tile=self.run(task,values[start:start+4096],c);output+=tile['output'];statistics=tile['statistics']
            return dict(output=output,statistics=statistics,input_key=key,backend=self.backend)
        if key not in self.jobs:raise ValueError('No actual RTL result for these demo inputs; no numerical fallback')
        job=self.jobs[key];self.calls.append({'task':task,'input_key':key,'backend':'XSim checked AXI result replay'})
        return {'output':list(job['output']),'statistics':dict(job['statistics']),'metadata':dict(job.get('metadata',{})),'input_key':key,'backend':self.backend}

    def run_three(self,frames):
        result=None
        for i,values in enumerate(frames):result=self.run(1,values,{} if i==0 else {'mode':3})
        return result
