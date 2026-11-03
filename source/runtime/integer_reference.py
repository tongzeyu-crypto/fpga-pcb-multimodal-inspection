"""Explicit OFFLINE backend; never selected implicitly by production runtime."""
from pathlib import Path
import json,hashlib
import numpy as np
def conv(x,w,b,stride,pad,shift,relu):
    x=np.pad(x.astype(np.int32),((0,0),(pad,pad),(pad,pad)))
    k=w.shape[2];windows=np.lib.stride_tricks.sliding_window_view(x,(k,k),axis=(1,2))[:,::stride,::stride]
    z=np.einsum('cyxij,ocij->oyx',windows,w.astype(np.int32),dtype=np.int32,optimize=True)+b[:,None,None]
    z=z>>shift
    return np.clip(z,0 if relu else -128,127).astype(np.int8)
def run_model(folder,x):
    folder=Path(folder);d=json.loads((folder/'model.json').read_text());p=folder/'int8.npz'
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['weights_sha256']:raise ValueError('model weight digest')
    w=np.load(p);ys=[]
    if list(x.shape)!=d['input_shape'] or x.dtype!=np.int8:raise ValueError('input dtype/shape')
    for layer in d['layers']:
        if layer['op']=='gap':x=np.trunc(x.astype(np.int32).sum((1,2),keepdims=True)/(x.shape[1]*x.shape[2])).astype(np.int8)
        else:x=conv(x,w[layer['weight_key']],w[layer['bias_key']],layer['stride'],layer['padding'],layer['shift'],layer['relu'])
        ys.append(x)
    return ys
