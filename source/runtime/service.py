"""Board-local processor for source-validated raw replay or fresh bundles."""
from pathlib import Path
import argparse,hashlib,json,platform,sys,subprocess
import numpy as np
from .capture_bundle import load,require,MissingInput
from .numerics import thermal_decode,spectrum_three,bands
def process(path,output,reference=None,offline_test=False,calibration=None,annotations=None):
    path=Path(path);b=load(path);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    if not offline_test and (platform.system()!='Linux' or not platform.machine().startswith(('arm','aarch'))):raise RuntimeError('production processor requires board ARM Linux')
    from .compute_backend import PlCompute
    from .numerics import adc_decode,read_adc
    compute=None if offline_test else PlCompute()
    t=None
    record={'board_id':b['board_id'],'capture_id':b['capture_id'],'calibration_version':b['calibration_version'],'mode':'explicit offline verification' if offline_test else 'ARM production','raw_input_hashes':{i['path']:i['sha256'] for items in b['raw'].values() for i in items},'modalities':{},'acquisition_batches':b['acquisition_batches'],'synchronization':b['synchronization']}
    for kind in ['rgb','thermal','adc']:
        try:items=require(b,kind)
        except MissingInput as e:record['modalities'][kind]={'state':'waiting','reason':str(e)};continue
        if kind=='thermal':
            raw=(path.parent/items[0]['path']).read_bytes()
            if compute:
                _,t,statistics=compute.thermal_decode(raw)
                colors=compute.pseudocolor(np.rint(t*1000).astype(np.int32));colors.astype('<u4').tofile(output/'thermal-color.argb')
                quant=compute.thermal_quantize(np.frombuffer(raw[98304:],'<u2').reshape(192,256));quant.tofile(output/'thermal-input.i8')
            else:
                _,t=thermal_decode(raw);statistics={'hot_count':int(np.count_nonzero(t>=40)),'min_mc':int(np.rint(t.min()*1000)),'max_mc':int(np.rint(t.max()*1000)),'max_index':int(np.argmax(t)),'processed_pixels':int(t.size)}
            t.astype('<f4').tofile(output/'temperature.f32');record['modalities'][kind]={'state':'computed','backend':compute.backend if compute else 'explicit PS floating reference','statistics':statistics,'min_c':statistics['min_mc']/1000,'max_c':statistics['max_mc']/1000,'raw_dimensions':[192,256],'calibrated_absolute_accuracy':False}
        if kind=='adc':
            points={}
            for i in items:points.setdefault(i['point_index'],[]).append(path.parent/i['path'])
            results=[]
            for n,files in sorted(points.items()):
                if len(files)!=3:raise ValueError('exactly three ADC frames required')
                psd=compute.spectrum_three([compute.decode_adc(read_adc(f)) for f in files]) if compute else spectrum_three(files)
                psd.astype('<f4').tofile(output/f'point-{n:05d}-psd.f32');results.append({'index':n,'bands_rms_adc_codes':compute.last_bands_rms if compute else bands(psd)})
            record['modalities'][kind]={'state':'computed','backend':compute.backend if compute else 'explicit PS floating reference','points':results,'unit':'ADC codes squared per Hz','encoding':'14-bit two-complement interpretation hypothesis; not calibrated voltage','frequency_bins':2049,'raw_high_frequency_preserved':True,'external_io_timing_signed_off':False}
        if kind=='rgb':
            if reference is None:record['modalities'][kind]={'state':'captured','aoi':'waiting for normal reference RGB'}
            else:
                from .aoi_rules import detect
                raw=(path.parent/items[0]['path']).read_bytes()
                try:
                    labels=json.loads(Path(annotations).read_text(encoding='utf8')) if annotations else None
                    result=detect(Path(reference).read_bytes(),raw,compute=compute,annotations=labels);(output/'aoi.json').write_text(json.dumps(result,indent=2),encoding='utf8');record['modalities'][kind]={'state':'rule-screened','test_sha256':hashlib.sha256(raw).hexdigest(),'reference_sha256':hashlib.sha256(Path(reference).read_bytes()).hexdigest(),'result':result}
                except ValueError as e:record['modalities'][kind]={'state':'aoi_unavailable','reason':str(e)}
    record['ai_registration']={'state':'waiting for RGB and thermal'}
    if b['raw'].get('rgb') and b['raw'].get('thermal'):
        try:
            import cv2
            from .registration import correct
            from .board_profiles import model as board_model
            model=board_model(b['board_id']);geo=model['board_geometry'];w,h=geo['rectified_size_px'];margin=geo['extended_margin_px'];size=(w+2*margin,h+2*margin)
            from .calibration import resolve
            cal,calpath=resolve(b,path,calibration);record['calibration_source']=str(calpath.resolve());record['calibration_sha256']=hashlib.sha256(calpath.read_bytes()).hexdigest();rgb_bytes=np.frombuffer((path.parent/b['raw']['rgb'][0]['path']).read_bytes(),np.uint8)
            rgb=compute.gray(cv2.imdecode(rgb_bytes,cv2.IMREAD_COLOR)[...,::-1]) if compute else cv2.imdecode(rgb_bytes,0)
            preview=compute.image('resize',rgb,out_width=256,out_height=192).astype(np.int16)-128 if compute else cv2.resize(rgb,(256,192)).astype(np.int16)-128
            preview.astype(np.int8).tofile(output/'rgb-preview.i8')
            rgb_h=np.array(geo['native_rgb_to_board']);rgb_h[0]+=margin*rgb_h[2];rgb_h[1]+=margin*rgb_h[2]
            rgb=cv2.warpPerspective(rgb,rgb_h,size)
            if t is None:
                thermal_raw=(path.parent/b['raw']['thermal'][0]['path']).read_bytes()
                t=compute.thermal_decode(thermal_raw)[1] if compute else thermal_decode(thermal_raw)[1]
            initial=np.array(cal['matrix_thermal_to_extended_rgb']);aligned=cv2.warpPerspective(t,initial,size)
            try:
                residual,detail=correct(rgb,aligned,offline_test=offline_test,compute=compute);scale=np.diag([64/size[0],48/size[1],1]);transform=np.linalg.inv(scale)@residual@scale@initial;state='computed'
            except ValueError as rejection:
                transform=initial;detail={'status':'residual rejected; retain explicit initial calibration','reason':str(rejection)};state='initial_calibration'
            record['ai_registration']={'state':state,'backend':'explicit offline INT8 reference' if offline_test else 'PL task 1','thermal_to_extended_rgb':transform.tolist(),'detail':detail,'absolute_registration_accuracy_validated':False}
        except (OSError,KeyError,RuntimeError,ValueError,subprocess.SubprocessError) as e:
            record['ai_registration']={'state':'unavailable','reason':str(e),'silent_software_fallback':False}
    record['compute']={'backend':compute.backend if compute else 'explicit offline PS reference','calls':compute.calls if compute else [],'silent_software_fallback':False}
    record['output_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for pattern in ['temperature.f32','thermal-color.argb','thermal-input.i8','rgb-preview.i8','point-*-psd.f32'] for p in output.glob(pattern)}
    # Atomic publication; consumers must match capture_id and board_id.
    temp=output/'processing.json.tmp';temp.write_text(json.dumps(record,indent=2),encoding='utf8');temp.replace(output/'processing.json');return record
def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--reference',type=Path);p.add_argument('--annotations',type=Path);p.add_argument('--calibration',type=Path);p.add_argument('--offline-test',action='store_true');a=p.parse_args();process(a.bundle,a.output,a.reference,a.offline_test,a.calibration,a.annotations)
if __name__=='__main__':main()
