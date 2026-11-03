"""Train -> L1 structured prune -> fine tune -> power-of-two W8A8 export.

One physical RGB/thermal source is available. Validation here is explicitly a
held-out AUGMENTATION test of that source, never independent acquisition accuracy.
Frame supervision comes from complete 1280x720 software renders of a model prior.
"""
from pathlib import Path
import argparse,hashlib,json,math,sys,time
import numpy as np
import cv2
import torch
from torch import nn
import torch.nn.functional as F
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime.frame_synthesis import make_legacy_confidence_training_frames
torch.set_num_threads(4)
SEED=20261103
def savej(p,x):p.write_text(json.dumps(x,indent=2),encoding='utf8')
class Net(nn.Module):
    def __init__(self,kind,channels):
        super().__init__();self.kind=kind
        inp=2 if kind=='registration' else 4
        self.layers=nn.ModuleList()
        for out in channels:
            self.layers.append(nn.Conv2d(inp,out,3,stride=2 if kind=='registration' else 1,padding=1));inp=out
        self.head=nn.Conv2d(inp,9 if kind=='registration' else 1,1 if kind=='registration' else 3,padding=0 if kind=='registration' else 1)
    def forward(self,x,collect=False):
        acts=[]
        for layer in self.layers:x=F.relu(layer(x));acts.append(x)
        if self.kind=='registration':x=x.mean((2,3),keepdim=True);acts.append(x)
        x=self.head(x);acts.append(x)
        return (x,acts) if collect else x
def reg_data(n,seed):
    rng=np.random.default_rng(seed);raw=ROOT/'data/raw/dcdc-rgb-thermal'
    rgb=cv2.imdecode(np.fromfile(raw/'rgb.jpg',np.uint8),0)
    # Carrier is two full planes, not interleaved temperatures.
    thermal=np.fromfile(raw/'thermal.raw','<u2').reshape(2,192,256)[1].astype(np.float32)/16-273.15
    cal=json.loads((raw/'thermal-calibration.json').read_text(encoding='utf8'))
    model=json.loads((ROOT/'resources/models/model-v3.json').read_text(encoding='utf8'))
    sz=model['board_geometry']['rectified_size_px'];margin=model['board_geometry']['extended_margin_px']
    h=np.array(model['board_geometry']['native_rgb_to_board']);h[0]+=margin*h[2];h[1]+=margin*h[2]
    rgb=cv2.warpPerspective(rgb,h,(sz[0]+2*margin,sz[1]+2*margin))
    th=cv2.warpPerspective(thermal,np.array(cal['matrix_thermal_to_extended_rgb']), (rgb.shape[1],rgb.shape[0]))
    def structure(a):
        a=cv2.resize(a,(64,48)).astype(np.float32);a=cv2.GaussianBlur(a,(3,3),0)
        a=cv2.magnitude(cv2.Sobel(a,cv2.CV_32F,1,0),cv2.Sobel(a,cv2.CV_32F,0,1))
        return np.clip(a/max(np.percentile(a,98),1e-5),0,1)
    r,t=structure(rgb),structure(th);xs=[];ys=[]
    corners=np.array([[0,0],[63,0],[63,47],[0,47]],np.float32)
    for i in range(n):
        # Fixed rig residual translations, rotation <= 2 degrees, scale <= 2%.
        angle=rng.uniform(-2,2);m=cv2.getRotationMatrix2D((31.5,23.5),angle,rng.uniform(.98,1.02));m[:,2]+=rng.uniform(-3,3,2)
        moved=cv2.warpAffine(t,m,(64,48));bad=i%8==0
        if bad:moved=rng.uniform(0,1,(48,64)).astype(np.float32)
        inv=cv2.invertAffineTransform(m);q=corners@m[:,:2].T+m[:,2]
        # Output is corrective displacement at the OBSERVED corners.
        target=(corners-q).reshape(-1)/4
        xs.append(np.stack([r,moved]));ys.append(np.r_[target,0. if bad else 1.])
    return np.array(xs,np.float32),np.array(ys,np.float32)[:,:,None,None]
