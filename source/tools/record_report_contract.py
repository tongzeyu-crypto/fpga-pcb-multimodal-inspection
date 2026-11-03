"""Record the fixed report identity and source-bound validation map."""
from pathlib import Path
import argparse,hashlib,json
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser();p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    frozen=json.loads((ROOT/'resources/technical-document2-contract.json').read_text(encoding='utf8'))
    if digest(a.report)!=frozen['reference']['sha256']:raise ValueError('fixed report identity changed')
    checks=['evidence/combined/result.json','demo/evidence/rtl-verification.json','demo/evidence/report-pipeline.json','evidence/report-contract/result.json','evidence/report-consumers/result.json','evidence/report-scan-ui/result.json','evidence/report-fixes/result.json','evidence/demo-integration/result.json','evidence/neural-frame/result.json','evidence/neural-frame/ui-verification.json','evidence/candidate-clocks.json','evidence/kernel/result.json']
    if (ROOT/'evidence/demo-integration/portable.json').exists():checks.append('evidence/demo-integration/portable.json')
    for name in checks:
        if not json.loads((ROOT/name).read_text(encoding='utf8')).get('passed'):raise ValueError('validation not passed: '+name)
    groups={
      'PL_SPECTRUM':['demo/rtl/pcb_demo_core.sv','demo/rtl/pcb_scalar.sv','runtime/pl_compute.cpp','runtime/pdp_device.hpp','runtime/compute_backend.py','runtime/service.py','tools/build_display_assets.py'],
      'PL_THERMAL':['demo/rtl/pcb_demo_core.sv','runtime/pl_image.cpp','runtime/compute_backend.py','runtime/service.py','tools/build_display_assets.py'],
      'PL_IMAGE':['demo/rtl/pcb_demo_core.sv','runtime/pl_image.cpp','runtime/compute_backend.py','runtime/registration.py','runtime/aoi_rules.py','runtime/aoi_annotation.py','resources/annotations/dcdc.json','resources/annotations/stm32.json','rtl/pcb_ai_core.sv','models/registration/model.json','models/registration/int8.npz'],
      'FRAME_FUSION':['runtime/display/driver/full_ai_frame.h','runtime/display/driver/gfx3_runtime.cpp','runtime/frame_demo.py','runtime/demo_preview.html','models/frame/model.json','models/frame/model.pai','models/frame/int8.npz','tools/train_neural_frame.py'],
      'PS_SCAN':['demo/runtime/scan_demo.py','runtime/grbl_control.c','runtime/grbl_guard.h','runtime/motion.py','runtime/adc_sampler.py','runtime/demo_integration.py','runtime/demo_board.py','runtime/board_demo.py','runtime/run_board.py','runtime/display/driver/full_demo.h','runtime/display/driver/full_state.h'],
      'AUTOSTART':['resources/autostart/pcb-detection.service','resources/autostart/pcb-detection.init','resources/autostart/motion.json','runtime/run_board.py','runtime/board_demo.py']}
    groups.update({
      'ADC_BUFFER':['rtl/pcb_adc_capture.sv','rtl/compute_cdc.xdc','runtime/pcb_adc.cpp','runtime/adc_sampler.py','tests/tb_adc.sv'],
      'THERMAL_QUERY':['runtime/display/driver/full_capture_data.h','runtime/display/driver/gfx3_runtime.cpp','tools/build_display_assets.py','runtime/registration.py'],
      'SCAN_CONFIG':['runtime/display/driver/full_state.h','runtime/demo_integration.py','runtime/demo_host.py','runtime/demo_preview.html','demo/runtime/scan_demo.py'],
      'SCAN_PUBLICATION':['runtime/scan_results.py','runtime/display/driver/full_capture_data.h','runtime/display/driver/full_scene.h','runtime/display/driver/full_raw.h','runtime/bands.py'],
      'BOARD_CAPTURE':['runtime/capture_live.py','runtime/capture_bundle.py','runtime/capture_set.py','runtime/calibration.py','runtime/board_profiles.py','runtime/run_board.py','runtime/demo_board.py','resources/models/stm32-model-v3.json'],
      'AOI_COORDINATES':['runtime/aoi_annotation.py','runtime/aoi_rules.py','resources/annotations/dcdc.json','resources/annotations/stm32.json','runtime/display/driver/full_aoi.h']})
    items=[]
    for required in frozen['items']:
        sources=groups[required['id']];items.append(dict(id=required['id'],paragraphs=required['paragraphs'],required=required['required'],source_implemented=True,source_sha256={s:digest(ROOT/s) for s in sources}))
    extra=['evidence/extensions.json','evidence/arm/result.json','evidence/rtl-verification.json']
    record=dict(passed=True,verification_scope='source integration and offline validation; deployment and physical acceptance pending',report_path=str(a.report),report_sha256=digest(a.report),report_bytes=a.report.stat().st_size,report_modified=False,requirements=items,validation_sha256={n:digest(ROOT/n) for n in checks+extra},current_revision_board_tested=False,physical_motion_executed=False,persistent_boot_image_modified=False,unresolved_physical_acceptance=['ADC external IO timing and channel wiring','new hardware HDMI/sensor/motion end-to-end run','STM32 real ADC acquisition','candidate autostart installation and acceptance'])
    (ROOT/'evidence/report-traceability.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    print('FIXED_REPORT_CONTRACT_RECORDED',len(items),'groups; original report unchanged')
if __name__=='__main__':main()
