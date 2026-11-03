"""Recreate full-sized demo inputs from the supplied source-bound raw records."""
from pathlib import Path
import csv,hashlib,json,struct
import cv2,numpy as np
ROOT=Path(__file__).resolve().parents[1]
def main():
    r=ROOT;o=json.loads((r/'demo/inputs/demo-inputs.json').read_text());o['schema']='PlPsDemoInputs/2';o['fft_size']=4096
    for point in o['points']:
        for i,frame in enumerate(point['frames']):
            path=r/'data/raw/dcdc-adc/points'/('point-%05d'%point['point_index'])/('capture_%02d.csv'%i)
            with path.open(encoding='utf-8-sig',newline='') as f:
                reader=csv.reader(f);header=next(reader);col=next(j for j,n in enumerate(header) if 'capture_word' in n);words=[int(row[col],16) for row in reader if row and row[0].isdigit()]
            samples=[(w&16383)-16384 if (w&16383)>=8192 else w&16383 for w in words if ((w>>15)&3)==1]
            if len(samples)!=4096:raise ValueError('source frame size')
            frame.update(samples=samples,source_path=path.relative_to(r).as_posix(),source_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    path=r/'data/raw/dcdc-rgb-thermal/thermal.raw';raw=path.read_bytes();o['thermal'].update(shape=[192,256],raw_kelvin16=list(struct.unpack('<49152H',raw[98304:])),source_path=path.relative_to(r).as_posix(),source_sha256=hashlib.sha256(raw).hexdigest(),sampling='all 192 rows and 256 columns of the temperature plane')
    path=r/'data/raw/dcdc-rgb-thermal/rgb.jpg';image=cv2.imdecode(np.frombuffer(path.read_bytes(),np.uint8),1);image=cv2.resize(image,(256,192),interpolation=cv2.INTER_AREA)[...,::-1].astype(np.uint32);packed=(image[...,0]<<16)|(image[...,1]<<8)|image[...,2]
    o['rgb'].update(shape=[192,256],rgb888=packed.reshape(-1).tolist(),source_path=path.relative_to(r).as_posix(),source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),sampling='PS offline JPEG decode and area resize to 256x192; every resulting pixel enters PL')
    (r/'demo/inputs/full-inputs.json').write_text(json.dumps(o,separators=(',',':')))
if __name__=='__main__':main()
