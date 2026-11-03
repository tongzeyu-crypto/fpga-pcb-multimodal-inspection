"""Verify the neural generator through the shipped main application's API."""
from pathlib import Path
import argparse, hashlib, json, time, urllib.request, urllib.error
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8698');a=p.parse_args()
    e=ROOT/'evidence/neural-frame';e.mkdir(exist_ok=True);sessions=[]
    def get(path):return urllib.request.urlopen(a.url+path,timeout=30).read()
    def status():return json.loads(get('/api/status'))['framegen']
    for mode in [0,3]:
        urllib.request.urlopen(urllib.request.Request(a.url+'/framegen/start',data=str(mode).encode(),method='POST'),timeout=10).read()
        deadline=time.monotonic()+40
        while True:
            result=status()
            if result['state']=='DONE':break
            if result['state']=='FAULT' or time.monotonic()>deadline:raise RuntimeError(result['error'] or 'neural demo timeout')
            time.sleep(.15)
        assert result['mode']==mode and len(result['cases'])==4 and len(result['frames'])==12
        assert not result['network_is_confidence_classifier'] and not result['board_connected']
        assert result['model_sha256']==hashlib.sha256((ROOT/'models/frame/model.pai').read_bytes()).hexdigest()
        for case in result['cases']:
            assert case['network_participated'] and case['soft_blended_pixels']>0 and case['network_ablation_changed_pixels']>0
        assert [f['kind'] for f in result['frames'][:3]]==['完整渲染','神经生成过渡帧','完整渲染']
        assert all(b['yaw']>=a['yaw']-1e-6 for a,b in zip(result['frames'],result['frames'][1:]))
        neural=get('/framegen/image?key=neural-0');warp=get('/framegen/image?key=warp-0')
        weights=cv2.imdecode(np.frombuffer(get('/framegen/image?key=weights-0'),np.uint8),cv2.IMREAD_COLOR)
        difference=cv2.imdecode(np.frombuffer(get('/framegen/image?key=difference-0'),np.uint8),cv2.IMREAD_COLOR)
        assert weights.shape==difference.shape==(720,1280,3) and np.unique(weights.reshape(-1,3),axis=0).shape[0]>1
        assert neural!=warp
        pixels=cv2.imdecode(np.frombuffer(neural,np.uint8),cv2.IMREAD_COLOR);assert pixels.shape==(720,1280,3)
        (e/f'ui-mode-{mode}-neural.png').write_bytes(cv2.imencode('.png',pixels)[1].tobytes())
        assert json.loads(get('/framegen/export'))['run_id']==result['run_id']
        sessions.append(result)
    for path,method,data,code in [('/framegen/image?key=../../README.md','GET',None,404),('/framegen/start','POST',b'12',400)]:
        try:urllib.request.urlopen(urllib.request.Request(a.url+path,data=data,method=method),timeout=10)
        except urllib.error.HTTPError as exc:assert exc.code==code
        else:raise AssertionError('invalid neural request accepted')
    report=dict(passed=True,scenes=2,generated_frames=8,display_frames=24,actual_neural_integer_execution=True,network_ablation_verified=True,board_connected=False,
                sessions=sessions,source_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'runtime/frame_demo.py',ROOT/'runtime/demo_host.py',ROOT/'runtime/demo_preview.html',ROOT/'bin/neural_frame_tool.exe']})
    (e/'ui-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('MAIN_UI_NEURAL_FRAME_PASS: 2 scenes, 8 neural frames, 24 display frames, real integer inference and network-off ablation')


if __name__=='__main__':main()
