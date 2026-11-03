"""Quantization-aware fine tune against the ACTUAL floor/GAP arithmetic.

The initial PTQ result is retained. No independent real-image claim is made.
"""
from pathlib import Path
import json,sys,shutil,hashlib,math,time
import numpy as np
import torch
import torch.nn.functional as F
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from train_models import Net,reg_data,evaluate,loss_fn
from runtime.integer_reference import run_model
torch.manual_seed(20261104);torch.set_num_threads(4)
def ste(q,x):return x+(q-x).detach()
def main():
    folder=ROOT/'models/registration';old=folder/'ptq-attempt';old.mkdir(exist_ok=True)
    for name in ['int8.npz','model.json','training-report.json']:
        if not (old/name).exists():shutil.copyfile(folder/name,old/name)
    current_report=json.loads((folder/'training-report.json').read_text())
    base_report=json.loads((old/'training-report.json').read_text()) if 'qat' in current_report else current_report
    desc=json.loads(((old if 'qat' in current_report else folder)/'model.json').read_text());desc['layers'][-1]['output_scale']=1/32;desc['layers'][-1]['shift']=3;desc['output_scale']=1/32
    net=Net('registration',[8,8,16]);net.load_state_dict(torch.load(folder/'pruned-finetuned.pt',map_location='cpu',weights_only=True));device='cuda' if torch.cuda.is_available() else 'cpu';net.to(device)
    def forward(x):
        x=ste(torch.clamp(torch.round(x*128),-128,127)/128,x);ix=0
        for d in desc['layers']:
            if d['op']=='gap':
                avg=x.mean((2,3),keepdim=True);x=ste(torch.trunc(avg/d['output_scale'])*d['output_scale'],avg);continue
            layer=list(net.layers)+[net.head];layer=layer[ix];ix+=1
            ws=d['weight_scale'];ins=d['input_scale'];outs=d['output_scale']
            w=torch.clamp(ste(torch.round(layer.weight/ws)*ws,layer.weight),-127*ws,127*ws);b=ste(torch.round(layer.bias/(ws*ins))*(ws*ins),layer.bias)
            y=F.conv2d(x,w,b,stride=d['stride'],padding=d['padding']);x=torch.clamp(ste(torch.floor(y/outs)*outs,y),(0 if d['relu'] else -128)*outs,127*outs)
        return x
    x,y=reg_data(1536,20261103);vx,vy=reg_data(192,20261104);xx=torch.from_numpy(x).to(device);yy=torch.from_numpy(y).to(device)
    optimizer=torch.optim.Adam(net.parameters(),lr=.0001);history=[];start=time.time();best_loss=float('inf');best_state=None;best_epoch=None
    for epoch in range(150):
        total=0
        for ix in torch.randperm(len(x),device=device).split(64):
            optimizer.zero_grad();loss=loss_fn('registration',forward(xx[ix]),yy[ix]);loss.backward();optimizer.step();total+=float(loss)*len(ix)
        history.append(total/len(x))
        if history[-1]<best_loss:best_loss=history[-1];best_epoch=epoch;best_state={k:v.detach().cpu().clone() for k,v in net.state_dict().items()}
        if epoch%20==0:print(epoch,history[-1],flush=True)
    net.cpu();net.load_state_dict(best_state);torch.save(net.state_dict(),folder/'qat-finetuned.pt');arrays={};layers=list(net.layers)+[net.head];ix=0
    for d in desc['layers']:
        if d['op']=='gap':continue
        l=layers[ix];ix+=1;arrays[d['weight_key']]=np.clip(np.rint(l.weight.detach().numpy()/d['weight_scale']),-127,127).astype(np.int8);arrays[d['bias_key']]=np.rint(l.bias.detach().numpy()/(d['weight_scale']*d['input_scale'])).astype(np.int32)
    np.savez(folder/'int8.npz',**arrays);desc['weights_sha256']=hashlib.sha256((folder/'int8.npz').read_bytes()).hexdigest();(folder/'model.json').write_text(json.dumps(desc,indent=2))
    pred=np.stack([run_model(folder,np.clip(np.rint(xx*128),-128,127).astype(np.int8))[-1] for xx in vx])*desc['output_scale']
    report=base_report;report['initial_ptq_validation']=report['int8_validation'];report['int8_validation']=evaluate('registration',pred,vy);report['quantization_output_rmse_before_qat']=report.pop('quantization_output_rmse');report['qat']={'epochs':150,'best_training_epoch':best_epoch,'selection':'minimum training loss, no validation selection','seed':20261104,'loss':history,'seconds':time.time()-start,'lr':.0001,'arithmetic':'STE exact arithmetic shifts/floor, int8 saturation and truncating GAP; saturation gradients masked','head_output_scale':1/32,'head_confidence_logit_clamped_to_int8':True,'independent_capture_validation':False}
    report['weight_hashes']={p.relative_to(folder).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.suffix in {'.pt','.npz'}};(folder/'training-report.json').write_text(json.dumps(report,indent=2));reports={task:json.loads((ROOT/'models'/task/'training-report.json').read_text()) for task in ['registration','frame']};(ROOT/'evidence/training.json').write_text(json.dumps(reports,indent=2));print(report['int8_validation'],flush=True)
if __name__=='__main__':main()
