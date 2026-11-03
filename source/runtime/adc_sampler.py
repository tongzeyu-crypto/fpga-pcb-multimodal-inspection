"""Fresh board ADC acquisition, PL channel extraction and position association."""
from pathlib import Path
import json,struct,subprocess,time
from demo.runtime.hashutil import sha256
ROOT=Path(__file__).resolve().parents[1]

class AdcSampler:
    def __init__(self,motion,compute,output,device='/dev/pcb_adc',command=None):
        self.motion=motion;self.compute=compute;self.output=Path(output);self.output.mkdir(parents=True,exist_ok=False);self.device=device;self.command=command;self.batch=None
    def capture(self,point,frame_index):
        position=self.motion.status();now=time.monotonic()
        if not position['ack'] or position['state']!='Idle' or not 0<=now-position['reported_at']<=1 or any(abs(x-y)>=.05 for x,y in zip(position['xy_mm'],point['xy_mm'])):raise RuntimeError('capture requires fresh confirmed target position')
        name='point-%05d-frame-%d.u32'%(point['point_index'],frame_index);path=self.output/name;begin=time.monotonic();adc_metadata={}
        if self.command is None:
            if frame_index==0:
                prefix=self.output/('point-%05d-batch'%point['point_index'])
                result=subprocess.run([str(ROOT/'bin/pcb_adc'),self.device,str(prefix),'--frames','3'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=8)
                batch=json.loads(result.stdout)
                if batch.get('backend')!='ADC_PINGPONG_V2' or len(batch.get('frames',[]))!=3:raise ValueError('ADC batch metadata')
                self.batch=(point['point_index'],batch)
            if self.batch is None or self.batch[0]!=point['point_index']:raise ValueError('ADC batch point mismatch')
            batch=self.batch[1];adc_metadata=batch['frames'][frame_index];captured=Path(adc_metadata['file'])
            if captured.parent!=self.output or adc_metadata['frame_index']!=frame_index:raise ValueError('ADC batch file identity')
            captured.replace(path);result=subprocess.CompletedProcess([],0,json.dumps(batch).encode(),b'')
        else:
            command=self.command(path) if callable(self.command) else self.command
            result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=4)
        blob=path.read_bytes()
        if len(blob)!=65536:raise ValueError('fresh ADC raw frame size')
        words=struct.unpack('<16384I',blob);channels=self.compute.decode_adc_lists(words)
        after=self.motion.status()
        if not after['ack'] or after['state']!='Idle' or not 0<=time.monotonic()-after['reported_at']<=1 or any(abs(x-y)>=.05 for x,y in zip(after['xy_mm'],point['xy_mm'])):raise RuntimeError('controller moved or stopped reporting during capture')
        record=dict(source='ZYNQ_ADC_AXI_RAW',source_path=str(path),source_sha256=sha256(blob).hexdigest(),source_timestamp=time.monotonic(),source_point_index=point['point_index'],source_xy_mm=list(position['xy_mm']),target_xy_mm=list(point['xy_mm']),controller=position['controller'],controller_after=after['controller'],sample_begin=begin,sample_end=time.monotonic(),fresh_capture=True,samples=channels[0],samples_channels=channels,capture_log=result.stdout.decode(errors='replace'))
        record.update(frame_index=frame_index,adc=adc_metadata)
        if adc_metadata:
            record.update(source_timestamp=adc_metadata['ready_observed_ns']/1e9,sample_begin=batch['trigger_ns']/1e9,sample_end=adc_metadata['copy_done_ns']/1e9,timestamp_semantics='CPU trigger-to-copy bounds; exact per-frame interval is the independent 200 MHz sample tick pair',decoded_at=time.monotonic())
        path.with_suffix('.json').write_text(json.dumps({k:v for k,v in record.items() if k not in ('samples','samples_channels')},indent=2));return record
