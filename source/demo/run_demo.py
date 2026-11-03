"""One-command offline run. No board, serial port or network is opened."""
from pathlib import Path
import importlib.util,subprocess,sys,time
ROOT=Path(__file__).resolve().parent
output=ROOT/'output'/('run_'+str(time.monotonic_ns()))
print('离线演示：模拟运动、历史原始数据、RTL 已核验结果回放。',flush=True)
subprocess.run([sys.executable,'-m','runtime.scan_demo','--replay','--output',str(output)],cwd=ROOT,check=True)
if importlib.util.find_spec('PIL'):
    subprocess.run([sys.executable,'tools/render_demo.py','--run',str(output)],cwd=ROOT,check=True)
print('输出目录：',output)
