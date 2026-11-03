"""Extract the delivered ZIP and run its main demo entry without build tools."""
from pathlib import Path
import argparse, hashlib, json, os, subprocess, sys, time, urllib.request, zipfile

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser();p.add_argument('--zip',type=Path,required=True);p.add_argument('--work',type=Path,required=True);p.add_argument('--port',type=int,default=8699);p.add_argument('--result',type=Path);a=p.parse_args()
    a.work.mkdir(parents=True,exist_ok=False)
    with zipfile.ZipFile(a.zip) as z:
        names=[n for n in z.namelist() if n.endswith('/VERSION.json') and n.count('/')==1]
        if len(names)!=1:raise ValueError('one submission root required')
        extracted=a.work/names[0].split('/')[0];z.extractall(a.work)
    log=(a.work/'portable-launch.log').open('wb')
    command=[sys.executable,'-m','runtime.run_board','--demo','--port',str(a.port),'--demo-work',str(a.work/'work'),'--no-browser']
    proc=subprocess.Popen(command,cwd=extracted,stdout=log,stderr=subprocess.STDOUT)
    base=f'http://127.0.0.1:{a.port}'
    def get():return json.load(urllib.request.urlopen(base+'/api/status',timeout=5))
    try:
        deadline=time.monotonic()+60
        while True:
            if proc.poll() is not None:raise RuntimeError('extracted demo exited; see portable-launch.log')
            try:initial=get();break
            except OSError:
                if time.monotonic()>deadline:raise TimeoutError('extracted demo failed to start')
                time.sleep(.25)
        assert initial['app']['mode']==16 and not initial['board_connected']
        urllib.request.urlopen(urllib.request.Request(base+'/demo/start',data=b'',method='POST'),timeout=5).read()
        deadline=time.monotonic()+20
        while True:
            status=get()
            if status['demo']['state']=='DONE':break
            if status['demo']['state']=='FAULT' or time.monotonic()>deadline:
                (a.work/'failed-session.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf8')
                raise RuntimeError('extracted demo scan failed: '+status['demo']['error'])
            time.sleep(.2)
        assert status['demo']['completed']==6
        assert len(status['demo']['pl_calls'])==54
        urllib.request.urlopen(urllib.request.Request(base+'/framegen/start',data=b'0',method='POST'),timeout=5).read()
        deadline=time.monotonic()+30
        while True:
            status=get()
            if status['framegen']['state']=='DONE':break
            if status['framegen']['state']=='FAULT' or time.monotonic()>deadline:raise RuntimeError('extracted neural frame demo failed')
            time.sleep(.2)
        assert len(status['framegen']['cases'])==4
        assert all(c['network_participated'] and c['soft_blended_pixels']>0 for c in status['framegen']['cases'])
        image=urllib.request.urlopen(base+'/frame.jpg').read()
        assert image[:2]==b'\xff\xd8'
        (a.work/'portable-frame.jpg').write_bytes(image)
        result=dict(passed=True,extracted_main_entry=True,compiler_required=False,points=6,frames=18,
                    neural_generated_frames=4,actual_neural_rgb_fusion=True,board_connected=False,original_boot_image_modified=False,
                    tested_zip_sha256=hashlib.sha256(a.zip.read_bytes()).hexdigest(),source_sha256={n:hashlib.sha256((extracted/n).read_bytes()).hexdigest() for n in ['bin/demo_reference.exe','bin/neural_frame_tool.exe','runtime/run_board.py','runtime/demo_host.py','runtime/demo_integration.py','runtime/frame_demo.py','models/frame/model.pai']})
        (a.result or ROOT/'evidence/demo-integration/portable.json').write_text(json.dumps(result,indent=2),encoding='utf8')
        print(json.dumps(result,indent=2))
    finally:
        if os.name=='nt':subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        else:proc.terminate()
        proc.wait(timeout=10);log.close()


if __name__=='__main__':main()