def loss_fn(kind,pred,y):
    if kind=='registration':
        return (((pred[:,:8]-y[:,:8])**2)*y[:,8:]).mean()+.15*F.binary_cross_entropy_with_logits(pred[:,8:],y[:,8:])
    return F.binary_cross_entropy_with_logits(pred,y)
def fit(net,x,y,epochs,device):
    net.to(device);xx=torch.from_numpy(x).to(device);yy=torch.from_numpy(y).to(device)
    opt=torch.optim.Adam(net.parameters(),lr=.002);history=[];start=time.time()
    for epoch in range(epochs):
        order=torch.randperm(len(x),device=device);total=0
        for ix in order.split(64):
            opt.zero_grad();loss=loss_fn(net.kind,net(xx[ix]),yy[ix]);loss.backward();opt.step();total+=float(loss)*len(ix)
        history.append(total/len(x))
        if epoch%20==0 or epoch==epochs-1:print(net.kind,epoch,history[-1],flush=True)
    net.cpu();return {'loss':history,'seconds':time.time()-start,'optimizer':'Adam','lr':.002,'epochs':epochs}
def prune(wide,channels):
    small=Net(wide.kind,channels);prev=list(range(2 if wide.kind=='registration' else 4));indices=[]
    with torch.no_grad():
        for src,dst,count in zip(wide.layers,small.layers,channels):
            rank=src.weight.abs().sum((1,2,3));keep=sorted(torch.topk(rank,count).indices.tolist());indices.append(keep)
            dst.weight.copy_(src.weight[keep][:,prev]);dst.bias.copy_(src.bias[keep]);prev=keep
        small.head.weight.copy_(wide.head.weight[:,prev]);small.head.bias.copy_(wide.head.bias)
    return small,indices
def pow2(x):return 2.**math.ceil(math.log2(max(float(x),2**-24)))
def export(net,cal,out):
    with torch.no_grad():_,acts=net(torch.from_numpy(cal),True)
    scale=1/128;layers=[];arrays={};ai=0
    for i,layer in enumerate(list(net.layers)+[net.head]):
        if i==len(net.layers) and net.kind=='registration':
            layers.append({'op':'gap','channels':layer.in_channels,'input_scale':scale,'output_scale':scale});ai+=1
        w=layer.weight.detach().numpy();b=layer.bias.detach().numpy();ws=pow2(np.max(np.abs(w))/127)
        os=pow2(float(torch.quantile(acts[ai].abs().flatten(),.9999))/120);ai+=1
        shift=round(math.log2(os/(scale*ws)))
        if not 0<=shift<=31:raise ValueError('unsupported quant shift')
        qw=np.clip(np.rint(w/ws),-127,127).astype(np.int8);qb=np.rint(b/(scale*ws)).astype(np.int32)
        idx=len(layers);arrays['w'+str(idx)]=qw;arrays['b'+str(idx)]=qb
        desc={'op':'conv','in_channels':layer.in_channels,'out_channels':layer.out_channels,'kernel':layer.kernel_size[0],'stride':layer.stride[0],'padding':layer.padding[0],'relu':i<len(net.layers),'shift':shift,'input_scale':scale,'weight_scale':ws,'output_scale':os,'weight_key':'w'+str(idx),'bias_key':'b'+str(idx)}
        layers.append(desc);scale=os
    np.savez(out/'int8.npz',**arrays)
    savej(out/'model.json',{'schema':'PCB-AI-W8A8/1','hardware_abi':1,'task':net.kind,'task_id':1 if net.kind=='registration' else 2,'input_scale':1/128,'output_scale':scale,'input_shape':[2,48,64] if net.kind=='registration' else [4,45,80],'layers':layers,'arithmetic':'int32 wrap accumulation; arithmetic right shift; int8 saturation; GAP truncates toward zero','weights_sha256':hashlib.sha256((out/'int8.npz').read_bytes()).hexdigest()})
