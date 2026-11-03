"""Regression of the audited integration gaps; no physical device access."""
from pathlib import Path
import argparse,hashlib,inspect,json,shutil,subprocess,sys
import cv2,numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime.neural_frames import NativeRenderer,read_rgb

def main():
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);p.add_argument('--assets',type=Path,required=True);p.add_argument('--cxx',type=Path,required=True);a=p.parse_args();a.work.mkdir(parents=True,exist_ok=True)
    assets=a.work/'assets';shutil.copytree(a.assets,assets,dirs_exist_ok=True);checks={}
    from runtime.motion import GrblMotion
    default=inspect.signature(GrblMotion).parameters['feed'].default
    cfg=json.loads((ROOT/'resources/autostart/motion.json').read_text())
    assert default==cfg['feed']==120
    shutil.copyfile(ROOT/'runtime/grbl_guard.h',a.work/'grbl_guard.h')
    (a.work/'guard.cpp').write_text('#include <cstdio>\n#include "grbl_guard.h"\nint main(){Guard g={};g.origin_valid=g.position_valid=g.units_known=g.configured=1;g.limit_x=70;g.limit_y=44;g.stamp=10;strcpy(g.status,"Idle");return check_move(&g,5,5,120,10)!=NULL||check_move(&g,5,5,600,10)==NULL;}')
    subprocess.run([str(a.cxx),'-O2',str(a.work/'guard.cpp'),'-o',str(a.work/'guard.exe')],check=True);subprocess.run([str(a.work/'guard.exe')],check=True)
    checks['native_guard_accepts_shipped_feed']=True
    from demo.runtime.scan_demo import report_route
    assert len(report_route())==150
    plan=report_route(12,7,2,3);assert len(plan)==28 and plan[-1]['xy_mm']==[0,7]
    assert len(report_route(70,44,2,2))==828
    try:report_route(200,200,.25,.25)
    except ValueError:pass
    else:raise AssertionError('oversize route accepted')
    checks['configurable_inclusive_serpentine_route']=True
    thermal_queries=[]
    with NativeRenderer(ROOT/'bin/demo_reference.exe',assets,a.work/'render') as renderer:
        for board,name in [(1,'dcdc'),(0,'stm32')]:
            folder=assets/('dcdc' if board else '')
            raw=np.fromfile(folder/'temperature-raw.u16','<u2').reshape(192,256)
            renderer.command('app raw_board %d mode 14 cursor_visible 0'%board)
            for x,y in [(0,0),(128,96),(255,191)]:
                value=renderer.command('temperature raw %d %d'%(x,y))['app'];assert value['temperature_valid'] and value['raw_kelvin16']==int(raw[y,x])
                assert abs(value['temperature_c']-(int(raw[y,x])/16-273.15))<1e-5
            renderer.command('pointer 1 605 349 0 0');value=renderer.command('pointer 2 605 349 0 0')['app'];assert value['raw_thermal_xy']==[128,96]
            stats=(folder/'thermal-stats.txt').read_text().split();renderer.command('app hotspot 1');value=renderer.command('dump')['app'];assert value['raw_thermal_xy']==list(map(int,stats[:2]))
            assert not renderer.command('temperature raw -1 0')['app']['temperature_valid']
            lines=(folder/'thermal-map.txt').read_text().splitlines();w,h,scale=map(float,lines[1].split());matrix=np.array([list(map(float,l.split())) for l in lines[2:5]])
            inverse=np.linalg.inv(matrix);point=inverse@np.array([128,96,1]);point/=point[2]
            assert 0<=point[0]<w and 0<=point[1]<h
            value=renderer.command('temperature board %.9g %.9g'%(point[0],point[1]))['app'];assert value['temperature_valid'] and value['raw_thermal_xy']==[128,96]
            # Exercise the real fusion-view mouse hit, not only the query API.
            renderer.command('app mode 1 hud 0 components 0 points 0');ids=np.fromfile(str(renderer.prefix)+'.u16','<u2').reshape(720,1280)
            found=False
            for yy,xx in zip(*np.where(ids<64000)):
                if xx%30 or yy%30:continue
                renderer.command('pointer 1 %d %d 0 0'%(xx,yy));value=renderer.command('pointer 2 %d %d 0 0'%(xx,yy))['app']
                if value['temperature_valid']:found=True;break
            assert found,'no source-valid fusion mouse query on '+name
            thermal_queries.append(dict(board=name,fusion_mouse=True,raw_mouse=True,raw_value_exact=True))
        from runtime.scan_results import publish_scan
        records=[]
        for i,(x,y) in enumerate([(0,0),(5,0),(10,0),(0,5),(5,5),(10,5)]):
            values=[float((i+1)*1e-5)]*2049
            result=dict(output=[int(v*(1<<40)) for v in values],metadata=dict(unit='PSD_Q40',bands_rms_q16=[int((i+1)*(b+1)*65536) for b in range(5)]),backend='explicit fixture')
            records.append(dict(xy_mm=[x,y],mean_power=values,spectrum=result,frames=[]))
        for board,name in [(1,'dcdc'),(0,'stm32')]:
            renderer.command('app raw_board %d mode 15 point 0 band 4 hud 1'%board);before=hashlib.sha256(read_rgb(str(renderer.prefix)+'.argb').tobytes()).hexdigest()
            publish_scan(assets,name,records,'fixture'+name)
            value=renderer.command('dump');assert value['app']['capture_id']=='scan-fixture'+name and value['app']['data_revision']>0
            assert value['measurement']['points']==6 and value['measurement']['bins']==2049 and value['measurement']['max_frequency_hz']==25e6
            assert value['measurement']['selected_rms']==5,'renderer recomputed RMS instead of consuming PL output'
            assert abs(value['measurement']['last_psd']-1e-5)<1e-10
            after=hashlib.sha256(read_rgb(str(renderer.prefix)+'.argb').tobytes()).hexdigest();assert after!=before
            for mode in [0,3,6]:renderer.command('app mode '+str(mode))
        checks['completed_scan_updates_original_views_and_pl_rms']=True
    checks['two_board_temperature_queries']=thermal_queries
    from runtime.aoi_annotation import load_annotations,assess
    source=(ROOT/'data/raw/dcdc-rgb-thermal/rgb.jpg').read_bytes();annotation=load_annotations(source);assert annotation is not None
    photo=cv2.imdecode(np.frombuffer(source,np.uint8),0);encoded=cv2.imencode('.jpg',photo,[cv2.IMWRITE_JPEG_QUALITY,93])[1].tobytes()
    moved=load_annotations(encoded);assert moved is not None and moved['source_rgb_sha256']==hashlib.sha256(encoded).hexdigest() and moved.get('transfer')
    # Use the actual source-bound U1 lead row. Synthetic bridge pixels are
    # deliberate test mutations, never stored as physical defect evidence.
    rect=cv2.warpPerspective(photo,np.array(annotation['native_to_board']),(1500,1100));local=json.loads(json.dumps(annotation));local['native_to_board']=np.eye(3).tolist()
    normal,coverage,_=assess(rect,rect,np.ones_like(rect),local,1,np.eye(3))
    assert not any(f['kind']=='pin_bridge_candidate' for f in normal),'unchanged source triggered bridge'
    rows=[r for r in coverage if r['component']=='U1' and r['state']=='lead_row_assessed'];assert rows and len(rows[0]['visible_lead_peaks'])>=3
    changed=rect.copy();spec=next(c for c in local['components'] if c['id']=='U1')['pins']['rows'][0];q=np.array(spec['quad_px'],np.float32)
    cv2.line(changed,tuple(np.rint(q[0]+[15,40]).astype(int)),tuple(np.rint(q[0]+[225,40]).astype(int)),240,12)
    findings,_,_=assess(rect,changed,np.ones_like(rect),local,1,np.eye(3))
    assert any(f['component']=='U1' and f['kind']=='pin_bridge_candidate' for f in findings)
    assert all('quad_board'in f and 'quad_test_native'in f and 'quad_reference_native'in f for f in findings)
    checks['dcdc_real_lead_row_and_synthetic_bridge']=dict(visible_peaks=rows[0]['visible_lead_peaks'],all_coordinate_spaces=True)
    checks['reencoded_reference_annotation_transfer']=True
    from runtime.calibration import publish,resolve
    from runtime.capture_bundle import load
    portable=a.work/'portable';portable.mkdir(exist_ok=True)
    for name in ['dcdc','stm32']:
        path=ROOT/'data/raw'/(name+'.bundle.json');bundle=load(path,name);_,cal=resolve(bundle,path);target=portable/name;target.mkdir(exist_ok=True);publish(bundle,target,cal)
        _,resolved=resolve(bundle,target/'capture.bundle.json');assert resolved==target/'calibration.json'
    checks['flat_fresh_bundle_calibration_resolves']=True
    from runtime.adc_sampler import AdcSampler
    from unittest.mock import patch
    import time
    class Motion:
        def status(self):return dict(ack=True,state='Idle',xy_mm=[5.,4.],reported_at=time.monotonic(),controller={'status':'Idle'})
    class Decoder:
        def decode_adc_lists(self,words):assert len(words)==16384;return [[0]*4096,[1]*4096]
    calls=[]
    def capture_batch(command,**kwargs):
        assert command[-2:]==['--frames','3'];calls.append(command);prefix=command[2];now=time.monotonic_ns();frames=[]
        for i in range(3):
            name=prefix+'-'+str(i)+'.u32';Path(name).write_bytes(bytes(65536));frames.append(dict(file=name,frame_index=i,generation=i+1,bank=i%2,sample_tick_begin=i*20000,sample_tick_end=i*20000+16383,ready_observed_ns=now,copy_done_ns=now))
        return subprocess.CompletedProcess(command,0,json.dumps(dict(backend='ADC_PINGPONG_V2',trigger_ns=now,frames=frames)).encode(),b'')
    sampler=AdcSampler(Motion(),Decoder(),a.work/'adc-batch')
    with patch('runtime.adc_sampler.subprocess.run',capture_batch):frames=[sampler.capture(dict(point_index=0,xy_mm=[5,4]),i) for i in range(3)]
    assert len(calls)==1 and [f['adc']['generation'] for f in frames]==[1,2,3]
    fresh=dict(records[0],xy_mm=[5,4],reported_xy_mm=[5,4],source_point_index=0,frames=frames)
    from runtime.scan_results import publish_scan
    publish_scan(assets,'dcdc',[fresh],'fixturemerged',ROOT/'data/raw/dcdc.bundle.json')
    bundle=load(assets/'dcdc/scan-results/fixturemerged/capture.bundle.json','dcdc');assert len(bundle['raw']['adc'])==3 and bundle['raw']['adc'][0]['mechanical_mm']==[5,4]
    checks['batch_three_frames_and_merged_portable_bundle']=True
    result=dict(passed=True,checks=checks,physical_devices_opened=False,synthetic_mutations_are_test_fixtures=True,source_sha256={q.relative_to(ROOT).as_posix():hashlib.sha256(q.read_bytes()).hexdigest() for folder in ['runtime','resources/annotations','resources/calibration'] for q in (ROOT/folder).rglob('*') if q.suffix in {'.py','.h','.cpp','.json'} and '__pycache__' not in q.parts})
    e=ROOT/'evidence/report-fixes';e.mkdir(exist_ok=True);(e/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(checks,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
