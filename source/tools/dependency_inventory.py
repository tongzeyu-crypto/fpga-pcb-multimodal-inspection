"""Record development package versions and their shipped license notices."""
from pathlib import Path
import hashlib,importlib.metadata as md,json
ROOT=Path(__file__).resolve().parents[1]
def main():
    records=[];dest=ROOT/'resources/licenses';dest.mkdir(parents=True,exist_ok=True)
    for name in ['torch','numpy','opencv-python-headless','Pillow','scipy']:
        try:d=md.distribution(name)
        except md.PackageNotFoundError:records.append({'package':name,'installed_in_checked_development_environment':False});continue
        record={'package':name,'version':d.version,'license_expression':d.metadata.get('License-Expression'),'license_metadata':d.metadata.get('License'),'shipped_notices':[],'bundled_dependency_binary':False}
        for f in d.files or []:
            # Top-level distribution notices, not unrelated package source trees.
            if '.dist-info/' in str(f).replace('\\','/') and f.name.upper() in {'LICENSE','LICENSE.TXT','LICENSE.APACHE-2.0','LICENSE.BSD-3-CLAUSE','NOTICE'}:
                source=d.locate_file(f)
                if source.is_file():
                    data=source.read_bytes();out=dest/(name+'-'+f.name);out.write_bytes(data);record['shipped_notices'].append({'file':out.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(data).hexdigest()})
        records.append(record)
    (ROOT/'evidence/development-dependencies.json').write_text(json.dumps(records,indent=2),encoding='utf8');print(json.dumps([{'package':r['package'],'version':r.get('version'),'notices':len(r.get('shipped_notices',[]))} for r in records]))
if __name__=='__main__':main()
