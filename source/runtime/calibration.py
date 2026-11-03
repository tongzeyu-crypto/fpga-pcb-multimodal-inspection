"""Portable, source-bound camera/board calibration for saved and fresh bundles."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
def resolve(bundle,bundle_path,override=None):
    root=Path(bundle_path).resolve().parent
    if override is not None:path=Path(override).resolve()
    elif bundle.get('calibration'):
        entry=bundle['calibration'];relative=Path(entry['path'])
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('calibration path')
        path=(root/relative).resolve()
        if root not in path.parents or hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('calibration source mismatch')
    else:
        legacy=root/'dcdc-rgb-thermal/thermal-calibration.json'
        path=legacy if legacy.exists() else ROOT/'resources/calibration'/('dcdc-initial.json' if bundle['board_id']=='dcdc' else 'stm32-initial.json')
    value=json.loads(path.read_text(encoding='utf8'));matrix=value.get('matrix_thermal_to_extended_rgb')
    if not isinstance(matrix,list) or len(matrix)!=3 or any(len(row)!=3 for row in matrix):raise ValueError('calibration transform shape')
    if value.get('board_id',bundle['board_id'])!=bundle['board_id']:raise ValueError('calibration board mismatch')
    return value,path

def publish(bundle,output,source):
    output=Path(output);blob=Path(source).read_bytes();(output/'calibration.json').write_bytes(blob)
    bundle['calibration']=dict(path='calibration.json',sha256=hashlib.sha256(blob).hexdigest())
    bundle['calibration_version']=hashlib.sha256(blob).hexdigest()[:16]
