"""PS-side orchestration example. Default CLI is explicitly offline/replay only."""
from pathlib import Path
import argparse,json,time
from .hashutil import sha256
from .backend import RtlReplay
ROOT=Path(__file__).resolve().parents[1]

def serpentine(points):
    ys=sorted({p['xy_mm'][1] for p in points});route=[]
    for row,y in enumerate(ys):
        route+=sorted([p for p in points if p['xy_mm'][1]==y],key=lambda p:p['xy_mm'][0],reverse=bool(row%2))
    return route

def report_route(width=70,height=44,step_x=5,step_y=5):
    """Endpoint-inclusive configurable route, with up to 1024 result points."""
    import math
    width,height,step_x,step_y=map(float,(width,height,step_x,step_y))
    if not all(math.isfinite(v) for v in (width,height,step_x,step_y)) or not 0<width<=200 or not 0<height<=200 or not .25<=step_x<=200 or not .25<=step_y<=200:raise ValueError('invalid scan range or spacing')
    def axis(end,step):
        points=[round(i*step,6) for i in range(int(math.floor(end/step+1e-9))+1)]
        if abs(points[-1]-end)>1e-6:points.append(end)
        return points
    xs,ys=axis(width,step_x),axis(height,step_y)
    if len(xs)*len(ys)>1024:raise ValueError('scan route exceeds 1024 points; increase spacing or reduce range')
    return serpentine([dict(point_index=row*len(xs)+col,xy_mm=[x,y]) for row,y in enumerate(ys) for col,x in enumerate(xs)])

class SimulatedMotion:
    """A reported-position fixture, never a serial/JTAG/hardware transport."""
    def __init__(self,clock=time):self.clock=clock;self.xy=[0.,0.];self.target=self.xy;self.polls=0;self.canceled=False
    def move(self,xy):self.target=list(xy);self.polls=0
    def status(self):
        self.polls+=1
        if self.polls>=3:self.xy=list(self.target)
        return {'ack':True,'state':'Idle' if self.polls>=3 else 'Jog','xy_mm':list(self.xy),'reported_at':self.clock.monotonic(),'simulated':True}
    def cancel(self):self.canceled=True

class RawReplaySampler:
    def __init__(self):self.calls=0
    def capture(self,point,frame_index):
        self.calls+=1;record=dict(point['frames'][frame_index])
        record.update(source_point_index=point['point_index'],source_xy_mm=point['xy_mm'],fresh_capture=False)
        return record

