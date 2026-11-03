"""Publish one completed scan atomically to the original renderer and a bundle.

No missing positions are filled with invented measurements. A partial/cancelled
run stays in the scan journal; the last complete map remains separately named.
"""
from pathlib import Path
import json,math,shutil,struct
from demo.runtime.hashutil import sha256
from .bands import UI_BANDS_HZ

def floats(path,values):
    values=list(values);path.write_bytes(struct.pack('<%df'%len(values),*values))

def publish_scan(display_root,board,records,run_id,base_bundle=None,calibration=None):
    if board not in ('dcdc','stm32') or not run_id.isalnum() or not records:raise ValueError('scan publication identity')
    folder=Path(display_root)/('dcdc' if board=='dcdc' else '')
    root=folder/'scan-results';root.mkdir(exist_ok=True);dest=root/run_id
    dest.mkdir(exist_ok=False)
    ordered=sorted(records,key=lambda r:(r['xy_mm'][1],r['xy_mm'][0]))
    xs=sorted({r['xy_mm'][0] for r in ordered});ys=sorted({r['xy_mm'][1] for r in ordered})
    if len(xs)*len(ys)!=len(ordered) or len(ordered)>1024:raise ValueError('complete rectangular scan required')
    spectra=[];points=[];rms=[];bins=len(ordered[0]['mean_power'])
    if bins!=2049:raise ValueError('full 4096 point FFT required')
    channels=min(len(r.get('channel_spectra',[r['spectrum']])) for r in ordered)
    for record in ordered:
        values=record['mean_power']
        if len(values)!=bins or any(not math.isfinite(v) or v<0 for v in values):raise ValueError('scan spectrum values')
        spectra+=values;points.extend([*record['xy_mm'],*record['xy_mm'],float('nan')])
        metadata=record['spectrum']['metadata']
        if metadata.get('unit')=='PSD_Q40':
            q=metadata.get('bands_rms_q16')
            if not q or len(q)!=5:raise ValueError('PL RMS outputs missing')
            rms.extend(v/65536 for v in q)
        else:
            # Explicit historical PC replay; never used for a PDP3 result.
            df=50000000/4096
            rms.extend(math.sqrt(sum(v for k,v in enumerate(values) if lo<=k*df<hi)*df) for lo,hi in UI_BANDS_HZ)
    floats(dest/'points.f32',points);floats(dest/'psd.f32',spectra+spectra)
    floats(dest/'raw-dcdc-psd.f32',spectra);floats(dest/'band-rms.f32',rms)
    floats(dest/'raw-dcdc-coordinates.f32',[v for r in ordered for v in r['xy_mm']])
    floats(dest/'raw-dcdc-frequency.f32',[k*50000000/4096 for k in range(bins)])
    full=[]
    for channel in range(channels):
        for r in ordered:
            result=r.get('channel_spectra',[r['spectrum']])[channel]
            full.extend(v/(1<<40) for v in result['output']) if result['metadata'].get('unit')=='PSD_Q40' else full.extend(r['mean_power'])
    floats(dest/'channels-psd.f32',full)
    if base_bundle and all(f.get('fresh_capture') for r in records for f in r['frames']):
        from .capture_bundle import load
        source=Path(base_bundle);bundle=load(source,board);bundle=json.loads(json.dumps(bundle))
        for kind in ('rgb','thermal'):
            for i,item in enumerate(bundle['raw'].get(kind,[])):
                target=Path('media')/(kind+'-'+str(i)+Path(item['path']).suffix);(dest/target).parent.mkdir(exist_ok=True)
                shutil.copyfile(source.parent/item['path'],dest/target);item['path']=target.as_posix()
        from .calibration import resolve,publish
        _,cal=resolve(bundle,source,calibration);publish(bundle,dest,cal)
        bundle['raw']['adc']=[];bundle['capture_id']=board+'-scan-'+run_id;bundle['acquisition_batches'].append(run_id)
        bundle['synchronization']='camera snapshots retain their source timestamps; ADC acquired at confirmed mechanical positions, not hardware-synchronized across modalities'
        for r in records:
            for n,f in enumerate(r['frames']):
                target=Path('adc')/('point-%05d'%r['source_point_index'])/('frame-%d.u32'%n);(dest/target).parent.mkdir(parents=True,exist_ok=True)
                blob=Path(f['source_path']).read_bytes()
                if sha256(blob).hexdigest()!=f['source_sha256']:raise ValueError('captured ADC source hash changed')
                (dest/target).write_bytes(blob)
                bundle['raw']['adc'].append(dict(path=target.as_posix(),sha256=f['source_sha256'],source='ZYNQ_ADC_AXI_RAW',timestamp={'monotonic_s':f['source_timestamp'],'sample_ticks':f.get('adc',{})},dimensions=[16384],unit='uint32 raw packed ADC words',batch_id=run_id,point_index=r['source_point_index'],frame_index=n,mechanical_mm=r['reported_xy_mm'],commanded_mm=r['xy_mm']))
        (dest/'capture.bundle.json').write_text(json.dumps(bundle,indent=2),encoding='utf8')
    manifest=dict(schema='CompletedScan/1',board_id=board,capture_id=board+'-scan-'+run_id,points=len(ordered),bins=bins,nx=len(xs),ny=len(ys),channels=channels,bands_hz=UI_BANDS_HZ,measurement_backend=ordered[0]['spectrum'].get('backend'),files={p.name:sha256(p.read_bytes()).hexdigest() for p in dest.glob('*.f32')})
    (dest/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    (dest/'ready.txt').write_text('SCAN1 %s %d %d %d %d\n'%(run_id,len(ordered),bins,len(xs),len(ys)))
    pointer=folder/'scan-current.tmp';pointer.write_text(run_id+'\n');pointer.replace(folder/'scan-current.txt')
    return manifest
