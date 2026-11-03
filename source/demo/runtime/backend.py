"""Replay only values actually returned by the verified AXI RTL simulation."""
from pathlib import Path
import json
from .hashutil import sha256
ROOT=Path(__file__).resolve().parents[1]

def task_key(task,values,config):
    return sha256(json.dumps([task,values,config],separators=(',',':')).encode()).hexdigest()

class RtlReplay:
    def __init__(self,path=None):
        evidence=json.loads(Path(path or ROOT/'evidence/rtl-results.json').read_text())
        for name,expected in evidence['source_sha256'].items():
            if sha256((ROOT/'rtl'/name).read_bytes()).hexdigest()!=expected:raise ValueError('RTL changed: rerun tools/verify_demo.py')
        self.jobs={job['key']:job for job in evidence['jobs']};self.calls=[]
    def run(self,task,values,config=None):
        config=config or {};key=task_key(task,values,config)
        if key not in self.jobs:raise ValueError('No actual RTL result for these demo inputs; no numerical fallback')
        job=self.jobs[key];self.calls.append({'task':task,'input_key':key,'backend':'XSim checked AXI result replay'})
        return {'output':list(job['output']),'statistics':dict(job['statistics']),'input_key':key,'backend':'XSim checked AXI result replay'}