class ScanScheduler:
    def __init__(self,motion,sampler,pl,clock=time,settle_s=.5,arrival_timeout_s=30.,poll_s=.01,on_event=None,on_point=None):
        if settle_s<0 or arrival_timeout_s<=0 or poll_s<=0:raise ValueError('invalid scan timing')
        self.motion=motion;self.sampler=sampler;self.pl=pl;self.clock=clock
        self.settle_s=settle_s;self.timeout=arrival_timeout_s;self.poll_s=poll_s;self.events=[];self.on_event=on_event;self.on_point=on_point
    def event(self,state,**data):
        item={'state':state,'monotonic_s':self.clock.monotonic(),**data};self.events.append(item)
        if self.on_event:self.on_event(item)
    def run(self,points):
        records=[];route=serpentine(points);self.event('ROUTE',xy_mm=[p['xy_mm'] for p in route])
        try:
            for ordinal,point in enumerate(route):
                xy=point['xy_mm'];self.event('MOVE',ordinal=ordinal,xy_mm=xy);sent=self.clock.monotonic();self.motion.move(xy)
                self.event('WAIT_ARRIVAL',ordinal=ordinal)
                while True:
                    status=self.motion.status();now=self.clock.monotonic();age=now-status['reported_at']
                    arrived=status['ack'] and status['state']=='Idle' and status['reported_at']>=sent and 0<=age<=1 and len(status['xy_mm'])==2 and all(abs(a-b)<.05 for a,b in zip(status['xy_mm'],xy))
                    if arrived:break
                    if now-sent>self.timeout:raise TimeoutError('no fresh Idle/target-position confirmation')
                    self.clock.sleep(self.poll_s)
                arrival=self.clock.monotonic();self.event('SETTLE',ordinal=ordinal,required_s=self.settle_s)
                settle_deadline=arrival+self.settle_s
                while self.clock.monotonic()<settle_deadline:
                    self.clock.sleep(min(self.poll_s,settle_deadline-self.clock.monotonic()))
                    current=self.motion.status();age=self.clock.monotonic()-current['reported_at']
                    if not current['ack'] or current['state']!='Idle' or not 0<=age<=1 or any(abs(a-b)>=.05 for a,b in zip(current['xy_mm'],xy)):
                        raise RuntimeError('position or controller state changed during settling')
                settled=self.clock.monotonic();frames=[]
                for n in range(3):
                    self.event('CAPTURE',ordinal=ordinal,frame_index=n);began=self.clock.monotonic();frame=self.sampler.capture(point,n)
                    if len(frame['source_xy_mm'])!=2 or any(abs(a-b)>=.05 for a,b in zip(frame['source_xy_mm'],xy)):raise ValueError('source point mismatch')
                    frames.append({**frame,'demo_capture_id':f'point-{ordinal:03d}-frame-{n}','demo_sample_begin':began,'demo_sample_end':self.clock.monotonic()})
                from .fixed_reference import psd
                result=self.pl.run_three([f['samples'] for f in frames]);meta=result['metadata'];n=len(frames[0]['samples'])
                mean_power=[v/(1<<40) for v in result['output']] if meta.get('unit')=='PSD_Q40' else psd(result['output'],n,meta['window_energy_q28'],3,50_000_000)
                channel_results=[result]
                if all('samples_channels' in f for f in frames):channel_results.append(self.pl.run_three([f['samples_channels'][1] for f in frames]))
                current=self.motion.status();age=self.clock.monotonic()-current['reported_at']
                if not current['ack'] or current['state']!='Idle' or not 0<=age<=1 or any(abs(a-b)>=.05 for a,b in zip(current['xy_mm'],xy)):raise RuntimeError('controller state changed before association')
                for frame in frames:
                    if frame.get('fresh_capture') and frame.get('source_path'):
                        frame.pop('samples',None);frame.pop('samples_channels',None)
                records.append({'ordinal':ordinal,'source_point_index':point['point_index'],'xy_mm':xy,'reported_xy_mm':list(status['xy_mm']),'arrival_confirmed_at':arrival,'settled_at':settled,'settle_s':self.settle_s,'frames':frames,'spectrum':result,'channel_spectra':channel_results,'mean_power':mean_power})
                if self.on_point:self.on_point(records[-1])
                self.event('ASSOCIATE',ordinal=ordinal,frames=3,source_point_index=point['point_index'])
            self.event('DONE',points=len(records));return records
        except Exception as exc:
            self.motion.cancel();self.event('FAULT',reason=str(exc));raise

def main():
    p=argparse.ArgumentParser();p.add_argument('--replay',action='store_true',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--settle-s',type=float,default=.1);a=p.parse_args()
    inputs=json.loads((ROOT/'inputs/full-inputs.json').read_text());a.output.mkdir(parents=True,exist_ok=False)
    pl=RtlReplay();scheduler=ScanScheduler(SimulatedMotion(),RawReplaySampler(),pl,settle_s=a.settle_s)
    records=scheduler.run(inputs['points']);thermal=pl.run(2,inputs['thermal']['raw_kelvin16'])
    rgb=pl.run(3,inputs['rgb']['rgb888']);thermal_input=pl.run(3,inputs['thermal']['raw_kelvin16'],{'mode':1})
    result={'schema':'PlPsDemoSession/1','motion_simulated':True,'fresh_acquisition':False,'hardware_synchronized':False,'pl_backend':'XSim AXI checked result replay, not a connected FPGA',
        'input_sha256':sha256((ROOT/'inputs/full-inputs.json').read_bytes()).hexdigest(),'sample_rate_hz':inputs['sample_rate_hz'],'spectrum_size':4096,'thermal_shape':[192,256],
        'points':records,'thermal':thermal,'preprocessing':{'rgb_int8':rgb,'thermal_int8':thermal_input},'pl_calls':pl.calls,'events':scheduler.events}
    (a.output/'demo-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    (a.output/'events.jsonl').write_text('\n'.join(json.dumps(e,ensure_ascii=False) for e in scheduler.events)+'\n',encoding='utf8')
    print('DEMO_DONE points=',len(records),'frames=',sum(len(p['frames']) for p in records),'PL-result calls=',len(pl.calls),'motion=SIMULATED capture=HISTORICAL_REPLAY')
if __name__=='__main__':main()
