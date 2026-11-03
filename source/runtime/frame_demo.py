"""One-click, actual INT8 neural frame generation in the offline main UI."""
from pathlib import Path
import hashlib, json, subprocess, threading, time
import cv2
import numpy as np
from .neural_frames import NativeRenderer, render_pair, read_rgb

ROOT=Path(__file__).resolve().parents[1]


class NeuralFrameDemo:
    def __init__(self,assets,work):
        self.assets=Path(assets);self.work=Path(work);self.work.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock();self.cancel=threading.Event();self.worker=None
        self.record=dict(state='READY',frames=[],cases=[],error='',offline_reference=True,board_connected=False,network_is_confidence_classifier=False)
        self.images={}

    def status(self):
        with self.lock:return json.loads(json.dumps(self.record))

    def image(self,key):
        with self.lock:
            path=self.images.get(key)
            if path is None:raise KeyError('frame image is unavailable')
            return path.read_bytes()

    def close(self):
        self.cancel.set()
        if self.worker:self.worker.join(timeout=15)

    def start(self,mode=0):
        if mode not in [0,3]:raise ValueError('frame generation supports 3D fusion or EMI terrain')
        with self.lock:
            if self.worker and self.worker.is_alive():return False
            self.cancel.clear();self.images={}
            self.record=dict(state='RUNNING',run_id=str(time.monotonic_ns()),frames=[],cases=[],error='',offline_reference=True,board_connected=False,mode=mode,
                             network_is_confidence_classifier=False,algorithm='depth reprojection + trained neural RGB pixel fusion',backend='C++ INT8 reference; no connected FPGA')
            self.worker=threading.Thread(target=self._run,args=(mode,),name='neural-pixel-fusion-demo',daemon=True);self.worker.start();return True

    def _save_image(self,key,image,folder):
        path=folder/(key+'.jpg');path.write_bytes(cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,95])[1].tobytes());self.images[key]=path

    def _run(self,mode):
        try:
            folder=self.work/self.record['run_id'];folder.mkdir()
            model=ROOT/'models/frame/model.pai'
            expected=(model.with_suffix('.pai.sha256')).read_text().split()[0]
            if hashlib.sha256(model.read_bytes()).hexdigest()!=expected:raise ValueError('neural model hash mismatch')
            with NativeRenderer(ROOT/'bin/demo_reference.exe',self.assets,folder/'render') as engine:
                for i in range(4):
                    if self.cancel.is_set():break
                    yaw=.45+i*.02
                    source,truth=render_pair(engine,folder,mode,yaw,.9,.01)
                    prefix=folder/'generated'
                    process=subprocess.run([str(ROOT/'bin/neural_frame_tool.exe'),'generate',str(model),str(source),str(truth),str(prefix)],capture_output=True,check=True,timeout=20)
                    stats=json.loads(process.stdout)
                    if not stats['network_participated'] or not stats['soft_blended_pixels']:raise RuntimeError('network did not participate in RGB generation')
                    original=read_rgb(str(source)+'.argb');reference=read_rgb(str(truth)+'.argb');warped=read_rgb(str(prefix)+'.warp.argb');neural=read_rgb(str(prefix)+'.neural.argb')
                    # The native UI header is a separate display layer. Reuse
                    # that unchanged source UI, never the target scene pixels.
                    warped[:54]=original[:54];neural[:54]=original[:54]
                    error=np.abs(neural.astype(float)-reference).mean(2)
                    difference=np.abs(neural.astype(np.int16)-warped.astype(np.int16)).max(2)
                    stats.update(index=i,network_ablation_changed_pixels=int(np.count_nonzero(difference)),render_reference_mae=float(error.mean()),source_yaw=yaw,target_yaw=yaw+.01,measurement_input=False)
                    # A is a complete render, G is neural generation at its own
                    # intermediate pose, B is the next complete render.
                    engine.command(f'app raw_board 1 mode {mode} hud 0 cursor_visible 0 points 0 base 1 polar .9 yaw {yaw+.02}')
                    final=read_rgb(str(engine.prefix)+'.argb')
                    with self.lock:
                        for kind,image in [('source',original),('neural',neural),('truth',reference),('warp',warped),('final',final),('difference',cv2.applyColorMap(np.minimum(difference*6,255).astype(np.uint8),cv2.COLORMAP_TURBO))]:
                            self._save_image(f'{kind}-{i}',image,folder)
                        self.record['cases'].append(stats)
                        self.record['frames'] += [dict(image=f'source-{i}',kind='完整渲染',yaw=yaw),dict(image=f'neural-{i}',kind='神经生成过渡帧',yaw=yaw+.01),dict(image=f'final-{i}',kind='完整渲染',yaw=yaw+.02)]
                with self.lock:
                    self.record['state']='CANCELED' if self.cancel.is_set() else 'DONE'
                    self.record['model_sha256']=expected
                    (folder/'session.json').write_text(json.dumps(self.record,ensure_ascii=False,indent=2),encoding='utf8')
        except Exception as exc:
            with self.lock:self.record['state']='FAULT';self.record['error']=str(exc)
