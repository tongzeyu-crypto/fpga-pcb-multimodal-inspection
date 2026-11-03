"""Take small, traceable raw subsets; no new capture or controller connection."""
from pathlib import Path
import argparse,hashlib,importlib.util,json
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser();p.add_argument('--source-root',type=Path,required=True);a=p.parse_args()
    source=a.source_root;raw=source/'data/raw';bundle=json.loads((raw/'dcdc.bundle.json').read_text())
    spec=importlib.util.spec_from_file_location('source_numerics',source/'runtime/numerics.py');numeric=importlib.util.module_from_spec(spec);spec.loader.exec_module(numeric)
    def verified(entry):
        path=raw/entry['path'];blob=path.read_bytes()
        if hashlib.sha256(blob).hexdigest()!=entry['sha256']:raise ValueError('Original input SHA256 mismatch')
        return path,blob
    thermal=bundle['raw']['thermal'][0];_,blob=verified(thermal);plane=np.frombuffer(blob,'<u2').reshape(2,192,256)[1]
    rgb=bundle['raw']['rgb'][0];path,_=verified(rgb);image=np.asarray(Image.open(path).convert('RGB'));h,w=image.shape[:2]
    rows=np.rint(np.linspace(0,h-1,16)).astype(int);cols=np.rint(np.linspace(0,w-1,16)).astype(int);small=image[np.ix_(rows,cols)].astype(np.uint32)
    groups={}
    for entry in bundle['raw']['adc']:groups.setdefault(entry['point_index'],[]).append(entry)
    xy={tuple(es[0]['mechanical_mm']):n for n,es in groups.items()};xs=sorted({p[0] for p in xy})[:3];ys=sorted({p[1] for p in xy})[:2]
    points=[]
    for y in ys:
        for x in xs:
            number=xy[(x,y)];frames=[]
            for entry in groups[number]:
                path,_=verified(entry);samples=numeric.adc_decode(numeric.read_adc(path))[0,:64].astype(int).tolist()
                frames.append({'samples':samples,'source_path':entry['path'],'source_sha256':entry['sha256'],'source':entry['source'],'source_timestamp':entry['timestamp']})
            if len(frames)!=3:raise ValueError('Three source frames per point required')
            points.append({'point_index':number,'xy_mm':[x,y],'frames':frames})
    inputs={'schema':'PlPsDemoInputs/1','source_board':'dcdc','fresh_capture':False,'hardware_synchronized':False,'fft_size':64,'sample_rate_hz':50000000,
        'thermal':{'shape':[16,16],'raw_kelvin16':plane[::12,::16].ravel().astype(int).tolist(),'source_path':thermal['path'],'source_sha256':thermal['sha256'],'sampling':'rows 0:192:12; columns 0:256:16'},
        'rgb':{'shape':[16,16],'rgb888':((small[:,:,0]<<16)|(small[:,:,1]<<8)|small[:,:,2]).ravel().astype(int).tolist(),'source_path':rgb['path'],'source_sha256':rgb['sha256'],'sampling':'16 evenly spaced rows and columns; fixture preparation only'},'points':points}
    (ROOT/'inputs/demo-inputs.json').write_text(json.dumps(inputs,ensure_ascii=False,indent=2),encoding='utf8');print('PREPARED',len(points),'points, 18 ADC subsets, thermal/RGB 16x16; historical raw only')
if __name__=='__main__':main()
