"""Explicit allowlist importer. Development only; never contacts a board.

All machine-local discovery paths are command line arguments, not runtime paths.
"""
from pathlib import Path
import argparse, hashlib, json, shutil

ROOT = Path(__file__).resolve().parents[1]
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def copy_tree(src, dst, extensions):
    for p in src.rglob('*'):
        if p.is_file() and p.suffix.lower() in extensions and '__pycache__' not in p.parts:
            q=dst/p.relative_to(src); q.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(p,q)
def main():
    a=argparse.ArgumentParser()
    for name in ['native','graphics','capture','scan','bootstrap']: a.add_argument('--'+name,type=Path,required=True)
    x=a.parse_args()
    copy_tree(x.native/'src',ROOT/'runtime/display', {'.cpp','.h'})
    for folder in ['rtl','include','driver','integration']:
        copy_tree(x.graphics/folder,ROOT/'graphics'/folder,{'.sv','.v','.h','.c','.tcl','.xdc'})
    for name in ['camera_stream.c','camera_capture.c','grbl_control.c','grbl_guard.h']:
        shutil.copyfile(x.bootstrap/'src'/name, ROOT/'runtime'/name)
    raw=ROOT/'data/raw/dcdc-rgb-thermal'; raw.mkdir(parents=True,exist_ok=True)
    for name in ['capture.json','rgb.jpg','thermal.raw','thermal-calibration.json']:
        shutil.copyfile(x.capture/name,raw/name)
    for name in ['board-v3.glb','board_geometry.json','model-v3.json']:
        q=ROOT/'resources/models'/name;q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(x.capture/name,q)
    scan=ROOT/'data/raw/dcdc-adc';scan.mkdir(parents=True,exist_ok=True)
    # Only acquisition records, no JTAG programs, keys, broker logs or results.
    for name in ['session.json','points.jsonl','motion.jsonl']:
        shutil.copyfile(x.scan/name,scan/name)
    for p in sorted((x.scan/'points').rglob('*')):
        if p.is_file() and (p.name.startswith('capture_') and p.suffix in {'.csv','.json'} or p.name in {'point.json','position.json'}):
            q=scan/'points'/p.relative_to(x.scan/'points');q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,q)
    manifest={p.relative_to(ROOT/'data/raw').as_posix(): {'sha256':sha(p),'bytes':p.stat().st_size} for p in (ROOT/'data/raw').rglob('*') if p.is_file()}
    (ROOT/'data/raw-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    (ROOT/'evidence/source-import.json').write_text(json.dumps({'raw_files':len(manifest),'adc_csv_count':len(list(scan.rglob('capture_*.csv'))),'policy':'explicit source allowlist; no credentials or historical computed measurement assets'},indent=2))
    print('Imported',len(manifest),'raw files')
if __name__=='__main__': main()
