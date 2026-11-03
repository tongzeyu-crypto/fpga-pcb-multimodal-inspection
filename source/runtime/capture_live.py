"""ARM-local fresh USB acquisition. This module is never run by offline tools."""
from pathlib import Path
import argparse,hashlib,json,os,platform,selectors,struct,subprocess,time
from .numerics import thermal_decode
ROOT=Path(__file__).resolve().parents[1]
def camera(device,width,height,raw,out):
    cmd=[str(ROOT/'bin/camera_stream'),device,str(width),str(height),'30','1','35']+(['raw'] if raw else [])
    with (out/('thermal.log' if raw else 'rgb.log')).open('wb') as log:
        proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log)
        deadline=time.monotonic()+40;sel=selectors.DefaultSelector();sel.register(proc.stdout,selectors.EVENT_READ)
        def readn(n):
            data=bytearray()
            while len(data)<n:
                left=deadline-time.monotonic()
                if left<=0 or not sel.select(left):raise RuntimeError('camera timeout')
                chunk=os.read(proc.stdout.fileno(),n-len(data))
                if not chunk:raise RuntimeError('camera transport ended')
                data.extend(chunk)
            return bytes(data)
        try:
            nm,nb=struct.unpack('!II',readn(8))
            if nm>4096 or nb>24*1024*1024:raise ValueError('camera payload bounds')
            meta=json.loads(readn(nm));payload=readn(nb)
            if meta['source']!='ZYNQ_USB_REAL' or meta['negotiated_width']!=width or meta['negotiated_height']!=height:raise ValueError('negotiated camera format')
            proc.wait(timeout=3)
            if proc.returncode:raise RuntimeError('camera acquisition failed')
        finally:
            if proc.poll() is None:proc.terminate();proc.wait(timeout=3)
            sel.close();proc.stdin.close();proc.stdout.close()
    if raw:thermal_decode(payload);meta['temperature_matrix_valid']=True
    return payload,meta
def main():
    a=argparse.ArgumentParser();a.add_argument('--rgb-device',default='/dev/video0');a.add_argument('--thermal-device',default='/dev/video1');a.add_argument('--board',choices=['dcdc','stm32'],required=True);a.add_argument('--output',type=Path,required=True);x=a.parse_args()
    if platform.system()!='Linux' or not platform.machine().startswith(('arm','aarch')):raise RuntimeError('fresh acquisition requires board ARM Linux')
    x.output.mkdir(parents=True,exist_ok=False);batch=x.board+'-'+str(time.monotonic_ns());raw={};metadata={}
    for kind,dev,w,h,mode,name in [('rgb',x.rgb_device,3840,3040,False,'rgb.jpg'),('thermal',x.thermal_device,256,384,True,'thermal.raw')]:
        payload,meta=camera(dev,w,h,mode,x.output);(x.output/name).write_bytes(payload);metadata[kind]=meta
        raw[kind]=[{'path':name,'sha256':hashlib.sha256(payload).hexdigest(),'source':'ZYNQ_USB_REAL','timestamp':{'v4l2_us':meta['v4l2_timestamp_us'],'clock':'board-monotonic'},'dimensions':[2,192,256] if mode else [3040,3840,3],'unit':'dual uint16 LE; plane1 Kelvin*16' if mode else 'uint8 RGB','batch_id':batch}]
    # No default ADC or mechanical position. Capture with pcb_adc; attach only
    # a measured mechanical-point record with three real frames in one batch.
    bundle={'schema':'CaptureBundle/1','board_id':x.board,'capture_id':batch,'calibration_version':'unregistered-live-v1','acquisition_batches':[batch],'synchronization':'sequential USB acquisition, not hardware synchronized','raw':raw}
    (x.output/'capture.json').write_text(json.dumps(metadata,indent=2));(x.output/'capture.bundle.json').write_text(json.dumps(bundle,indent=2))
if __name__=='__main__':main()
