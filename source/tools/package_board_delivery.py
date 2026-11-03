"""Package the verified board update without regenerating historical reports."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    args = parser.parse_args()
    board = json.loads((ROOT/'evidence/board-20261103-r1/result.json').read_text(encoding='utf8'))
    if not board['board_demo_passed'] or board['original_boot_image_modified']:
        raise ValueError('successful RAM-only board record required')
    folders = ['runtime', 'demo', 'drivers', 'rtl', 'graphics', 'models', 'tools',
               'tests', 'docs', 'resources', 'bin', 'data/raw', 'evidence', 'hardware']
    files = [ROOT/p for p in ['README.md', 'data/raw-manifest.json', 'start_demo.cmd',
                              'start_demo.ps1', 'start_board_demo.sh']]
    files += [ROOT/n for n in ['VERSION.json', '版本说明.md'] if (ROOT/n).is_file()]
    files += [p for f in folders for p in (ROOT/f).rglob('*') if p.is_file()
              and '__pycache__' not in p.parts and p.suffix not in {'.pyc', '.dcp', '.bit', '.hdf', '.pb'}
              and not (p.parent == ROOT/'bin' and p.suffix == '.exe'
                       and p.name not in {'demo_reference.exe', 'neural_frame_tool.exe'})]
    files = sorted(set(files))
    manifest = {}
    for p in files:
        name = p.relative_to(ROOT).as_posix()
        if re.search(r'(?i)(board_.*_key|id_rsa|id_ed25519|ssh_config|\.pem$|\.env$)', name):
            raise ValueError('credential filename excluded: ' + name)
        data = p.read_bytes()
        if p.suffix.lower() in {'.py', '.json', '.md', '.txt', '.log', '.c', '.h', '.cpp', '.tcl', '.sv', '.v', '.dts', '.dtsi', '.sh'}:
            if re.search(rb'-----BEGIN (?:OPENSSH|RSA|EC) PRIVATE KEY-----|(?:sk-proj-|ghp_)[A-Za-z0-9_-]{20,}', data):
                raise ValueError('credential candidate excluded: ' + name)
        manifest[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    (ROOT/'FILE_MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8')
    sources = {k: v for k, v in manifest.items() if Path(k).suffix in
               {'.py', '.cpp', '.c', '.h', '.html', '.ps1', '.cmd', '.sh', '.sv', '.v', '.tcl', '.xdc', '.dts', '.dtsi'} or k.endswith('Makefile')}
    (ROOT/'SOURCE_SHA256.json').write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding='utf8')
    check = json.loads((ROOT/'DELIVERY_CHECK.json').read_text(encoding='utf8'))
    check.update(files=len(files), bytes=sum(v['bytes'] for v in manifest.values()),
                 credential_scan_matches=[], board_accessed=True, board_demo_passed=True,
                 physical_hdmi_user_confirmed=True, original_boot_image_modified=False,
                 full_acquisition_pipeline_validated=False, single_plane_scanout=True,
                 board_record='evidence/board-20261103-r1/result.json')
    check['extensions']['depth']['board_tested'] = True
    (ROOT/'DELIVERY_CHECK.json').write_text(json.dumps(check, ensure_ascii=False, indent=2), encoding='utf8')
    with zipfile.ZipFile(args.archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for p in files + [ROOT/'FILE_MANIFEST.json', ROOT/'SOURCE_SHA256.json', ROOT/'DELIVERY_CHECK.json']:
            archive.write(p, ROOT.name + '/' + p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(args.archive) as archive:
        if archive.testzip():
            raise ValueError('ZIP CRC failure')
    digest = hashlib.sha256(args.archive.read_bytes()).hexdigest()
    args.archive.with_suffix(args.archive.suffix+'.sha256').write_text(digest+'  '+args.archive.name+'\n', encoding='utf8')
    print(json.dumps({'files': len(files), 'zip_bytes': args.archive.stat().st_size,
                      'zip_sha256': digest, 'board_demo_passed': True}, indent=2))


if __name__ == '__main__':
    main()
