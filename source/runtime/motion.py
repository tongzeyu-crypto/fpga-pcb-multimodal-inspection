"""PS adapter for the actual GRBL helper. Construction never starts a move.

The scan operator must supply the calibrated envelope/scale and confirm origin.
The helper retains all position, unit, alarm, cancellation and freshness guards.
"""
from pathlib import Path
import json,subprocess,threading,time
ROOT=Path(__file__).resolve().parents[1]

class GrblMotion:
    def __init__(self,device,*,origin_confirmed=False,width=70,height=44,scale_x=1,scale_y=1,frame='CONTROLLER',feed=120,command=None):
        if not origin_confirmed:raise ValueError('scan origin must be explicitly confirmed')
        if frame not in ('CONTROLLER','LEFT_REAR','RIGHT_REAR') or not 1<=feed<=120:raise ValueError('motion feed must be within native guard range 1..120')
        self.feed=feed;self.condition=threading.Condition();self.sequence=0;self.replies={};self.latest=None;self.move_id=None;self.failure='';self.closed=False
        self.process=subprocess.Popen(command or [str(ROOT/'bin/grbl_control'),str(device)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
        self.serial=[]
        self.reader=threading.Thread(target=self._read,daemon=True);self.reader.start()
        self.logger=threading.Thread(target=self._log,daemon=True);self.logger.start()
        try:
            deadline=time.monotonic()+10
            with self.condition:
                while not self.latest or not self.latest.get('configured'):
                    if self.failure or self.process.poll() is not None:raise RuntimeError(self.failure or 'GRBL helper ended')
                    left=deadline-time.monotonic()
                    if left<=0:raise TimeoutError('GRBL initialization')
                    self.condition.wait(min(left,.2))
            self.request('SCALE %.9g %.9g'%(scale_x,scale_y));self.request('LIMITS %.9g %.9g'%(width,height));self.request('FRAME '+frame);self.request('ORIGIN 1')
        except BaseException:self.close();raise

    def _read(self):
        try:
            for line in self.process.stdout:
                item=json.loads(line)
                if item.get('type')!='state':continue
                with self.condition:
                    self.latest=item
                    if item.get('id'):self.replies[item['id']]=item
                    error=item.get('error')
                    startup_reset=error=='controller_reset' and not item.get('configured') and self.move_id is None
                    if error and error!='jog_canceled' and not startup_reset:self.failure=error
                    self.condition.notify_all()
        except (OSError,ValueError) as e:
            with self.condition:self.failure=str(e);self.condition.notify_all()

    def _log(self):
        for line in self.process.stderr:
            self.serial.append(line.rstrip())
            if len(self.serial)>200:self.serial.pop(0)

    def send(self,command):
        with self.condition:
            if self.closed or self.process.poll() is not None:raise RuntimeError('GRBL helper unavailable')
            self.sequence+=1;number=self.sequence;self.process.stdin.write('%d %s\n'%(number,command));self.process.stdin.flush();return number

    def request(self,command,timeout=5):
        number=self.send(command);deadline=time.monotonic()+timeout
        with self.condition:
            while number not in self.replies:
                left=deadline-time.monotonic()
                if left<=0:raise TimeoutError('GRBL command '+command.split()[0])
                if self.process.poll() is not None:raise RuntimeError('GRBL helper ended')
                self.condition.wait(min(left,.2))
            result=self.replies.pop(number)
            if not result.get('ok') or result.get('error'):raise RuntimeError(result.get('error') or 'GRBL command rejected')
            return result

    def move(self,xy):self.move_id=self.send('MOVE %.9g %.9g %.9g'%(xy[0],xy[1],self.feed))

    def status(self):
        with self.condition:
            if self.failure:raise RuntimeError(self.failure)
            if self.latest is None:raise RuntimeError('GRBL status absent')
            item=dict(self.latest);reply=self.replies.get(self.move_id,{})
            stamp=item['monotonic_s']-max(0,item['position_age_s'])
            return dict(ack=bool(reply.get('ok')),state=item['status'],xy_mm=[item['local_x'],item['local_y']],reported_at=stamp,simulated=False,controller=item)

    def cancel(self):
        if not self.closed and self.process.poll() is None:self.send('CANCEL')

    def close(self):
        if self.closed:return
        try:
            if self.process.poll() is None:self.request('QUIT',timeout=2)
        except (OSError,RuntimeError,TimeoutError):
            if self.process.poll() is None:self.process.terminate()
        self.closed=True
        try:self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=3)
        for stream in (self.process.stdin,self.process.stdout,self.process.stderr):stream.close()

    def __enter__(self):return self
    def __exit__(self,*_):self.close()
