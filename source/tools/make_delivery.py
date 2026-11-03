"""Refresh integrity manifests and package the maintained formal release."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
GENERATED = {'FILE_MANIFEST.json', 'SOURCE_SHA256.json', 'DELIVERY_CHECK.json'}
FOLDERS = {'runtime', 'demo', 'drivers', 'rtl', 'graphics', 'models', 'tools',
           'tests', 'docs', 'resources', 'bin', 'hardware', 'evidence', 'data'}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args()
    board = json.loads((ROOT/'evidence/board-20261103-r1/result.json').read_text(encoding='utf8'))
    if not board.get('board_demo_passed'):
        raise RuntimeError('Formal packaging requires the recorded board-demo result')
    files = []
    for path in ROOT.rglob('*'):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if rel.as_posix() in GENERATED or '__pycache__' in rel.parts or path.suffix == '.pyc':
            continue
        if len(rel.parts) > 1 and rel.parts[0] not in FOLDERS:
            continue
        if rel.parts[:2] == ('data', 'derived'):
            continue
        if re.search(r'(?i)(board_.*_key|id_rsa|id_ed25519|ssh_config|[.]pem$|[.]env$)', rel.as_posix()):
            raise RuntimeError('Credential-like filename blocked: ' + rel.as_posix())
        if path.suffix.lower() in {'.py','.json','.md','.txt','.log','.c','.h','.cpp','.tcl','.sv','.v','.dts','.dtsi'}:
            if re.search(rb'-----BEGIN (?:OPENSSH|RSA|EC) PRIVATE KEY-----|(?:sk-proj-|ghp_)[A-Za-z0-9_-]{20,}', path.read_bytes()):
                raise RuntimeError('Credential-like content blocked: ' + rel.as_posix())
        files.append(path)
    manifest = {p.relative_to(ROOT).as_posix(): {'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(files)}
    (ROOT/'FILE_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    source = {k:v for k,v in manifest.items() if Path(k).suffix in {'.py','.cpp','.c','.h','.html','.ps1','.cmd','.sh','.sv','.v','.tcl','.xdc','.dts','.dtsi'} or k.endswith('Makefile')}
    (ROOT/'SOURCE_SHA256.json').write_text(json.dumps(source,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    check = json.loads((ROOT/'DELIVERY_CHECK.json').read_text(encoding='utf8'))
    check.update({'files':len(files),'bytes':sum(p.stat().st_size for p in files),
                  'credential_scan_matches':[],'documentation_revision':'r2'})
    (ROOT/'DELIVERY_CHECK.json').write_text(json.dumps(check,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    if args.archive:
        args.archive.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(args.archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for path in sorted(files + [ROOT/n for n in sorted(GENERATED)]):
                archive.write(path,'submission_zynq_20261103/'+path.relative_to(ROOT).as_posix())
        with zipfile.ZipFile(args.archive) as archive:
            bad = archive.testzip()
            if bad:
                raise RuntimeError('ZIP CRC: '+bad)
        args.archive.with_suffix(args.archive.suffix+'.sha256').write_text(sha(args.archive)+'  '+args.archive.name+'\n',encoding='utf8')
    print(json.dumps({'files':len(files),'documentation_revision':'r2','board_demo_passed':True}))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
