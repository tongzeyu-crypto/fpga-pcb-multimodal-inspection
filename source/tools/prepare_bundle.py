from pathlib import Path
import json,sys,hashlib,argparse
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime.numerics import thermal_decode,spectrum_three,bands
from runtime.capture_bundle import load
def main():
    a=argparse.ArgumentParser();a.add_argument('--reference-adc',type=Path);a.add_argument('--reference-thermal',type=Path);args=a.parse_args()
    raw=ROOT/'data/raw';cap=json.loads((raw/'dcdc-rgb-thermal/capture.json').read_text());entries={'rgb':[],'thermal':[],'adc':[]}
    if cap['rgb']['source']!='ZYNQ_USB_REAL' or cap['thermal']['source']!='ZYNQ_USB_REAL':raise ValueError('capture metadata is not Zynq USB acquisition')
    for name,key in [('rgb.jpg','rgb_sha256'),('thermal.raw','thermal_raw_sha256')]:
        if hashlib.sha256((raw/'dcdc-rgb-thermal'/name).read_bytes()).hexdigest()!=cap[key]:raise ValueError('original capture metadata hash mismatch')
    scan=json.loads((raw/'dcdc-adc/session.json').read_text())
    if scan['sample_rate_hz_nominal']!=50_000_000 or scan['samples_per_phase_per_frame']!=4096 or scan['frames_per_point']!=3:raise ValueError('unexpected original ADC acquisition configuration')
    def item(p,source,ts,dims,unit,batch,**extra):
        return {'path':p.relative_to(raw).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'source':source,'timestamp':ts,'dimensions':dims,'unit':unit,'batch_id':batch,**extra}
    entries['rgb'].append(item(raw/'dcdc-rgb-thermal/rgb.jpg','ZYNQ_USB_REAL',{'v4l2_us':cap['rgb']['v4l2_timestamp_us'],'clock':'board-monotonic'},[3040,3840,3],'uint8 RGB','dcdc-rgbthermal-20261029'))
    entries['thermal'].append(item(raw/'dcdc-rgb-thermal/thermal.raw','ZYNQ_USB_REAL',{'v4l2_us':cap['thermal']['v4l2_timestamp_us'],'clock':'board-monotonic'},[2,192,256],'uint16 LE: plane1 Kelvin*16','dcdc-rgbthermal-20261029'))
    maxerr=0;count=0;pointinfo=[]
    derived=ROOT/'data/derived/offline-recomputed';derived.mkdir(parents=True,exist_ok=True)
    _,temp=thermal_decode((raw/'dcdc-rgb-thermal/thermal.raw').read_bytes());temp.tofile(derived/'temperature.f32')
    for folder in sorted((raw/'dcdc-adc/points').glob('point-*')):
        meta=json.loads((folder/'point.json').read_text());paths=sorted(folder.glob('capture_*.csv'))
        adcmeta=json.loads((folder/'capture_metadata.json').read_text())
        if adcmeta['design']!='adc_bringup_50m_psirq_v3' or adcmeta['layout']!='packed32_v1':raise ValueError('unexpected ADC raw provenance/layout')
        if len(paths)!=3:raise ValueError('missing ADC frame')
        p=spectrum_three(paths);p.astype('<f4').tofile(derived/(folder.name+'-psd.f32'));count+=len(paths)
        if args.reference_adc:
            ref=np.load(args.reference_adc/'points'/folder.name/'spectrum.npz')
            old=np.stack([ref['INA_psd'].mean(0),ref['INB_psd'].mean(0)])
            err=float(np.max(np.abs(p-old)));maxerr=max(err,maxerr)
            if not np.allclose(p,old,rtol=1e-11,atol=1e-14):raise ValueError('ADC recomputation mismatch')
        for path in paths:entries['adc'].append(item(path,'ZYNQ_ADC_ILA_RAW',meta['time'],[16384],'packed32_v1 raw ADC codes','dcdc-scan-20261028',point_index=meta['index'],mechanical_mm=[meta['left_mm'],meta['away_mm']]))
        pointinfo.append({'point_index':meta['index'],'xy_mm':[meta['left_mm'],meta['away_mm']],'bands_rms_codes':bands(p)})
    therr=None
    if args.reference_thermal:
        ref=np.load(args.reference_thermal);keys=list(ref.keys());matches=[k for k in keys if ref[k].shape==temp.shape and np.allclose(ref[k],temp,atol=1e-5)]
        if not matches:raise ValueError('thermal recomputation mismatch')
        therr=float(np.max(np.abs(ref[matches[0]]-temp)))
    bundle={'schema':'CaptureBundle/1','board_id':'dcdc','capture_id':'dcdc-replay-rgbthermal-20261029-adc-20261028','calibration_version':'manual-thermal-20261029; mechanical-ruler-20261028; NOT-metrology','acquisition_batches':['dcdc-rgbthermal-20261029','dcdc-scan-20261028'],'synchronization':'RGB/thermal sequential; ADC different date/batch, not a synchronized multimodal snapshot','raw':entries}
    (raw/'dcdc.bundle.json').write_text(json.dumps(bundle,indent=2),encoding='utf8');load(raw/'dcdc.bundle.json','dcdc')
    (ROOT/'evidence/raw-recomputation.json').write_text(json.dumps({'adc_frames':count,'points':len(pointinfo),'adc_max_absolute_psd_difference':maxerr if args.reference_adc else None,'thermal_max_absolute_difference_c':therr,'temperature_min_c':float(temp.min()),'temperature_max_c':float(temp.max()),'used_precomputed_measurement_as_input':False,'point_bands':pointinfo},indent=2))
    print('Raw recomputation passed',count,'frames',len(pointinfo),'points')
if __name__=='__main__':main()
