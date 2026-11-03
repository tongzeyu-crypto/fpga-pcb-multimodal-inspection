"""CaptureBundle v1: strict provenance, board isolation, hash and path checks."""
from pathlib import Path
import hashlib,json

ALLOWED={'rgb':{'ZYNQ_USB_REAL'},'thermal':{'ZYNQ_USB_REAL'},'adc':{'ZYNQ_ADC_ILA_RAW','ZYNQ_ADC_AXI_RAW'}}
class MissingInput(RuntimeError): pass
def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(bundle_path,board_id=None):
    p=Path(bundle_path).resolve(); b=json.loads(p.read_text(encoding='utf8'))
    if b.get('schema')!='CaptureBundle/1' or not b.get('capture_id') or not b.get('calibration_version'): raise ValueError('bundle identity/calibration missing')
    if board_id is not None and b['board_id']!=board_id: raise ValueError('cross-board data rejected')
    if b['board_id'] not in {'dcdc','stm32'}:raise ValueError('unknown board')
    for kind,items in b['raw'].items():
        if kind not in ALLOWED: raise ValueError('unsupported raw modality')
        for item in items:
            if item['source'] not in ALLOWED[kind]: raise ValueError('non-Zynq measurement rejected')
            for k in ['sha256','timestamp','dimensions','unit','batch_id']: 
                if not item.get(k):raise ValueError('missing provenance: '+k)
            if item['batch_id'] not in b['acquisition_batches']:raise ValueError('unlinked acquisition batch')
            rel=Path(item['path'])
            if rel.is_absolute() or '..' in rel.parts or ':' in str(rel):raise ValueError('nonportable raw path')
            q=(p.parent/rel).resolve()
            if p.parent not in q.parents or not q.is_file() or digest(q)!=item['sha256']:raise ValueError('raw hash/path mismatch')
    return b
def require(b,kind):
    if not b['raw'].get(kind):raise MissingInput(kind+' unavailable; waiting for Zynq acquisition')
    return b['raw'][kind]
class Session:
    def __init__(self):self.board=None;self.bundle=None;self.derived={};self.render_history=[]
    def select(self,board):
        if board!=self.board:self.board=board;self.bundle=None;self.derived.clear();self.render_history.clear()
    def attach(self,path):
        self.bundle=load(path,self.board);self.derived.clear();self.render_history.clear()
    def measurement(self,kind):
        if self.bundle is None:raise MissingInput('No capture for selected board')
        return require(self.bundle,kind)
