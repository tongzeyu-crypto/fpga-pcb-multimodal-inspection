"""Prove display generation consumes signed processing outputs, not PS FFT.

Runs on the explicit offline processing fixture. This is a consumer test,
not evidence that a PL device was present.
"""
from pathlib import Path
import argparse,hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import build_display_assets as assets
def main():
    p=argparse.ArgumentParser();p.add_argument('--computed',type=Path,required=True);p.add_argument('--work',type=Path,required=True);a=p.parse_args();a.work.mkdir(exist_ok=True,parents=True)
    def forbidden(*args,**kwargs):raise AssertionError('display attempted a PS numeric recomputation')
    assets.thermal_decode=forbidden;assets.spectrum_three=forbidden
    command=['build_display_assets.py','--bundle',str(ROOT/'data/raw/dcdc.bundle.json'),'--processing',str(a.computed/'processing.json'),'--output',str(a.work/'assets')]
    sys.argv=command;assets.main();assert (a.work/'assets/generation.json').is_file()
    path=next(a.computed.glob('point-*-psd.f32'));original=path.read_bytes()
    rejected=False
    try:
        path.write_bytes(bytes([original[0]^1])+original[1:]);sys.argv=command[:-1]+[str(a.work/'corrupt')]
        try:assets.main()
        except ValueError as e:rejected='processing output hash' in str(e)
    finally:path.write_bytes(original)
    assert rejected,'altered compute output was accepted'
    evidence=ROOT/'evidence/report-consumers';evidence.mkdir(exist_ok=True)
    (evidence/'result.json').write_text(json.dumps(dict(passed=True,display_recomputes_ps_fft=False,display_recomputes_ps_temperature=False,corrupt_output_rejected=True,board_connected=False,source_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'tools/build_display_assets.py',ROOT/'runtime/service.py',Path(__file__)]}),indent=2))
    print('PROCESSING_CONSUMERS_PASS')
if __name__=='__main__':main()
