from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
def model(board):
    if board not in ('stm32','dcdc'):raise ValueError('unknown board profile')
    return json.loads((ROOT/'resources/models'/('model-v3.json' if board=='dcdc' else 'stm32-model-v3.json')).read_text(encoding='utf8'))
def captures(index=None):
    path=Path(index or ROOT/'data/board-index.json').resolve()
    value=json.loads(path.read_text(encoding='utf8'));result={}
    for board,entry in value.items():
        candidate=Path(entry['bundle']);candidate=candidate if candidate.is_absolute() else (ROOT/candidate)
        from .capture_bundle import load
        load(candidate,board);result[board]=candidate.resolve()
    return result
