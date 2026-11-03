"""Portable, bounded model container for ARM; SHA256 sidecars + FNV payload CRC."""
from pathlib import Path
import json,struct,hashlib
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
def fnv(raw):
    value=2166136261
    for b in raw:value=((value^b)*16777619)&0xffffffff
    return value
def export_task(task):
    p=ROOT/'models'/task;d=json.loads((p/'model.json').read_text());z=np.load(p/'int8.npz');c,h,w=d['input_shape'];payload=bytearray()
    for layer in d['layers']:
        gap=layer['op']=='gap';oc=c if gap else layer['out_channels'];ow=1 if gap else (w+2*layer['padding']-layer['kernel'])//layer['stride']+1;oh=1 if gap else (h+2*layer['padding']-layer['kernel'])//layer['stride']+1
        vals=[int(gap),c,oc,layer.get('kernel',1),layer.get('stride',1),layer.get('padding',0),layer.get('shift',0),int(layer.get('relu',False)),w,h,ow,oh]
        payload+=struct.pack('<12I',*vals)
        if not gap:payload+=z[layer['weight_key']].tobytes()+z[layer['bias_key']].astype('<i4').tobytes()
        c,h,w=oc,oh,ow
    header=struct.pack('<10I',0x31494150,1,0x20261103,d['task_id'],len(d['layers']),*d['input_shape'],len(payload),fnv(payload))
    out=p/'model.pai';out.write_bytes(header+payload);(p/'model.pai.sha256').write_text(hashlib.sha256(out.read_bytes()).hexdigest()+'  model.pai\n');(p/'model.pai.scale').write_text(str(d['output_scale'])+'\n')
    data=np.load(p/'validation-inputs.npz')['x'][0];np.clip(np.rint(data*128),-128,127).astype(np.int8).tofile(p/'test-input.i8')

def main():
    for task in ['registration','frame']:export_task(task)
if __name__=='__main__':main()
