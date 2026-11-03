"""Check evidence/source identity and make the small, self-contained demo ZIP."""
from pathlib import Path
import argparse,hashlib,json,re,zipfile
ROOT=Path(__file__).resolve().parents[1]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads((ROOT/path).read_text(encoding='utf8'))
def main():
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True);a=p.parse_args()
    rtl=read('evidence/rtl-verification.json');ooc=read('evidence/ooc/result.json');arm=read('evidence/arm-build.json');session=read('output/example_run/demo-result.json')
    if not all([rtl['passed'],ooc['passed'],arm['passed']]):raise ValueError('Unpassed build evidence')
    for evidence in [rtl,ooc]:
        if any(sha(ROOT/'rtl'/name)!=expected for name,expected in evidence['source_sha256'].items()):raise ValueError('RTL/evidence mismatch')
    if sha(ROOT/'runtime/pl_demo.cpp')!=arm['source_sha256'] or sha(ROOT/'bin/pl_demo')!=arm['sha256']:raise ValueError('ARM client/source mismatch')
    ps=(ROOT/'evidence/ps-tests.log').read_text(encoding='utf8')
    if 'Ran 5 tests' not in ps or not ps.strip().endswith('OK'):raise ValueError('PS tests unpassed')
    if not session['motion_simulated'] or session['fresh_acquisition'] or sha(ROOT/'inputs/demo-inputs.json')!=session['input_sha256']:raise ValueError('Demo/source labels mismatch')
    if len(session['points'])!=6 or sum(len(p['frames']) for p in session['points'])!=18:raise ValueError('Incomplete demo route')
    for point in session['points']:
        if point['settled_at']-point['arrival_confirmed_at']<point['settle_s']-1e-9:raise ValueError('Sample settling violation')
        for frame in point['frames']:
            if frame['demo_sample_begin']<point['settled_at'] or frame['source_xy_mm']!=point['xy_mm'] or frame['fresh_capture']:raise ValueError('Incorrect point/sample association')
    delivery={'date':'2026-11-03','rtl_jobs':rtl['job_count'],'rtl_outputs_checked':rtl['checked_output_elements'],'ps_tests_passed':5,'demo_points':6,'demo_frames':18,'arm_client_built':True,'independent_ooc_passed':True,'setup_ns':ooc['setup_ns'],'hold_ns':ooc['hold_ns'],'resources':ooc['resources'],'integrated_in_prior_bitstream':False,'board_connected':False,'original_autoboot_modified':False,'ps_source_sha256':sha(ROOT/'runtime/scan_demo.py')}
    (ROOT/'DELIVERY.json').write_text(json.dumps(delivery,ensure_ascii=False,indent=2),encoding='utf8')
    files=sorted(p for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.dcp','.bit','.hdf'} and p.name!='FILE_MANIFEST.json')
    for path in files:
        if re.search(r'id_rsa|id_ed25519|ssh_config|\.pem$',path.name,re.I):raise ValueError('Credential filename blocked')
        if path.suffix in {'.py','.json','.txt','.md','.log','.c','.cpp','.sv'} and re.search(rb'-----BEGIN (OPENSSH|RSA|EC) PRIVATE KEY-----|(?:sk-proj-|ghp_)[A-Za-z0-9_-]{20,}',path.read_bytes()):raise ValueError('Credential content blocked')
    manifest={p.relative_to(ROOT).as_posix():{'bytes':p.stat().st_size,'sha256':sha(p)} for p in files}
    (ROOT/'FILE_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    prefix=ROOT.name+'/'
    with zipfile.ZipFile(a.archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path in files+[ROOT/'FILE_MANIFEST.json']:archive.write(path,prefix+path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(a.archive) as archive:
        if archive.testzip():raise ValueError('ZIP CRC failure')
        for name,expected in manifest.items():
            blob=archive.read(prefix+name)
            if len(blob)!=expected['bytes'] or hashlib.sha256(blob).hexdigest()!=expected['sha256']:raise ValueError('ZIP file hash mismatch')
    a.archive.with_suffix(a.archive.suffix+'.sha256').write_text(sha(a.archive)+'  '+a.archive.name+'\n',encoding='utf8')
    print(json.dumps({'passed':True,'files':len(manifest),'zip_bytes':a.archive.stat().st_size,'sha256':sha(a.archive)},indent=2))
if __name__=='__main__':main()
