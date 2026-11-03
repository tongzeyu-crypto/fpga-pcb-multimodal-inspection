"""Board-local processor for source-validated raw replay or fresh bundles."""
from pathlib import Path
import argparse,hashlib,json,platform,sys,subprocess
import numpy as np
from .capture_bundle import load,require,MissingInput
from .numerics import thermal_decode,spectrum_three,bands
def process(path,output,reference=None,offline_test=False):
    path=Path(path);b=load(path);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    if not offline_test and (platform.system()!='Linux' or not platform.machine().startswith(('arm','aarch'))):raise RuntimeError('production processor requires board ARM Linux')
    record={'board_id':b['board_id'],'capture_id':b['capture_id'],'calibration_version':b['calibration_version'],'mode':'explicit offline verification' if offline_test else 'ARM production','raw_input_hashes':{i['path']:i['sha256'] for items in b['raw'].values() for i in items},'modalities':{},'acquisition_batches':b['acquisition_batches'],'synchronization':b['synchronization']}
    for kind in ['rgb','thermal','adc']:
        try:items=require(b,kind)
        except MissingInput as e:record['modalities'][kind]={'state':'waiting','reason':str(e)};continue
        if kind=='thermal':
            _,t=thermal_decode((path.parent/items[0]['path']).read_bytes());t.astype('<f4').tofile(output/'temperature.f32');record['modalities'][kind]={'state':'computed','min_c':float(t.min()),'max_c':float(t.max()),'raw_dimensions':[192,256],'calibrated_absolute_accuracy':False}
        if kind=='adc':
            points={}
            for i in items:points.setdefault(i['point_index'],[]).append(path.parent/i['path'])
            results=[]
            for n,files in sorted(points.items()):
                psd=spectrum_three(files);psd.astype('<f4').tofile(output/f'point-{n:05d}-psd.f32');results.append({'index':n,'bands_rms_adc_codes':bands(psd)})
            record['modalities'][kind]={'state':'computed','points':results,'unit':'ADC codes squared per Hz','encoding':'14-bit two-complement interpretation hypothesis; not calibrated voltage','frequency_bins':2049,'raw_high_frequency_preserved':True,'external_io_timing_signed_off':False}
        if kind=='rgb':
            if reference is None:record['modalities'][kind]={'state':'captured','aoi':'waiting for normal reference RGB'}
            else:
                from .aoi_rules import detect
                raw=(path.parent/items[0]['path']).read_bytes()
                try:
                    result=detect(Path(reference).read_bytes(),raw);(output/'aoi.json').write_text(json.dumps(result,indent=2),encoding='utf8');record['modalities'][kind]={'state':'rule-screened','test_sha256':hashlib.sha256(raw).hexdigest(),'reference_sha256':hashlib.sha256(Path(reference).read_bytes()).hexdigest(),'result':result}
                except ValueError as e:record['modalities'][kind]={'state':'aoi_unavailable','reason':str(e)}
    record['ai_registration']={'state':'waiting for RGB and thermal'}
    if b['board_id']=='dcdc' and b['raw'].get('rgb') and b['raw'].get('thermal'):
        try:
            import cv2
            from .registration import correct
            root=Path(__file__).resolve().parents[1];model=json.loads((root/'resources/models/model-v3.json').read_text(encoding='utf8'));geo=model['board_geometry'];w,h=geo['rectified_size_px'];margin=geo['extended_margin_px'];size=(w+2*margin,h+2*margin)
            cal=json.loads((path.parent/'dcdc-rgb-thermal/thermal-calibration.json').read_text());rgb=cv2.imdecode(np.frombuffer((path.parent/b['raw']['rgb'][0]['path']).read_bytes(),np.uint8),0)
            rgb_h=np.array(geo['native_rgb_to_board']);rgb_h[0]+=margin*rgb_h[2];rgb_h[1]+=margin*rgb_h[2]
            rgb=cv2.warpPerspective(rgb,rgb_h,size);_,t=thermal_decode((path.parent/b['raw']['thermal'][0]['path']).read_bytes());initial=np.array(cal['matrix_thermal_to_extended_rgb']);aligned=cv2.warpPerspective(t,initial,size)
            residual,detail=correct(rgb,aligned,offline_test=offline_test);scale=np.diag([64/size[0],48/size[1],1]);transform=np.linalg.inv(scale)@residual@scale@initial
            record['ai_registration']={'state':'computed','backend':'explicit offline INT8 reference' if offline_test else 'PL task 1','thermal_to_extended_rgb':transform.tolist(),'detail':detail,'absolute_registration_accuracy_validated':False}
        except (OSError,KeyError,RuntimeError,ValueError,subprocess.SubprocessError) as e:
            record['ai_registration']={'state':'unavailable','reason':str(e),'silent_software_fallback':False}
    # Atomic publication; consumers must match capture_id and board_id.
    temp=output/'processing.json.tmp';temp.write_text(json.dumps(record,indent=2),encoding='utf8');temp.replace(output/'processing.json');return record
def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--reference',type=Path);p.add_argument('--offline-test',action='store_true');a=p.parse_args();process(a.bundle,a.output,a.reference,a.offline_test)
if __name__=='__main__':main()
