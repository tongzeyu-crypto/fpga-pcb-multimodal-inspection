"""Build the original UI's offline renderer, without Vivado or board access."""
from pathlib import Path
import argparse, gzip, hashlib, json, shutil, struct, subprocess, sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def extend_glyphs():
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    from tools.build_display_assets import texture
    ui = ROOT/'resources/ui'
    glyphs = list(struct.iter_unpack('<I6H', (ui/'glyphs.bin').read_bytes()))
    known = {g[0] for g in glyphs}
    text = ''.join((ROOT/p).read_text(encoding='utf8') for p in ['runtime/display/driver/full_demo.h','runtime/display/driver/full_raw.h'])
    extra = sorted({ord(c) for c in text if ord(c) >= 0x4e00}-known)
    if not extra: return
    raw = np.frombuffer(gzip.decompress((ui/'ui.bin.gz').read_bytes()), np.uint8, count=2048*2048*4)
    atlas = raw.reshape(512,256,2,4,2,2,4).transpose(0,2,4,1,3,5,6).reshape(2048,2048,4).copy()
    font_path = Path('C:/Windows/Fonts/msyh.ttc')
    font = ImageFont.truetype(str(font_path), 24)
    occupied = {(g[1]//32,g[2]//32) for g in glyphs}
    slots = ((x,y) for y in range(24,44) for x in range(64) if (x,y) not in occupied)
    for code in extra:
        x,y = next(slots);image = Image.new('RGBA',(32,32));ImageDraw.Draw(image).text((0,0),chr(code),font=font,fill='white')
        pixels = np.array(image);atlas[y*32:y*32+32,x*32:x*32+32] = pixels[..., [2,1,0,3]]
        glyphs.append((code,x*32,y*32,32,32,int(round(font.getlength(chr(code)))),0))
    texture(ui/'ui.bin', atlas)
    (ui/'glyphs.bin').write_bytes(b''.join(struct.pack('<I6H',*g) for g in glyphs))
    (ui/'demo-glyphs.json').write_text(json.dumps(dict(added_codes=extra,font='Microsoft YaHei 24px',original_glyphs_preserved=True),indent=2))


def build(work, cxx, assets=None, install=True):
    work = Path(work); work.mkdir(parents=True,exist_ok=True)
    if not str(work).isascii(): raise ValueError('host renderer build directory must use ASCII characters')
    shutil.copytree(ROOT/'runtime/display',work/'src',dirs_exist_ok=True)
    runtime = (ROOT/'runtime/display/driver/gfx3_runtime.cpp').read_text(encoding='utf8')
    generated = runtime[runtime.index('static void full_input_locked('):runtime.index('#include "full_mouse.h"')]+ '\n' + runtime[runtime.index('static std::string full_app_json('):runtime.index('#include "bounded_workers.h"')]
    (work/'reference-generated.h').write_text(generated,encoding='utf8')
    source = (ROOT/'tests/reference_bridge.cpp').read_text(encoding='utf8')
    (work/'reference.cpp').write_text(source,encoding='utf8')
    result = subprocess.run([str(cxx),'-std=c++14','-O2','-static','-finput-charset=UTF-8','-fexec-charset=UTF-8','-I',str(work),str(work/'reference.cpp'),'-o',str(work/'demo_reference.exe')],capture_output=True)
    evidence=ROOT/'evidence/demo-integration' if install else work/'evidence';evidence.mkdir(parents=True,exist_ok=True)
    (evidence/'host-build.log').write_bytes(result.stdout+result.stderr)
    if result.returncode: raise RuntimeError('host build failed; see evidence/demo-integration/host-build.log')
    binary=ROOT/'bin/demo_reference.exe' if install else work/'demo_reference.exe'
    if install:shutil.copyfile(work/'demo_reference.exe',binary)
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'runtime/display').rglob('*') if p.suffix in {'.h','.cpp'}}
    hashes['tests/reference_bridge.cpp']=hashlib.sha256((ROOT/'tests/reference_bridge.cpp').read_bytes()).hexdigest()
    (evidence/'host-build.json').write_text(json.dumps(dict(passed=True,binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),source_sha256=hashes,board_connected=False),indent=2))
    return binary


def prepare_assets(work, bundle=None, reference=None):
    from runtime.service import process
    work=Path(work);asset_root=work/'assets';asset_root.mkdir(parents=True,exist_ok=True)
    bundle=Path(bundle or ROOT/'data/raw/dcdc.bundle.json')
    process(bundle,work/'computed',reference,offline_test=True)
    cmd=[sys.executable,str(ROOT/'tools/build_display_assets.py'),'--bundle',str(bundle),'--output',str(asset_root),'--processing',str(work/'computed/processing.json')]
    if reference:cmd+=['--reference',str(reference)]
    subprocess.run(cmd,check=True,cwd=ROOT)
    for p in asset_root.rglob('*.gz'):
        p.with_suffix('').write_bytes(gzip.decompress(p.read_bytes()))
    if bundle.resolve()==(ROOT/'data/raw/dcdc.bundle.json').resolve() and (ROOT/'data/raw/stm32.bundle.json').exists():
        second=ROOT/'data/raw/stm32.bundle.json';process(second,work/'computed-stm32',offline_test=True)
        subprocess.run([sys.executable,str(ROOT/'tools/build_display_assets.py'),'--bundle',str(second),'--output',str(work/'stm32-display'),'--processing',str(work/'computed-stm32/processing.json')],check=True,cwd=ROOT)
        for path in (work/'stm32-display').iterdir():
            if path.name!='dcdc':
                if path.is_dir():shutil.copytree(path,asset_root/path.name,dirs_exist_ok=True)
                else:shutil.copyfile(path,asset_root/path.name)
        for path in asset_root.rglob('*.gz'):path.with_suffix('').write_bytes(gzip.decompress(path.read_bytes()))
        (asset_root/'generation.json').write_text(json.dumps({'boards':['stm32','dcdc'],'source_bound':True,'adc_available':['dcdc']},indent=2))
    return asset_root


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);p.add_argument('--cxx',type=Path,required=True);p.add_argument('--extend-glyphs',action='store_true');p.add_argument('--prepare-assets',action='store_true');a=p.parse_args()
    if a.extend_glyphs:extend_glyphs()
    build(a.work,a.cxx)
    if a.prepare_assets:prepare_assets(a.work)
    print('Main UI demo host build passed')
