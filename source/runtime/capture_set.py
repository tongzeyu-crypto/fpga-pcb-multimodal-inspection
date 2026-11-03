"""Process each board independently and assemble one original-UI asset set."""
from pathlib import Path
import json,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
def prepare(paths,state,active,reference=None,annotations=None,calibration=None,offline_test=False):
    from .service import process
    from .capture_bundle import load
    state=Path(state);display=state/'display';display.mkdir(parents=True,exist_ok=False);index={}
    for board,path in paths.items():
        path=Path(path).resolve();load(path,board);computed=state/('computed-'+board)
        ref=reference if board==active else None
        process(path,computed,ref,offline_test,calibration if board==active else None,annotations if board==active else None)
        assets=state/('assets-'+board)
        command=[sys.executable,str(ROOT/'tools/build_display_assets.py'),'--bundle',str(path),'--output',str(assets),'--processing',str(computed/'processing.json')]
        if ref:command+=['--reference',str(Path(ref).resolve())]
        subprocess.run(command,check=True)
        source=assets/('dcdc' if board=='dcdc' else '');destination=display/('dcdc' if board=='dcdc' else '')
        for item in source.iterdir():
            if item.name=='dcdc':continue
            target=destination/item.name;target.parent.mkdir(parents=True,exist_ok=True)
            if item.is_dir():shutil.copytree(item,target,dirs_exist_ok=True)
            else:shutil.copyfile(item,target)
        index[board]=dict(bundle=str(path),processing=str((computed/'processing.json').resolve()))
    # The native renderer always has two slots; unprovided boards keep explicit
    # empty-state metadata rather than borrowing another board's measurements.
    if len(index)==1:
        source=state/('assets-'+next(iter(index)))
        empty=source if 'dcdc' in index else source/'dcdc';target=display if 'dcdc' in index else display/'dcdc'
        for item in empty.iterdir():
            if item.name=='dcdc':continue
            if not (target/item.name).exists():
                if item.is_dir():shutil.copytree(item,target/item.name)
                else:(target/item.name).parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(item,target/item.name)
    (display/'generation.json').write_text(json.dumps({'boards':index,'active_board':active,'source_bound':True},indent=2))
    (state/'capture-index.json').write_text(json.dumps(index,indent=2))
    return display,state/'capture-index.json'
