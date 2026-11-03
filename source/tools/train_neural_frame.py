"""Train actual pixel-fusion weights from full native-render RGB error."""
from pathlib import Path
import argparse, hashlib, json, shutil, subprocess, sys, time
import numpy as np
import torch
from torch import nn
import torch.nn.functional as F

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.build_demo_host import build
from tools.train_models import Net, export, prune


def compile_helper(work,cxx):
    work=Path(work);work.mkdir(parents=True,exist_ok=True)
    renderer=build(work,cxx,install=False)
    shutil.copyfile(ROOT/'runtime/pcb_ai.cpp',work/'pcb_ai.cpp')
    shutil.copyfile(ROOT/'tests/neural_frame_tool.cpp',work/'neural_frame_tool.cpp')
    exe=work/'neural_frame_tool.exe'
    result=subprocess.run([str(cxx),'-std=c++14','-O2','-static',str(work/'neural_frame_tool.cpp'),'-o',str(exe)],capture_output=True)
    (work/'helper-build.log').write_bytes(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError('neural frame helper compile failed')
    return renderer,exe


def generate_dataset(work,assets,renderer,helper,count,seed):
    from runtime.neural_frames import NativeRenderer, render_pair, read_rgb
    rng=np.random.default_rng(seed);inputs=[];targets=[];weights=[];records=[]
    with NativeRenderer(renderer,assets,work/'render') as engine:
        for i in range(count):
            mode=[0,3][i%2];yaw=float(rng.uniform(.28,.85));polar=float(rng.uniform(.75,1.05));step=float(rng.choice([-1,1])*rng.uniform(.004,.024))
            source,target=render_pair(engine,work,mode,yaw,polar,step)
            prefix=work/'prepared'
            result=subprocess.run([str(helper),'prepare',str(source),str(target),str(prefix)],capture_output=True,check=True)
            a=read_rgb(str(prefix)+'.warp.argb').astype(np.float64);b=read_rgb(str(prefix)+'.previous.argb').astype(np.float64);truth=read_rgb(str(target)+'.argb').astype(np.float64)
            delta=b-a;denom=(delta*delta).reshape(45,16,80,16,3).sum((1,3,4));numer=((truth-a)*delta).reshape(45,16,80,16,3).sum((1,3,4))
            alpha=np.clip(numer/np.maximum(denom,1),0,1)
            x=np.fromfile(str(prefix)+'.features.i8',np.int8).reshape(4,45,80).astype(np.float32)/128
            inputs.append(x);targets.append((1-alpha)[None].astype(np.float32));weights.append((denom/np.maximum(denom.mean(),1))[None].astype(np.float32))
            records.append(dict(mode=mode,yaw=yaw,polar=polar,step=step,**json.loads(result.stdout)))
            if i%8==0:print('Rendered supervision',i,'/',count,flush=True)
    return np.array(inputs),np.array(targets),np.array(weights),records


def fit(net,x,y,w,epochs):
    device='cuda' if torch.cuda.is_available() else 'cpu';net.to(device)
    xx,yy,ww=[torch.from_numpy(a).to(device) for a in [x,y,w]]
    optimizer=torch.optim.Adam(net.parameters(),lr=.008);losses=[]
    for epoch in range(epochs):
        optimizer.zero_grad();pred=(-net(xx)).sigmoid()
        loss=((pred-yy).square()*ww).sum()/ww.sum();loss.backward();optimizer.step();losses.append(float(loss.detach()))
        if epoch%50==0:print('Pixel-fusion reconstruction loss',epoch,losses[-1],flush=True)
    net.cpu();return dict(device=device,epochs=epochs,loss=losses,objective='RGB reconstruction MSE, equivalent to weighted optimal-alpha regression; no confidence labels')


def main():
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);p.add_argument('--assets',type=Path,required=True);p.add_argument('--cxx',type=Path,required=True);p.add_argument('--train-count',type=int,default=48);p.add_argument('--validation-count',type=int,default=12);a=p.parse_args()
    a.work.mkdir(parents=True,exist_ok=True);torch.set_num_threads(4);torch.manual_seed(20261103)
    renderer,helper=compile_helper(a.work,a.cxx)
    x,y,w,records=generate_dataset(a.work,a.assets,renderer,helper,a.train_count,20261103)
    vx,vy,vw,validation=generate_dataset(a.work,a.assets,renderer,helper,a.validation_count,20261104)
    folder=ROOT/'models/frame';folder.mkdir(exist_ok=True)
    wide=Net('frame',[8]);training=fit(wide,x,y,w,200);torch.save(wide.state_dict(),folder/'wide-trained.pt')
    small,kept=prune(wide,[4]);torch.save(small.state_dict(),folder/'pruned-before-finetune.pt')
    finetuning=fit(small,x,y,w,200);torch.save(small.state_dict(),folder/'pruned-finetuned.pt')
    export(small,x,folder)
    descriptor=json.loads((folder/'model.json').read_text())
    descriptor.update(purpose='NEURAL_PIXEL_FUSION_V1',feature_semantics=['motion_x','motion_y','depth_edge','valid_fraction'],output_semantics='alpha_R = sigmoid(-raw_logit); bilinear interpolation; alpha_R*reprojected + (1-alpha_R)*previous')
    (folder/'model.json').write_text(json.dumps(descriptor,indent=2),encoding='utf8')
    np.savez_compressed(folder/'validation-inputs.npz',x=vx,y=vy,reconstruction_weight=vw)
    with torch.no_grad():pred=(-small(torch.from_numpy(vx))).sigmoid().numpy()
    report=dict(task='frame',purpose='NEURAL_PIXEL_FUSION_V1',seed=20261103,wide_parameters=sum(p.numel() for p in wide.parameters()),pruned_parameters=sum(p.numel() for p in small.parameters()),
                kept_output_channels=kept,training=training,finetuning=finetuning,
                validation_weighted_alpha_mse=float(((pred-vy)**2*vw).sum()/vw.sum()),
                source_groups=dict(rendered_supervision_only=True,real_acquisitions=[],independent_real_validation=[],split='disjoint camera pose seeds; same source-bound geometry and ADC terrain'),
                training_cases=records,validation_cases=validation,network_generates_pixel_weights=True,network_is_confidence_classifier=False)
    (folder/'training-report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    # Export only the new frame container; preserve registration bytes.
    from tools.export_binary import export_task
    export_task('frame')
    (folder/'model.pai.kind').write_text('NEURAL_PIXEL_FUSION_V1\n',encoding='ascii')
    print('Trained neural pixel-fusion model:',report['pruned_parameters'],'parameters',flush=True)


if __name__=='__main__':main()
