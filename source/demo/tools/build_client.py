from pathlib import Path
import argparse,hashlib,json,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser();p.add_argument('--cxx',type=Path,required=True);p.add_argument('--work',type=Path,required=True);a=p.parse_args();a.work.mkdir(parents=True,exist_ok=True)
    source=ROOT/'runtime/pl_demo.cpp';shutil.copyfile(source,a.work/source.name)
    result=subprocess.run([str(a.cxx),'-std=c++14','-O2','-Wall','-Wextra','pl_demo.cpp','-o','pl_demo'],cwd=a.work,capture_output=True)
    (ROOT/'evidence/arm-build.log').write_bytes(result.stdout+result.stderr)
    report={'exit_code':result.returncode,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'board_executed':False}
    if result.returncode==0:
        blob=(a.work/'pl_demo').read_bytes();report['elf32_little_endian_arm']=blob[:6]==b'\x7fELF\x01\x01' and int.from_bytes(blob[18:20],'little')==40
        report['sha256']=hashlib.sha256(blob).hexdigest();(ROOT/'bin').mkdir(exist_ok=True);(ROOT/'bin/pl_demo').write_bytes(blob)
    report['passed']=result.returncode==0 and report.get('elf32_little_endian_arm',False)
    (ROOT/'evidence/arm-build.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2));return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
