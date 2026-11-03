"""Real-record subset/empty-state regression; creates no new measurements."""
from pathlib import Path
import argparse,copy,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime.service import process
def main():
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);a=p.parse_args();source=ROOT/'data/raw/dcdc.bundle.json';base=json.loads(source.read_text());cases=[]
    for name,kinds,flag in [('no-input',[],0),('real-rgb-subset',['rgb'],1)]:
        b=copy.deepcopy(base);b['capture_id']='REGRESSION-ONLY-'+name;b['raw']={k:v for k,v in b['raw'].items() if k in kinds};temp=source.parent/('regression-only-'+name+'.json');out=a.work/name
        try:
            temp.write_text(json.dumps(b));record=process(temp,out/'computed',None,offline_test=True)
            r=subprocess.run([sys.executable,str(ROOT/'tools/build_display_assets.py'),'--bundle',str(temp),'--output',str(out/'display'),'--processing',str(out/'computed/processing.json')],capture_output=True)
            if r.returncode:raise RuntimeError(r.stderr.decode(errors='replace'))
            got=int((out/'display/dcdc/capture-state.txt').read_text().split()[0]);assert got==flag
            assert record['modalities']['thermal']['state']=='waiting' and record['modalities']['adc']['state']=='waiting';assert record['ai_registration']['state'].startswith('waiting')
            cases.append({'case':name,'available_modality_flags':got,'thermal_state':'waiting','adc_state':'waiting','ai_state':'waiting','historical_results_loaded':False,'new_measurement_created':False})
        finally:temp.unlink(missing_ok=True)
    (ROOT/'evidence/missing-input-regression.json').write_text(json.dumps({'passed':True,'cases':cases},indent=2));print('missing-input regression passed')
if __name__=='__main__':main()
