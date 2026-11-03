"""Report-defined processing dispatch to the PDP3 device.

The only CPU execution mode is explicit offline_test. Production errors propagate.
"""
from pathlib import Path
import json,os,platform,struct,subprocess,time
from contextlib import contextmanager
ROOT=Path(__file__).resolve().parents[1]

@contextmanager
def scratch():
    # The supplied board Python omits hashlib, which tempfile imports via
    # random. Names require uniqueness here, not random numbers or hashes.
    p=Path('/tmp')/('pcb-compute-%d-%d'%(os.getpid(),time.monotonic_ns()))
    p.mkdir(mode=0o700)
    try:yield p
    finally:
        for name in ('input.u32','output.u64','input.i32','output.i32','second.i32','valid.i32','bands.txt'):
            f=p/name
            if f.exists():f.unlink()
        p.rmdir()

class PlCompute:
    backend='PDP3 MMIO'
    def __init__(self,binary=None,device='/dev/pcb_demo'):
        self.binary=Path(binary or ROOT/'bin/pl_demo');self.device=device;self.calls=[]
        if platform.system()!='Linux' or not platform.machine().startswith(('arm','aarch')):
            raise RuntimeError('PL processing requires ARM Linux')

    def execute(self,task,values,*,mode=None,frames=1,length=None,base=4370,shift=2,threshold_mc=40000,sample_rate=50000000,bands=None):
        values=list(map(int,values))
        if not values:raise ValueError('empty compute input')
        with scratch() as folder:
            p=Path(folder);inp=p/'input.u32';out=p/'output.u64'
            inp.write_bytes(struct.pack('<%dI'%len(values),*(v&0xffffffff for v in values)))
            command=[str(self.binary),str(task),str(inp),str(out),self.device,'--frames',str(frames),'--base',str(base),'--shift',str(shift),'--threshold',str(threshold_mc)]
            if mode is not None:command+=['--mode',str(mode)]
            if length is not None:command+=['--length',str(length)]
            command+=['--sample-rate',str(sample_rate)]
            if bands is not None:
                (p/'bands.txt').write_text('\n'.join('%d %d'%(lo,hi) for lo,hi in bands)+'\n');command+=['--bands',str(p/'bands.txt')]
            r=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=max(15,3*((len(values)+4095)//4096)+5))
            metadata=json.loads(r.stdout);data=out.read_bytes();n=(length or len(values)//frames)//2+1 if task==1 else len(values)
            if len(data)!=n*8:raise ValueError('PL output length mismatch')
            if metadata['backend']!=self.backend or metadata['input_count']!=len(values) or ((metadata['generation_end']-metadata['generation_start'])&0xffffffff)!=metadata['jobs']:
                raise ValueError('PL completion metadata mismatch')
            output=list(struct.unpack('<%d%s'%(n,'Q' if task==1 else 'q'),data))
            self.calls.append(metadata)
            return dict(output=output,statistics=metadata['statistics'] if task==2 else {},metadata=metadata,backend=self.backend)

    def run(self,task,values,config=None):
        config=dict(config or {});return self.execute(task,values,**config)

    def run_three(self,frames):
        if len(frames)!=3 or len({len(f) for f in frames})!=1:raise ValueError('three equal FFT frames required')
        return self.execute(1,[x for f in frames for x in f],length=len(frames[0]),frames=3)

    def spectrum_three(self,channels,sample_rate=50_000_000):
        import numpy as np
        channels=np.asarray(channels)
        if channels.shape!=(3,2,4096):raise ValueError('three dual-channel 4096 sample frames required')
        out=[];band_outputs=[]
        for channel in range(2):
            result=self.execute(1,channels[:,channel,:].reshape(-1),frames=3,length=4096,mode=1,sample_rate=sample_rate)
            m=result['metadata']
            if m['frames']!=3 or m['unit']!='PSD_Q40':raise ValueError('incomplete PL PSD normalization')
            out.append(np.asarray(result['output'],np.float64)/(1<<40))
            band_outputs.append(np.asarray(m['bands_rms_q16'],np.float64)/(1<<16))
        self.last_bands_rms={f'{lo:g}-{hi:g}Hz':[float(v[i]) for v in band_outputs] for i,(lo,hi) in enumerate(__import__('runtime.bands',fromlist=['UI_BANDS_HZ']).UI_BANDS_HZ)}
        return np.asarray(out,np.float64)

    def decode_adc(self,words):
        import numpy as np
        return np.asarray(self.decode_adc_lists(words),np.int32)

    def decode_adc_lists(self,words):
        if len(words)!=16384:raise ValueError('ADC raw frame size')
        result=self.execute(4,words)
        if result['metadata']['phase_counts']!=[4096]*4:raise ValueError('PL ADC phase counts')
        channels=[[],[]]
        for value in result['output']:
            if value&0x10000:channels[(value>>17)&1].append(struct.unpack('<h',struct.pack('<H',value&65535))[0])
        if any(len(channel)!=4096 for channel in channels):raise ValueError('PL channel sample count')
        return channels

    def image_words(self,operation,values,width,height,**options):
        values=list(map(int,values))
        if len(values)!=width*height:raise ValueError('image input shape')
        with scratch() as p:
            (p/'input.i32').write_bytes(struct.pack('<%dI'%len(values),*(v&0xffffffff for v in values)))
            command=[str(ROOT/'bin/pl_image'),operation,str(p/'input.i32'),str(p/'output.i32'),self.device,'--width',str(width),'--height',str(height)]
            for key,value in options.items():
                key=key.replace('_','-')
                if key in ('second','valid'):
                    v=list(map(int,value))
                    if len(v)!=len(values):raise ValueError('image paired input shape')
                    (p/(key+'.i32')).write_bytes(struct.pack('<%dI'%len(v),*(x&0xffffffff for x in v)));command+=['--'+key,str(p/(key+'.i32'))]
                else:command+=['--'+key,str(int(value))]
            result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=max(30,len(values)//5000+30))
            metadata=json.loads(result.stdout);blob=(p/'output.i32').read_bytes();expected=options.get('out_width',width)*options.get('out_height',height)
            if metadata['backend']!=self.backend or metadata['output_pixels']!=expected or len(blob)!=expected*4 or ((metadata['generation_end']-metadata['generation_start'])&0xffffffff)!=metadata['jobs']:raise ValueError('image completion metadata')
            self.calls.append(metadata);return list(struct.unpack('<%di'%expected,blob))

    def image(self,operation,image,**options):
        import numpy as np
        x=np.asarray(image)
        if x.ndim!=2 or not np.isfinite(x).all():raise ValueError('scalar image required')
        converted={k:np.asarray(v).reshape(-1) if k in ('second','valid') else v for k,v in options.items()}
        values=self.image_words(operation,x.reshape(-1),x.shape[1],x.shape[0],**converted)
        return np.asarray(values,np.int32).reshape(options.get('out_height',x.shape[0]),options.get('out_width',x.shape[1]))

    def structure(self,image):
        import numpy as np
        x=np.rint(image).astype(np.int32);x=self.image('resize',x,out_width=64,out_height=48)
        x=self.image('blur',x);magnitude=self.image('sobel',x)
        denominator=max(1,int(np.ceil(np.percentile(magnitude,98))))
        return self.image('normalize',magnitude,normalizer=denominator).astype(np.int8)

    def pseudocolor(self,temperature_mc):
        import numpy as np
        x=np.asarray(temperature_mc,np.int32)
        return self.image('color',x,low=int(x.min()),high=int(x.max())).view(np.uint32)

    def thermal_decode(self,raw,threshold_mc=40000):
        import numpy as np
        if len(raw)!=196608:raise ValueError('thermal dual-plane length')
        planes=np.frombuffer(raw,'<u2').reshape(2,192,256)
        if np.ptp(planes[0])==0 or np.ptp(planes[1])==0:raise ValueError('invalid thermal plane')
        result=self.execute(2,planes[1].reshape(-1),threshold_mc=threshold_mc)
        if result['statistics']['processed_pixels']!=49152:raise ValueError('incomplete thermal frame')
        return planes[0],np.asarray(result['output'],np.float32).reshape(192,256)/1000,result['statistics']

    def gray(self,rgb,quantized=False):
        import numpy as np
        rgb=np.asarray(rgb)
        if rgb.dtype!=np.uint8 or rgb.ndim!=3 or rgb.shape[2]!=3:raise ValueError('RGB uint8 image required')
        packed=(rgb[...,0].astype(np.uint32)<<16)|(rgb[...,1].astype(np.uint32)<<8)|rgb[...,2]
        flat=packed.reshape(-1);output=np.empty(flat.size,np.int8 if quantized else np.uint8)
        # Bound Python object memory for full-resolution camera images. The ARM
        # executor further tiles each batch into the same 4096-word PL RAM.
        for start in range(0,flat.size,65536):
            result=self.execute(3,flat[start:start+65536],mode=0 if quantized else 2)
            output[start:start+65536]=result['output']
        return output.reshape(rgb.shape[:2])

    def thermal_quantize(self,raw_kelvin16,base=4370,shift=2):
        import numpy as np
        x=np.asarray(raw_kelvin16)
        result=self.execute(3,x.reshape(-1),mode=1,base=base,shift=shift)
        return np.asarray(result['output'],np.int8).reshape(x.shape)
