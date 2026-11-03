"""Copy only the selected build's reports and record their actual numbers."""
from pathlib import Path
import argparse,hashlib,json,re,shutil
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);a=p.parse_args();dest=ROOT/'hardware'
    for source in [*a.work.glob('board-*.rpt'),a.work/'address-map.txt',a.work/'board.bit',a.work/'board.hdf']:shutil.copyfile(source,dest/source.name)
    text=(dest/'board-timing.rpt').read_text(errors='replace')
    row=re.search(r'^\s*(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(\d+)\s+(\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(\d+)\s+(\d+)\s+',text,re.M)
    if not row:raise ValueError('timing summary absent')
    setup,tns,failed,_,hold,ths,hfailed,_=row.groups();passed=float(setup)>=0 and float(hold)>=0 and int(failed)==int(hfailed)==0
    if not passed:raise ValueError('selected build fails timing')
    util=(dest/'board-utilization.rpt').read_text(errors='replace');resources={}
    for key,label in [('lut','Slice LUTs'),('ff','Slice Registers'),('bram36','Block RAM Tile'),('dsp','DSPs')]:
        match=re.search(r'\|\s*'+label+r'\*?\s*\|\s*([\d.]+)\s*\|\s*[\d.]+\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)',util)
        if not match:raise ValueError('resource absent: '+label)
        resources[key]=dict(zip(['used','available','percent'],map(float,match.groups())))
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    result=dict(global_timing=dict(setup_wns_ns=float(setup),setup_tns_ns=float(tns),setup_failing_endpoints=int(failed),hold_whs_ns=float(hold),hold_ths_ns=float(ths),hold_failing_endpoints=int(hfailed)),resources=resources,internal_timing_passed=passed,core_clock_mhz=62.5,resolution=[1280,720],board_tested=False,external_adc_io_signed_off=False,report_sha256={p.name:digest(p) for p in dest.glob('board-*.rpt')},artifact_sha256={p.name:digest(p) for p in [dest/'board.bit',dest/'board.hdf',dest/'address-map.txt']})
    (dest/'summary.json').write_text(json.dumps(result,indent=2));print(json.dumps(result['global_timing']))
if __name__=='__main__':main()
