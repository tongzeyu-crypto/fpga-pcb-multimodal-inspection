"""Generate display derivatives from a verified raw bundle; no result import.

Static glyph/cursor regions are extracted once from an existing program atlas.
RGB, temperature and all spectra are recomputed from bundle raw input every run.
"""
from pathlib import Path
import argparse,gzip,hashlib,json,struct,sys,shutil,datetime
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime.capture_bundle import load
from runtime.numerics import thermal_decode,spectrum_three
def pack(a,premultiplied=False):
    a=a.copy()
    if not premultiplied:a[...,:3]=((a[...,:3].astype(np.uint32)*a[...,3:4]+127)//255).astype(np.uint8)
    payload=bytearray()
    while True:
        h,w=a.shape[:2];pad=np.pad(a,((0,(-h)%4),(0,(-w)%8),(0,0)),mode='edge');hh,ww=pad.shape[:2]
        payload.extend(b'\0'*((-len(payload))%128));payload.extend(pad.reshape(hh//4,2,2,ww//8,4,2,4).transpose(0,3,1,4,2,5,6).tobytes())
        if w==h==1:break
        a=cv2.resize(a,(max(1,w//2),max(1,h//2)),interpolation=cv2.INTER_AREA)
    payload.extend(b'\0'*((-len(payload))%128));return payload
def texture(path,a,premultiplied=False):
    with gzip.GzipFile(filename=str(path)+'.gz',mode='wb',mtime=0) as f:f.write(pack(a,premultiplied))
def import_ui(source):
    dest=ROOT/'resources/ui';dest.mkdir(parents=True,exist_ok=True)
    g=(source/'glyphs.bin').read_bytes();(dest/'glyphs.bin').write_bytes(g)
    raw=np.fromfile(source/'ui.bin',np.uint8,count=2048*2048*4).reshape(512,256,2,4,2,2,4).transpose(0,2,4,1,3,5,6).reshape(2048,2048,4)
    clean=np.zeros_like(raw)
    for code,x,y,w,h,adv,res in struct.iter_unpack('<I6H',g):clean[y:y+h,x:x+w]=raw[y:y+h,x:x+w]
    clean[1488:1536,1984:2016]=raw[1488:1536,1984:2016]
    texture(dest/'ui.bin',clean,True)
    (dest/'provenance.json').write_text(json.dumps({'purpose':'program glyphs and cursor only','source_glyph_sha256':hashlib.sha256(g).hexdigest(),'measurement_photo_regions_copied':False},indent=2))
def command(vertices,uv,oid=0,color=0xffffffff,textured=True):
    b=struct.pack('<4I',1|(256|512 if textured else 0),color,oid,0)
    for v,t in zip(vertices,uv):b+=struct.pack('<3iI',*np.rint(np.array(v)*65536).astype(int),int(round(t[0]*65535))|(int(round(t[1]*65535))<<16))
    return b
def publish_aoi(dest,bundle,raw,processing,reference):
    info=processing['modalities'].get('rgb',{})
    if info.get('state')!='rule-screened' or reference is None:return
    if hashlib.sha256(reference.read_bytes()).hexdigest()!=info['reference_sha256']:raise ValueError('AOI reference identity mismatch')
    result=info['result'];ref=cv2.imdecode(np.frombuffer(reference.read_bytes(),np.uint8),cv2.IMREAD_COLOR);test=cv2.imdecode(np.frombuffer((raw/bundle['raw']['rgb'][0]['path']).read_bytes(),np.uint8),cv2.IMREAD_COLOR);h,w=ref.shape[:2]
    aligned=cv2.warpPerspective(test,np.array(result['test_native_to_reference']),(w,h));th=min(1024,max(1,round(1024*h/w)));view=cv2.resize(aligned,(1024,th));root=dest/'aoi-display';root.mkdir(exist_ok=True)
    run=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+hashlib.sha256((bundle['capture_id']+info['reference_sha256']).encode()).hexdigest()[:6];folder=root/run;folder.mkdir(exist_ok=True)
    for name,image in [('rgb',view),('gray',cv2.cvtColor(cv2.cvtColor(view,cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR))]:
        atlas=np.zeros((1024,1024,4),np.uint8);atlas[:th,:,:3]=image;atlas[:th,:,3]=255;(folder/(name+'.bin')).write_bytes(pack(atlas))
    regions=result['regions'][:64];lines=['AOI1_8X4',f'{run} {w} {h} {th} {len(regions)} {result["state"]}']
    for r in regions:
        x,y,bw,bh=r['reference_native_xywh'];lines.append(f'{x} {y} {bw} {bh}\tVisible change\tReview')
    (folder/'display.txt').write_text('\n'.join(lines)+'\n');(folder/'provenance.json').write_text(json.dumps({'capture_id':bundle['capture_id'],'board_id':bundle['board_id'],'test_sha256':info['test_sha256'],'reference_sha256':info['reference_sha256'],'algorithm':result['algorithm'],'real_defect_validation_complete':False},indent=2))
    (root/'current.txt').write_text(run+'\n');(root/'status.txt').write_text('READY\n')
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--bundle',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--ui-source',type=Path);ap.add_argument('--reference',type=Path);ap.add_argument('--processing',type=Path);ap.add_argument('--geometry-source',type=Path);a=ap.parse_args()
    if a.ui_source:import_ui(a.ui_source)
    if a.geometry_source:
        for name,src in [('stm32',a.geometry_source),('dcdc',a.geometry_source/'dcdc')]:
            for kind in ['model','flat']:
                dest=ROOT/'resources/models'/(name+'-'+kind+'.commands.bin');shutil.copyfile(src/(kind+'.bin'),dest)
    b=load(a.bundle);out=a.output;out.mkdir(parents=True,exist_ok=True);raw=a.bundle.parent;processing=None
    if a.processing:
        processing=json.loads(a.processing.read_text(encoding='utf8'));hashes={i['path']:i['sha256'] for items in b['raw'].values() for i in items}
        if processing['capture_id']!=b['capture_id'] or processing['board_id']!=b['board_id'] or processing['raw_input_hashes']!=hashes:raise ValueError('processing/capture identity mismatch')
    # Two board directories always exist; STM32 remains an explicit empty state.
    ui=np.frombuffer(gzip.decompress((ROOT/'resources/ui/ui.bin.gz').read_bytes()),np.uint8) # complete mip bytes
    glyph=(ROOT/'resources/ui/glyphs.bin').read_bytes()
    for board,dest in [('stm32',out),('dcdc',out/'dcdc')]:
        dest.mkdir(exist_ok=True);shutil.copyfile(ROOT/'resources/ui/ui.bin.gz',dest/'ui.bin.gz');(dest/'glyphs.bin').write_bytes(glyph);(dest/'texture-8x4.flag').write_text('8x4 tile mips\n')
        blank=np.zeros((2048,2048,4),np.uint8);color=blank.copy();heat=blank.copy();layouts=np.zeros((5,4),float);modeldata=b'';flatdata=b''
        points=np.array([[0,0,0,0,np.nan]],np.float32);psd=np.zeros((1,2),np.float32);avail=0;nx=ny=1;capture='MISSING-stm32'
        if board==b['board_id'] and not(board=='dcdc' and b['raw'].get('rgb') and b['raw'].get('thermal')):
            capture=b['capture_id'];atlas=np.zeros((2048,2048,4),np.uint8)
            if b['raw'].get('rgb'):
                rgb=cv2.imdecode(np.frombuffer((raw/b['raw']['rgb'][0]['path']).read_bytes(),np.uint8),cv2.IMREAD_COLOR)
                if rgb is None:raise ValueError('captured RGB decode')
                small=cv2.resize(rgb,(640,507));atlas[800:1307,:640,:3]=small;atlas[800:1307,:640,3]=255;layouts[2 if board=='dcdc' else 1]=[0,800,640,507];avail|=1
                if a.reference:
                    ref=cv2.imdecode(np.frombuffer(a.reference.read_bytes(),np.uint8),cv2.IMREAD_COLOR)
                    if ref is None:raise ValueError('reference decode')
                    atlas[800:1307,700:1340,:3]=cv2.resize(ref,(640,507));atlas[800:1307,700:1340,3]=255;layouts[0]=[700,800,640,507]
            if b['raw'].get('thermal'):
                _,temp=thermal_decode((raw/b['raw']['thermal'][0]['path']).read_bytes());ct=np.clip((temp-np.percentile(temp,1))/max(np.ptp(temp),.01)*255,0,255).astype(np.uint8);th=cv2.applyColorMap(ct,cv2.COLORMAP_TURBO)
                atlas[1400:1592,:256,:3]=th;atlas[1400:1592,:256,3]=255;layouts[4 if board=='dcdc' else 3]=[0,1400,256,192];avail|=2
            groups={}
            for entry in b['raw'].get('adc',[]):groups.setdefault(entry['point_index'],[]).append(entry)
            if groups:
                rows=[(es[0]['mechanical_mm'],spectrum_three([raw/e['path'] for e in es])[0]) for idx,es in sorted(groups.items())];rows.sort(key=lambda r:(r[0][1],r[0][0]));coords=np.array([r[0] for r in rows],np.float32);psd=np.array([r[1] for r in rows],np.float32);nx=len(np.unique(coords[:,0]));ny=len(np.unique(coords[:,1]))
                if nx*ny!=len(rows):raise ValueError('incomplete mechanical grid; waiting for a complete scan')
                points=np.c_[coords,coords[:,0],coords[:,1],np.full(len(rows),np.nan)].astype(np.float32);coords.astype('<f4').tofile(dest/'raw-dcdc-coordinates.f32');psd.astype('<f4').tofile(dest/'raw-dcdc-psd.f32');np.fft.rfftfreq(4096,1/50e6).astype('<f4').tofile(dest/'raw-dcdc-frequency.f32');avail|=4
            base=np.frombuffer(ui[:2048*2048*4],np.uint8).reshape(512,256,2,4,2,2,4).transpose(0,2,4,1,3,5,6).reshape(2048,2048,4);mask=base[...,3]>0;atlas[mask]=base[mask];texture(dest/'ui.bin',atlas,True)
        if board==b['board_id']=='dcdc' and b['raw'].get('rgb') and b['raw'].get('thermal'):
            capture=b['capture_id'];model=json.loads((ROOT/'resources/models/model-v3.json').read_text(encoding='utf8'));geo=model['board_geometry'];w,h=geo['rectified_size_px'];margin=geo['extended_margin_px'];size=(w+2*margin,h+2*margin)
            rpath=raw/b['raw']['rgb'][0]['path'];rgb=cv2.imdecode(np.frombuffer(rpath.read_bytes(),np.uint8),cv2.IMREAD_COLOR)
            transform=np.array(geo['native_rgb_to_board']);transform[0]+=margin*transform[2];transform[1]+=margin*transform[2]
            rect=cv2.warpPerspective(rgb,transform,size);rect=rect[margin:margin+h,margin:margin+w];color[:h,:w,:3]=rect;color[:h,:w,3]=255
            _,temp=thermal_decode((raw/b['raw']['thermal'][0]['path']).read_bytes());calpath=raw/'dcdc-rgb-thermal/thermal-calibration.json'
            if not calpath.exists():calpath=ROOT/'resources/calibration/dcdc-initial.json'
            cal=json.loads(calpath.read_text());ct=np.clip((temp-np.percentile(temp,1))/max(np.ptp(temp),.01)*255,0,255).astype(np.uint8);th=cv2.applyColorMap(ct,cv2.COLORMAP_TURBO)
            thermal_h=np.array(cal['matrix_thermal_to_extended_rgb'])
            if processing and processing['ai_registration']['state']=='computed':thermal_h=np.array(processing['ai_registration']['thermal_to_extended_rgb'])
            th=cv2.warpPerspective(th,thermal_h,size)[margin:margin+h,margin:margin+w];heat[:h,:w,:3]=th;heat[:h,:w,3]=255
            # Original test image and raw thermal preview in the UI's image atlas.
            atlas=np.zeros((2048,2048,4),np.uint8)
            small=cv2.resize(rgb,(640,507));atlas[800:1307,:640,:3]=small;atlas[800:1307,:640,3]=255;layouts[2]=[0,800,640,507]
            thermal=cv2.applyColorMap(ct,cv2.COLORMAP_TURBO);atlas[1400:1592,:256,:3]=thermal;atlas[1400:1592,:256,3]=255;layouts[4]=[0,1400,256,192]
            if a.reference:
                ref=cv2.imdecode(np.frombuffer(a.reference.read_bytes(),np.uint8),cv2.IMREAD_COLOR)
                if ref is None:raise ValueError('normal reference decode')
                ref=cv2.resize(ref,(640,507));atlas[800:1307,700:1340,:3]=ref;atlas[800:1307,700:1340,3]=255;layouts[0]=[700,800,640,507]
            # Add program glyphs after measurement regions; atlas only changes per bundle.
            base=np.frombuffer(ui[:2048*2048*4],np.uint8).reshape(512,256,2,4,2,2,4).transpose(0,2,4,1,3,5,6).reshape(2048,2048,4)
            mask=base[...,3]>0;atlas[mask]=base[mask];texture(dest/'ui.bin',atlas,True)
            scale=100/w
            def vertex(x,y,z):return [(x-w/2)*scale,y*scale,(z-h/2)*scale]
            uv=np.array([[0,0],[w-1,0],[w-1,h-1],[0,h-1]])/2047
            plane=np.array([vertex(0,0,0),vertex(w,0,0),vertex(w,0,h),vertex(0,0,h)])
            for tri in [(0,1,2),(0,2,3)]:flatdata+=command(plane[list(tri)],uv[list(tri)])
            modeldata=flatdata
            for i,c in enumerate(model['components']):
                x,z,cw,ch=c['bbox'];y=c['height'];vv=np.array([vertex(x,0,z),vertex(x+cw,0,z),vertex(x+cw,0,z+ch),vertex(x,0,z+ch),vertex(x,y,z),vertex(x+cw,y,z),vertex(x+cw,y,z+ch),vertex(x,y,z+ch)])
                tuv=np.clip(np.array([[x,z],[x+cw,z],[x+cw,z+ch],[x,z+ch],[x,z],[x+cw,z],[x+cw,z+ch],[x,z+ch]])/2047,0,1)
                for tri in [(4,5,6),(4,6,7),(0,1,5),(0,5,4),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]:modeldata+=command(vv[list(tri)],tuv[list(tri)],i+1)
            # Preserve the mature prebuilt mesh topology when supplied. UV is
            # recomputed against this bundle's fresh RGB/thermal atlas.
            for kind in ['model','flat']:
                src=ROOT/'resources/models'/('dcdc-'+kind+'.commands.bin')
                if src.exists():
                    converted=bytearray(src.read_bytes())
                    for off in range(0,len(converted),64):
                        flags=struct.unpack_from('<I',converted,off)[0];struct.pack_into('<I',converted,off,(flags&~1024)|256|512)
                        for vi in range(3):
                            x,y,z,_=struct.unpack_from('<3iI',converted,off+16+16*vi);u=np.clip((x/65536/100+.5)*(w-1)/2047,0,1);v=np.clip((z/65536/(100*h/w)+.5)*(h-1)/2047,0,1)
                            struct.pack_into('<I',converted,off+28+16*vi,int(round(u*65535))|(int(round(v*65535))<<16))
                    if kind=='model':modeldata=bytes(converted)
                    else:flatdata=bytes(converted)
            groups={}
            for entry in b['raw'].get('adc',[]):groups.setdefault(entry['point_index'],[]).append(entry)
            rows=[]
            for idx,entries in sorted(groups.items()):
                xy=entries[0]['mechanical_mm'];p=spectrum_three([raw/e['path'] for e in entries])[0]
                rows.append((xy,p))
            avail=27 if processing and processing['ai_registration']['state']=='computed' else 11
            if rows:
                rows.sort(key=lambda r:(r[0][1],r[0][0]));coords=np.array([r[0] for r in rows],np.float32);psd=np.array([r[1] for r in rows],np.float32);nx=len(np.unique(coords[:,0]));ny=len(np.unique(coords[:,1]))
                # Explicit millimetre world coordinates; no registration to RGB/model.
                points=np.c_[coords,coords[:,0],coords[:,1],np.full(len(rows),np.nan)].astype(np.float32)
                coords.astype('<f4').tofile(dest/'raw-dcdc-coordinates.f32');psd.astype('<f4').tofile(dest/'raw-dcdc-psd.f32');np.fft.rfftfreq(4096,1/50e6).astype('<f4').tofile(dest/'raw-dcdc-frequency.f32');avail|=4
            (dest/'dcdc.flag').write_text('real raw replay or live USB\n')
        for name,image in [('color',color),('gray',color.copy()),('line',color.copy()),('thermal',heat)]:
            if name=='gray':image[...,:3]=cv2.cvtColor(color[...,:3],cv2.COLOR_BGR2GRAY)[...,None]
            if name=='line':image[...,:3]=np.where(cv2.cvtColor(color[...,:3],cv2.COLOR_BGR2GRAY)[...,None]>100,230,20)
            texture(dest/(name+'.bin'),image)
        (dest/'model.bin').write_bytes(modeldata);(dest/'flat.bin').write_bytes(flatdata);points.astype('<f4').tofile(dest/'points.f32');np.stack([psd,psd]).astype('<f4').tofile(dest/'psd.f32')
        # Both planes refer to the same single scan; no invented before/after.
        np.array([0x48444631,len(modeldata)//64,len(flatdata)//64,len(points),psd.shape[1],nx,ny,len(glyph)//16,0,0,0,0],'<u4').tofile(dest/'full.meta');np.savetxt(dest/'raw-layout.txt',layouts,fmt='%g');(dest/'frequency.txt').write_text(f'{50e6/4096} 25\n');(dest/'capture-state.txt').write_text(f'{avail} {capture}\n')
        (dest/'aoi-display').mkdir(exist_ok=True);(dest/'aoi-display/status.txt').write_text('EMPTY\n')
        if board==b['board_id'] and processing:publish_aoi(dest,b,raw,processing,a.reference)
    (out/'generation.json').write_text(json.dumps({'capture_id':b['capture_id'],'board_id':b['board_id'],'raw_hashes':{i['path']:i['sha256'] for items in b['raw'].values() for i in items},'mechanical_to_model_registration':None,'thermal_registration':'manual approximate prior plus explicitly computed residual if present; not accuracy calibrated','missing_inputs':'pages are disabled per available modality; no cross-board fallback','geometry':'retained prebuilt command mesh where supplied, otherwise component box prior; not measured reconstruction'},indent=2))
    print('Generated source-bound display derivatives')
if __name__=='__main__':main()
