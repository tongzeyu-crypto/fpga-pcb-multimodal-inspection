"""Actual PL submission interface. Offline inference must be named explicitly."""
from pathlib import Path
import hashlib,json,subprocess,tempfile,platform
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
def infer(task,x,*,offline_test=False,binary=None,device='/dev/pcb_ai'):
    folder=ROOT/'models'/task;desc=json.loads((folder/'model.json').read_text());x=np.asarray(x,np.float32)
    if list(x.shape)!=desc['input_shape'] or not np.isfinite(x).all():raise ValueError('model input tensor')
    q=np.clip(np.rint(x/desc['input_scale']),-128,127).astype(np.int8)
    if offline_test:
        from .integer_reference import run_model
        return run_model(folder,q)[-1].astype(np.float32)*desc['output_scale']
    return infer_quantized(task,q,binary=binary,device=device)

def infer_quantized(task,q,*,binary=None,device='/dev/pcb_ai'):
    folder=ROOT/'models'/task;desc=json.loads((folder/'model.json').read_text());q=np.asarray(q)
    if q.dtype!=np.int8 or list(q.shape)!=desc['input_shape']:raise ValueError('quantized model input tensor')
    if platform.system()!='Linux' or platform.machine() not in {'armv7l','armv8l','aarch64'}:raise RuntimeError('production inference requires board Linux and PL device')
    model=folder/'model.pai';expected=(folder/'model.pai.sha256').read_text().split()[0]
    if hashlib.sha256(model.read_bytes()).hexdigest()!=expected:raise ValueError('portable model SHA256')
    with tempfile.TemporaryDirectory(prefix='pcb-ai-') as td:
        td=Path(td);q.tofile(td/'input.i8')
        subprocess.run([str(binary or ROOT/'bin/pcb_ai'),'--'+task,str(model),str(td/'input.i8'),str(td/'output.i8'),device],check=True,timeout=40)
        y=np.fromfile(td/'output.i8',np.int8)
        shape=(9,1,1) if task=='registration' else (1,45,80)
        if y.size!=np.prod(shape):raise ValueError('PL result length')
        return y.reshape(shape).astype(np.float32)*desc['output_scale']
