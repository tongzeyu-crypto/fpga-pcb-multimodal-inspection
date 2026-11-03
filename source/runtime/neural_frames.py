"""Native-render and neural-pixel-fusion offline demonstration helpers."""
from pathlib import Path
import json, shutil, subprocess
import numpy as np


class NativeRenderer:
    def __init__(self,binary,assets,prefix):
        self.prefix=Path(prefix)
        self.process=subprocess.Popen([str(binary),str(assets),str(prefix)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    def command(self,line):
        self.process.stdin.write((line+'\n').encode());self.process.stdin.flush()
        result=json.loads(self.process.stdout.readline())
        if result.get('error'):raise RuntimeError(result['error'])
        return result
    def save(self,prefix):
        for suffix in ['.argb','.depth.u16','.u16','.matrix']:
            shutil.copyfile(str(self.prefix)+suffix,str(prefix)+suffix)
    def __enter__(self):return self
    def __exit__(self,*args):
        self.process.stdin.close()
        try:self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:self.process.terminate();self.process.wait(timeout=5)
        if self.process.returncode:raise RuntimeError('offline renderer stopped: '+self.process.stderr.read().decode(errors='replace'))
        self.process.stdout.close();self.process.stderr.close()


def render_pair(engine,work,mode,yaw,polar,step):
    source,target=Path(work)/'source',Path(work)/'truth'
    base=f'raw_board 1 mode {mode} hud 0 cursor_visible 0 points 0 autorotate 0 base 1 polar {polar} '
    engine.command('app '+base+f'yaw {yaw}');engine.save(source)
    engine.command('app '+base+f'yaw {yaw+step}');engine.save(target)
    return source,target


def read_rgb(path):return np.fromfile(path,np.uint8).reshape(720,1280,4)[...,:3]
