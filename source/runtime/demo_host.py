"""Local-only supervisor for the integrated main-UI demo. Never opens devices."""
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import json, mmap, os, subprocess, tempfile, threading, time, uuid, webbrowser
from urllib.parse import urlsplit, parse_qs
import numpy as np
import cv2
from .demo_integration import DemoSession
from .frame_demo import NeuralFrameDemo

ROOT=Path(__file__).resolve().parents[1]


class DemoApplication:
    def __init__(self,work):
        self.work=Path(work);self.work.mkdir(parents=True,exist_ok=True)
        if not str(self.work).isascii():raise ValueError('demo work path must use ASCII characters')
        from tools.build_demo_host import prepare_assets
        # Rebuild derivatives from source-validated raw data for every launch.
        self.assets=prepare_assets(self.work)
        self.demo=DemoSession(self.assets,self.work/'sessions')
        self.framegen=NeuralFrameDemo(self.assets,self.work/'neural-frames')
        self.lock=threading.RLock();self.closed=threading.Event();self.jpeg=b'';self.state={};self.command_seen=0;self.error=''
        self.mapping=None
        args=[str(ROOT/'bin/demo_reference.exe'),'assets','frame']
        if os.name=='nt':
            name='pcb-integrated-demo-'+uuid.uuid4().hex
            self.mapping=mmap.mmap(-1,1280*720*4,tagname=name)
            args+=['--shared-memory',name]
        self.log=(self.work/'renderer.log').open('wb')
        self.process=subprocess.Popen(args,cwd=self.work,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,
                                      creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.transact('app raw_board 1 mode 16 cursor_visible 0')
        self.renderer=threading.Thread(target=self.refresh,name='demo-ui-refresh',daemon=True);self.renderer.start()

    def transact(self,line):
        if '\n' in line or len(line)>4096:raise ValueError('invalid application command')
        with self.lock:
            if self.process.poll() is not None:raise RuntimeError('UI renderer stopped')
            self.process.stdin.write((line+'\n').encode());self.process.stdin.flush()
            data=self.process.stdout.readline(32768)
            if not data:raise RuntimeError('UI renderer did not reply')
            response=json.loads(data)
            if response.get('error'):raise ValueError(response['error'])
            self.state=response
            raw=np.ndarray((720,1280,4),np.uint8,buffer=self.mapping) if self.mapping else np.fromfile(self.work/'frame.argb',np.uint8).reshape(720,1280,4)
            self.jpeg=cv2.imencode('.jpg',raw[...,:3],[cv2.IMWRITE_JPEG_QUALITY,94])[1].tobytes()
            app=response['app']
            if app['demo_command']!=self.command_seen:
                self.command_seen=app['demo_command']
                if app['demo_request']==1 and app['raw_board']:self.demo.start()
                elif app['demo_request']==2:self.demo.reset()
            return response

    def refresh(self):
        last=-1
        while not self.closed.wait(.18):
            try:
                revision=self.demo.status()['revision']
                if revision!=last:
                    self.transact('app demo_point '+str(self.state['app']['demo_point']));last=revision
            except Exception as exc:self.error=str(exc)

    def close(self):
        self.closed.set();self.demo.stop();self.framegen.close()
        if hasattr(self,'renderer'):self.renderer.join(timeout=5)
        self.process.stdin.close()
        try:self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:self.process.terminate();self.process.wait(timeout=5)
        self.log.close()
        if self.mapping:self.mapping.close()


def serve(port=8698,work=None,open_browser=True):
    work=Path(work or Path(tempfile.gettempdir())/('pcb-main-demo-'+str(time.monotonic_ns())))
    app=DemoApplication(work)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,body,mime='application/json',status=200):
            if not isinstance(body,bytes):body=json.dumps(body,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
        def do_GET(self):
            path=self.path.split('?')[0]
            if path=='/':return self.reply((ROOT/'runtime/demo_preview.html').read_bytes(),'text/html; charset=utf-8')
            if path=='/frame.jpg':
                with app.lock:data=app.jpeg
                return self.reply(data,'image/jpeg')
            if path=='/api/status':
                with app.lock:state=dict(app.state)
                return self.reply(dict(offline_reference=True,board_connected=False,app=state.get('app',{}),demo=app.demo.status(),framegen=app.framegen.status(),error=app.error))
            if path=='/framegen/export':return self.reply(app.framegen.status())
            if path=='/framegen/image':
                try:return self.reply(app.framegen.image(parse_qs(urlsplit(self.path).query).get('key',[''])[0]),'image/jpeg')
                except KeyError:return self.reply({'error':'image unavailable'},status=404)
            if path=='/api/export':return self.reply(app.demo.status())
            return self.reply({'error':'unknown endpoint'},status=404)
        def do_POST(self):
            # Only same-origin controls; no arbitrary paths, shell or device input.
            if self.headers.get('Origin') not in (None,f'http://127.0.0.1:{port}',f'http://localhost:{port}'):
                return self.reply({'error':'origin rejected'},status=403)
            try:
                size=int(self.headers.get('Content-Length',0))
                if size<0 or size>4096:raise ValueError('invalid request length')
                body=self.rfile.read(size).decode('utf8')
                if self.path=='/app':result=app.transact('app '+body)
                elif self.path=='/pointer':result=app.transact('pointer '+body)
                elif self.path=='/demo/start':result=app.transact('app demo_request 1')
                elif self.path=='/demo/reset':result=app.transact('app demo_request 2')
                elif self.path=='/framegen/start':
                    app.framegen.start(int(body or '0'));result=app.framegen.status()
                else:return self.reply({'error':'unknown endpoint'},status=404)
                self.reply(result)
            except (ValueError,RuntimeError,KeyError) as exc:self.reply({'error':str(exc)},status=400)
    try:
        server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
        server.daemon_threads=True
        url=f'http://127.0.0.1:{port}/'
        print('主程序离线演示已启动：'+url+'\n模拟运动 / 历史原始数据 / RTL 结果回放。',flush=True)
        print('运行记录：'+str(work),flush=True)
        if open_browser:webbrowser.open(url)
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:pass
    finally:
        if 'server' in locals():server.server_close()
        app.close()
