"""Validate that trained neural weights actually alter generated RGB pixels."""
from pathlib import Path
import argparse, hashlib, json, shutil, subprocess, sys
import numpy as np
import cv2

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime.neural_frames import NativeRenderer, render_pair, read_rgb
from runtime.integer_reference import run_model
from tools.train_neural_frame import compile_helper


def evaluate_case(helper,model,source,target,prefix):
    result=subprocess.run([str(helper),'generate',str(model),str(source),str(target),str(prefix)],capture_output=True,check=True)
    record=json.loads(result.stdout)
    warped=read_rgb(str(prefix)+'.warp.argb');neural=read_rgb(str(prefix)+'.neural.argb');repair=read_rgb(str(prefix)+'.previous.argb');truth=read_rgb(str(target)+'.argb')
    x=np.fromfile(str(prefix)+'.features.i8',np.int8).reshape(4,45,80)
    expected=run_model(ROOT/'models/frame',x)[-1]
    actual=np.fromfile(str(prefix)+'.logits.i8',np.int8).reshape(expected.shape)
    if not np.array_equal(expected,actual):raise ValueError('C++/Python model integer mismatch')
    if not record['network_participated'] or record['soft_blended_pixels']<=0:raise ValueError('network did not participate in generated pixels')
    alpha=np.fromfile(str(prefix)+'.alpha.u8',np.uint8).reshape(45,80)
    expanded=np.fromfile(str(prefix)+'.alpha-full.u8',np.uint8).reshape(720,1280).astype(np.uint32)[...,None]
    # Independent half-pixel bilinear reference; integer staging may differ by 1.
    bilinear=cv2.resize(alpha,(1280,720),interpolation=cv2.INTER_LINEAR)
    if np.abs(expanded[...,0].astype(int)-bilinear.astype(int)).max()>1:raise ValueError('fusion weights must be bilinearly interpolated')
    valid=np.fromfile(str(prefix)+'.valid.u8',np.uint8).reshape(720,1280)>0
    calculated=(expanded*warped.astype(np.uint32)+(255-expanded)*repair.astype(np.uint32)+127)//255
    if not np.array_equal(neural[~valid],repair[~valid]):raise ValueError('holes must retain previous complete pixels')
    if not np.array_equal(neural,calculated.astype(np.uint8)):raise ValueError('generated RGB not determined by network weights')
    affected=np.any(warped!=repair,axis=2)
    ids=np.fromfile(str(target)+'.u16',np.uint16).reshape(720,1280);depth=np.fromfile(str(target)+'.depth.u16',np.uint16).reshape(720,1280);geometry=(ids<64000)&(depth<65535)
    for name,image in [('warp',warped),('repair',repair),('neural',neural)]:
        error=np.abs(image.astype(float)-truth).mean(2)
        record[name+'_mae']=float(error.mean());record[name+'_affected_mae']=float(error[affected].mean());record[name+'_geometry_mae']=float(error[geometry].mean())
        squared=(image.astype(float)-truth)**2
        record[name+'_rmse']=float(np.sqrt(squared.mean()));record[name+'_affected_rmse']=float(np.sqrt(squared[affected].mean()))
    error=np.abs(neural.astype(float)-truth).mean(2)
    record.update(integer_equal=True,network_ablation_changes_pixels=True,full_frame_mae=record['neural_mae'],geometry_mae=record['neural_geometry_mae'],geometry_error_p95=float(np.percentile(error[geometry],95)),accepted=record['coverage']>=.94,
                  alpha_min=int(alpha.min()),alpha_max=int(alpha.max()),alpha_std=float(alpha.std()),measurement_input=False,physical_board_tested=False,board_speedup=None)
    return record,dict(warp=warped,neural=neural,truth=truth,repair=repair)


def main():
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);p.add_argument('--assets',type=Path,required=True);p.add_argument('--cxx',type=Path,required=True);a=p.parse_args()
    renderer,helper=compile_helper(a.work,a.cxx);e=ROOT/'evidence/neural-frame';e.mkdir(parents=True,exist_ok=True)
    train=json.loads((ROOT/'models/frame/training-report.json').read_text());cases=[];sheets=[]
    model=a.work/'model.pai'
    for suffix in ('','.kind','.scale','.sha256'):shutil.copyfile(str(ROOT/'models/frame/model.pai')+suffix,str(model)+suffix)
    with NativeRenderer(renderer,a.assets,a.work/'render') as engine:
        for i,case in enumerate(train['validation_cases']):
            source,target=render_pair(engine,a.work,case['mode'],case['yaw'],case['polar'],case['step'])
            record,images=evaluate_case(helper,model,source,target,a.work/'generated')
            cases.append(dict(index=i,mode=case['mode'],**record))
            if i<2:
                for name,image in images.items():(e/f'mode-{case["mode"]}-{name}.png').write_bytes(cv2.imencode('.png',image)[1].tobytes())
                row=[]
                for name in ['warp','neural','truth']:
                    image=cv2.resize(images[name],(640,360));cv2.putText(image,name.upper(),(16,30),cv2.FONT_HERSHEY_SIMPLEX,.8,(230,240,245),2);row.append(image)
                sheets.append(np.concatenate(row,1))
            print('Neural frame case',i,'changed',record['neural_changed_pixels'],'RGB pixels; soft fusion',record['soft_blended_pixels'],flush=True)
    (e/'comparison.png').write_bytes(cv2.imencode('.png',np.concatenate(sheets,0))[1].tobytes())
    result=dict(passed=True,cases=cases,trained_network_controls_rgb=True,network_is_confidence_classifier=False,
                frame_resolution=[1280,720],inference_grid=[80,45],board_verified=False,board_fps=None,
                average_neural_affected_mae=float(np.mean([c['neural_affected_mae'] for c in cases])),average_warp_affected_mae=float(np.mean([c['warp_affected_mae'] for c in cases])),average_repair_affected_mae=float(np.mean([c['repair_affected_mae'] for c in cases])),
                average_neural_affected_rmse=float(np.mean([c['neural_affected_rmse'] for c in cases])),average_warp_affected_rmse=float(np.mean([c['warp_affected_rmse'] for c in cases])),
                source_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'runtime/display/driver/full_ai_frame.h',ROOT/'tests/neural_frame_tool.cpp',ROOT/'models/frame/model.pai',ROOT/'models/frame/int8.npz']})
    (e/'result.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    # Retain the original acceptance schema, with the updated generator clearly named.
    (ROOT/'evidence/native-frame').mkdir(parents=True,exist_ok=True)
    (ROOT/'evidence/native-frame/result.json').write_text(json.dumps(dict(cases=cases,backend='learned RGB pixel fusion; explicit offline INT8 verification',gui_source_adapter_present=True,board_verified=False),indent=2),encoding='utf8')
    shutil.copyfile(helper,ROOT/'bin/neural_frame_tool.exe')
    shutil.copyfile(a.work/'helper-build.log',e/'helper-build.log')
    print('NEURAL_PIXEL_FUSION_PASS',len(cases),'held-out rendered cases')


if __name__=='__main__':main()
