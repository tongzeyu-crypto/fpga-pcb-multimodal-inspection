"""Exercise the actual local demo service and original renderer end to end."""
from pathlib import Path
import argparse, hashlib, json, time, urllib.request, urllib.error
import numpy as np
import cv2

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8698');a=p.parse_args()
    evidence=ROOT/'evidence/demo-integration';evidence.mkdir(parents=True,exist_ok=True)
    def get(path):return json.load(urllib.request.urlopen(a.url+path,timeout=30))
    def post(path,body=''):
        return json.load(urllib.request.urlopen(urllib.request.Request(a.url+path,data=body.encode(),method='POST'),timeout=30))
    def until(predicate,deadline=20):
        stop=time.monotonic()+deadline
        while time.monotonic()<stop:
            data=get('/api/status')
            if predicate(data):return data
            time.sleep(.1)
        raise TimeoutError('integrated demo state did not converge')
    def screenshot(name):
        data=urllib.request.urlopen(a.url+'/frame.jpg',timeout=30).read()
        image=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
        assert image.shape==(720,1280,3)
        (evidence/(name+'.png')).write_bytes(cv2.imencode('.png',image)[1].tobytes())
        return hashlib.sha256(image.tobytes()).hexdigest()
    post('/demo/reset');post('/app','raw_board 1 mode 16');post('/demo/start')
    active=until(lambda x:x['demo']['state']=='SETTLE')
    run_id=active['demo']['run_id'];post('/demo/start')
    assert get('/api/status')['demo']['run_id']==run_id, 'duplicate start replaced running scan'
    until(lambda x:x['demo']['completed']>=1)
    post('/demo/reset');time.sleep(.4)
    reset=get('/api/status')['demo']
    assert reset['state']=='READY' and reset['completed']==0 and reset['points']==[] and reset['run_id']!=run_id
    time.sleep(.4);assert get('/api/status')['demo']['completed']==0
    # Native hit tests share the real mouse path (down=1, up=2).
    for kind in [1,2]:post('/pointer',f'{kind} 1120 110 0 0')
    done=until(lambda x:x['demo']['state']=='DONE');session=done['demo']
    assert session['completed']==6 and len(session['pl_calls'])==21 and not done['error']
    assert session['motion_simulated'] and not session['fresh_acquisition'] and not session['hardware_synchronized']
    assert [p['xy_mm'] for p in session['points']]==[[0,0],[5,0],[10,0],[10,5],[5,5],[0,5]]
    ids=[]
    for point in session['points']:
        assert len(point['frames'])==3
        assert point['settled_at']-point['arrival_confirmed_at']>=.7-1e-6
        for frame in point['frames']:
            assert frame['source_xy_mm']==point['xy_mm'] and not frame['fresh_capture']
            assert frame['demo_sample_begin']>=point['settled_at']
            ids.append(frame['demo_capture_id'])
    assert len(set(ids))==18
    assert get('/api/export')['run_id']==session['run_id']
    (evidence/'session.json').write_text(json.dumps(session,ensure_ascii=False,indent=2),encoding='utf8')
    before=get('/api/status')['app']['demo_point']
    for kind in [1,2]:post('/pointer',f'{kind} 1200 214 0 0')
    assert get('/api/status')['app']['demo_point']==(before+1)%6
    post('/app','demo_point 0');time.sleep(.4);screenshot('demo-complete')
    rejected=False
    try:post('/app','demo_point 6')
    except urllib.error.HTTPError as exc:rejected=exc.code==400
    assert rejected
    assert get('/api/status')['app']['demo_point']==0
    states=[]
    for board in [1,0,1]:
        for mode in [0,1,3,6,12,13,14,15,16]:
            response=post('/app',f'raw_board {board} mode {mode}')
            assert response['app']['mode']==mode and response['app']['raw_board']==board
            states.append(dict(board=board,mode=mode,hash=screenshot(f'board-{board}-mode-{mode}')))
    for i in range(9):
        assert states[i]['hash']==states[18+i]['hash'], 'board switch changed source-bound scene'
        assert states[i]['hash']!=states[9+i]['hash'], 'cross-board stale pixels'
    post('/app','mode 3')
    for kind in [1,2]:post('/pointer',f'{kind} 45 292 0 0')
    assert get('/api/status')['app']['mode']==16
    result=dict(passed=True,demo_points=6,demo_frames=18,pl_result_calls=21,page_switch_states=len(states),
                original_ui_native_hit_tests=True,cancel_reset_restart=True,duplicate_start_guard=True,
                export_verified=True,board_isolation=True,board_connected=False,boot_image_modified=False,
                source_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for folder in ['runtime','demo/runtime'] for p in (ROOT/folder).rglob('*') if p.suffix in {'.py','.cpp','.c','.h','.html'}})
    (evidence/'result.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='source_sha256'},indent=2))


if __name__=='__main__':main()
