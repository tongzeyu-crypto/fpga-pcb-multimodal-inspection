"""Package the current release/debug snapshot without inventing board results."""
from pathlib import Path
import argparse,hashlib,json,re,subprocess,sys,zipfile
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path);p.add_argument('--root',type=Path,default=ROOT);a=p.parse_args();root=a.root.resolve()
    version=json.loads((root/'VERSION.json').read_text(encoding='utf8'))
    if not json.loads((root/'evidence/combined/result.json').read_text())['passed']:raise ValueError('combined build not passed')
    metadata={'FILE_MANIFEST.json','SOURCE_SHA256.json','DELIVERY_CHECK.json'}
    folders=['runtime','demo','drivers','rtl','graphics','models','tools','tests','docs','resources','bin','data','evidence','hardware','debug']
    files=[q for q in root.iterdir() if q.is_file() and q.name not in metadata and q.suffix in {'.md','.json','.sh','.cmd','.ps1'}]
    for folder in folders:
        for q in (root/folder).rglob('*'):
            if not q.is_file() or any(x in {'__pycache__','.git','.Xil','xsim.dir'} for x in q.parts) or q.suffix in {'.pyc','.dcp','.pb'}:continue
            if version['profile']=='release' and q.is_relative_to(root/'data/derived'):continue
            if version['profile']=='release' and (q.is_relative_to(root/'debug') or any(x.startswith('combined-before-') for x in q.relative_to(root).parts)):continue
            files.append(q)
    files=sorted(set(files));manifest={}
    for q in files:
        name=q.relative_to(root).as_posix();raw=q.read_bytes()
        if re.search(r'(?i)(id_rsa|id_ed25519|ssh_config|\.pem$|\.env$)',name):raise ValueError('credential filename '+name)
        if q.suffix in {'.py','.json','.md','.txt','.log','.c','.h','.cpp','.tcl','.sv','.v','.dts','.dtsi','.sh'} and re.search(rb'-----BEGIN (?:OPENSSH|RSA|EC) PRIVATE KEY-----|(?:sk-proj-|ghp_)[A-Za-z0-9_-]{20,}',raw):raise ValueError('credential content '+name)
        manifest[name]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    (root/'FILE_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    source={k:v for k,v in manifest.items() if Path(k).suffix in {'.py','.c','.cpp','.h','.sv','.v','.tcl','.xdc','.dts','.dtsi','.sh','.cmd','.ps1','.html'} or k.endswith('Makefile')}
    (root/'SOURCE_SHA256.json').write_text(json.dumps(source,ensure_ascii=False,indent=2),encoding='utf8')
    check=json.loads((root/'DELIVERY_CHECK.json').read_text(encoding='utf8'));check.update(profile=version['profile'],version_label=version['label'],files=len(files),bytes=sum(v['bytes'] for v in manifest.values()),credential_scan_matches=[],hardware_included=True,debug_intermediates_included=version['profile']=='debug',derived_measurement_outputs_excluded=version['profile']=='release')
    (root/'DELIVERY_CHECK.json').write_text(json.dumps(check,ensure_ascii=False,indent=2),encoding='utf8')
    subprocess.run([sys.executable,str(root/'tools/verify_delivery.py'),'--root',str(root)],check=True)
    output={'root':str(root),'files':len(files),'bytes':check['bytes']}
    if a.archive:
        with zipfile.ZipFile(a.archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for q in files+[root/n for n in sorted(metadata)]:z.write(q,root.name+'/'+q.relative_to(root).as_posix())
        digest=hashlib.sha256(a.archive.read_bytes()).hexdigest();a.archive.with_suffix(a.archive.suffix+'.sha256').write_text(digest+'  '+a.archive.name+'\n',encoding='utf8')
        subprocess.run([sys.executable,str(root/'tools/verify_delivery.py'),'--zip',str(a.archive)],check=True);output.update(zip_bytes=a.archive.stat().st_size,zip_sha256=digest)
    print(json.dumps(output,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