def evaluate(kind,p,y):
    if kind=='registration':
        good=y[:,8,0,0]>0
        return {'augmentation_corner_rmse_px':float(np.sqrt(np.mean((p[good,:8]-y[good,:8])**2))*4),'zero_correction_rmse_px':float(np.sqrt(np.mean(y[good,:8]**2))*4),'confidence_accuracy':float(np.mean((p[:,8]>0)==(y[:,8]>.5))),'independent_capture_accuracy':None}
    sig=1/(1+np.exp(-np.clip(p,-20,20)))
    return {'render_region_brier':float(np.mean((sig-y)**2)),'render_region_accuracy':float(np.mean((sig>=.5)==(y>=.5))),'positive_fraction':float(y.mean())}
def main():
    a=argparse.ArgumentParser();a.add_argument('--epochs',type=int,default=100);a.add_argument('--task',choices=['all','registration','frame'],default='all');args=a.parse_args()
    if args.task=='frame':raise SystemExit('Frame model now generates RGB fusion weights. Use tools/train_neural_frame.py with native-render inputs; legacy confidence training is disabled.')
    torch.manual_seed(SEED);np.random.seed(SEED);device='cuda' if torch.cuda.is_available() else 'cpu';print('device',device,flush=True)
    reports={}
    for kind,wide_ch,small_ch in [('registration',[12,16,24],[8,8,16]),('frame',[8],[4])]:
        if kind=='frame':continue # Dedicated RGB-reconstruction training, not confidence classification.
        if args.task not in {'all',kind}:continue
        out=ROOT/'models'/kind;out.mkdir(parents=True,exist_ok=True)
        if kind=='registration':x,y=reg_data(1536,SEED);vx,vy=reg_data(192,SEED+1)
        else:x,y,vx,vy=make_legacy_confidence_training_frames(ROOT,SEED)
        np.savez_compressed(out/'validation-inputs.npz',x=vx[:8],y=vy[:8])
        wide=Net(kind,wide_ch);init=hashlib.sha256(b''.join(t.numpy().tobytes() for t in wide.state_dict().values())).hexdigest()
        pre=fit(wide,x,y,args.epochs,device);torch.save(wide.state_dict(),out/'wide-trained.pt')
        small,indices=prune(wide,small_ch);torch.save(small.state_dict(),out/'pruned-before-finetune.pt')
        post=fit(small,x,y,max(30,args.epochs//2),device);torch.save(small.state_dict(),out/'pruned-finetuned.pt')
        with torch.no_grad():p=small(torch.from_numpy(vx)).numpy();wp=wide(torch.from_numpy(vx)).numpy()
        export(small,x[:192],out)
        from runtime.integer_reference import run_model
        ip=np.stack([run_model(out,np.clip(np.rint(xx*128),-128,127).astype(np.int8))[-1] for xx in vx])
        desc=json.loads((out/'model.json').read_text());qp=ip*desc['output_scale']
        report={'task':kind,'seed':SEED,'device':device,'source_groups':{'real_acquisitions':['dcdc-20261029-rgb-thermal'],'independent_real_validation':[],'split':'augmentation seeds only; same physical capture, no independent generalization claim' if kind=='registration' else 'disjoint camera pose seeds; same prebuilt geometry prior; rendered not measured'},'initial_state_sha256':init,'wide_channels':wide_ch,'pruned_channels':small_ch,'kept_output_channels':indices,'wide_parameters':sum(v.numel() for v in wide.parameters()),'pruned_parameters':sum(v.numel() for v in small.parameters()),'training':pre,'finetuning':post,'wide_validation':evaluate(kind,wp,vy),'float_validation':evaluate(kind,p,vy),'int8_validation':evaluate(kind,qp,vy),'quantization_output_rmse':float(np.sqrt(np.mean((qp-p)**2))),'weight_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.glob('*') if p.suffix in {'.pt','.npz'}}}
        if kind=='frame':
            report['source_groups']['real_acquisitions']=[]
            report['source_groups']['geometry_prior']='resources/models/model-v3.json'
            report['source_groups']['rendered_supervision_only']=True
        savej(out/'training-report.json',report);reports[kind]=report;print(kind,report['int8_validation'],flush=True)
    combined={}
    for task in ['registration','frame']:
        p=ROOT/'models'/task/'training-report.json'
        if p.exists():combined[task]=json.loads(p.read_text())
    savej(ROOT/'evidence/training.json',combined)
if __name__=='__main__':main()
