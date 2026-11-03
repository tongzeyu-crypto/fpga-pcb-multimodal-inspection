"""Verify every delivered byte against FILE_MANIFEST.json; stdlib only."""
from pathlib import Path,PurePosixPath
import argparse,hashlib,json,zipfile
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser();p.add_argument('--zip',type=Path);p.add_argument('--root',type=Path,default=ROOT);a=p.parse_args();archive=zipfile.ZipFile(a.zip) if a.zip else None;prefix=''
    if archive:
        candidates=[n for n in archive.namelist() if n=='FILE_MANIFEST.json' or n.endswith('/FILE_MANIFEST.json')]
        minimum=min(n.count('/') for n in candidates) if candidates else -1
        candidates=[n for n in candidates if n.count('/')==minimum]
        if len(candidates)!=1:raise ValueError('archive must contain exactly one root delivery manifest')
        prefix=candidates[0][:-len('FILE_MANIFEST.json')]
    def read(name):
        rel=PurePosixPath(name)
        if rel.is_absolute() or '..'in rel.parts or ':'in name or '\\'in name:raise ValueError('invalid manifest path')
        return archive.read(prefix+name) if archive else (a.root/name).read_bytes()
    manifest=json.loads(read('FILE_MANIFEST.json'));bad=[]
    for name,expected in manifest.items():
        try:
            data=read(name)
            if len(data)!=expected['bytes'] or hashlib.sha256(data).hexdigest()!=expected['sha256']:bad.append(name)
        except (OSError,KeyError):bad.append(name)
    # Tie executable evidence to the delivered sources and returned binaries.
    kernel=json.loads(read('evidence/kernel/result.json')) if 'evidence/kernel/result.json' in manifest else {}
    if kernel.get('modules_passed',kernel.get('passed')):
        for name,expected in kernel['source_sha256'].items():
            if hashlib.sha256(read(name)).hexdigest()!=expected:bad.append('kernel source: '+name)
        for name,result in kernel['modules'].items():
            blob=read('bin/'+name+'.ko')
            arm=blob[:6]==b'\x7fELF\x01\x01' and int.from_bytes(blob[18:20],'little')==40
            if not arm or hashlib.sha256(blob).hexdigest()!=result['sha256'] or ('vermagic='+result['vermagic']).encode() not in blob:
                bad.append('kernel binary: '+name)
        dt=kernel.get('device_tree',{})
        if dt.get('valid_fdt_magic'):
            blob=read('bin/demo-7020.dtb')
            if blob[:4]!=b'\xd0\x0d\xfe\xed' or hashlib.sha256(blob).hexdigest()!=dt['sha256']:bad.append('candidate device tree binary')
    graphics=json.loads(read('evidence/graphics-timing/result.json')) if 'evidence/graphics-timing/result.json' in manifest else None
    if graphics:
        if not graphics.get('passed'):bad.append('graphics RTL regressions')
        for name,expected in graphics['source_sha256'].items():
            if hashlib.sha256(read('graphics/rtl/'+name)).hexdigest()!=expected:bad.append('graphics RTL evidence: '+name)
    combined=json.loads(read('evidence/combined/result.json'))
    if not combined.get('passed'):bad.append('combined hardware implementation')
    for name,expected in combined.get('source_hashes',{}).items():
        if hashlib.sha256(read(name)).hexdigest()!=expected:bad.append('combined source evidence: '+name)
    hardware=json.loads(read('hardware/summary.json'))
    if not hardware['internal_timing_passed']:bad.append('hardware timing summary')
    for name,expected in {**hardware['report_sha256'],**hardware['artifact_sha256']}.items():
        if hashlib.sha256(read('hardware/'+name)).hexdigest()!=expected:bad.append('hardware report: '+name)
    if 'evidence/candidate-clocks.json' in manifest:
        clocks=json.loads(read('evidence/candidate-clocks.json'))
        if hashlib.sha256(read('bin/demo-7020.dtb')).hexdigest()!=clocks['dtb_sha256'] or hashlib.sha256(read('evidence/combined/board-clocks.rpt')).hexdigest()!=clocks['clock_report_sha256']:
            bad.append('candidate hardware/device-tree clock evidence')
    if 'evidence/demo-integration/result.json' in manifest:
        demo=json.loads(read('evidence/demo-integration/result.json'))
        if not demo['passed'] or demo['board_connected'] or demo['boot_image_modified']:bad.append('demo integration verification')
        for name,expected in demo['source_sha256'].items():
            if hashlib.sha256(read(name)).hexdigest()!=expected:bad.append('demo integration source: '+name)
        host=json.loads(read('evidence/demo-integration/host-build.json'))
        if hashlib.sha256(read('bin/demo_reference.exe')).hexdigest()!=host['binary_sha256']:bad.append('demo host executable')
        for name,expected in host['source_sha256'].items():
            if hashlib.sha256(read(name)).hexdigest()!=expected:bad.append('demo host source: '+name)
        if 'evidence/demo-integration/portable.json' in manifest:
            portable=json.loads(read('evidence/demo-integration/portable.json'))
            if not portable['passed']:bad.append('extracted package demo')
            for name,expected in portable.get('source_sha256',{}).items():
                if hashlib.sha256(read(name)).hexdigest()!=expected:bad.append('portable source: '+name)
        small=json.loads(read('demo/evidence/rtl-verification.json'))
        if not small.get('passed'):bad.append('PDP2 RTL verification')
        for name,expected in small['source_sha256'].items():
            if hashlib.sha256(read('demo/rtl/'+name)).hexdigest()!=expected:bad.append('demo RTL source: '+name)
        for name,expected in small.get('input_sha256',{}).items():
            if hashlib.sha256(read('demo/inputs/'+name)).hexdigest()!=expected:bad.append('PDP2 verified input: '+name)
        arm=json.loads(read('evidence/arm/result.json'))
        for name,expected in arm['source_sha256'].items():
            if hashlib.sha256(read(name)).hexdigest()!=expected:bad.append('ARM source: '+name)
        if hashlib.sha256(read('bin/hdmi_full_runtime')).hexdigest()!=arm['hdmi_full_runtime']['sha256']:bad.append('ARM UI executable')
        for name,result in arm.items():
            if isinstance(result,dict) and result.get('elf32_little_endian_arm'):
                if result.get('exit_code') or hashlib.sha256(read('bin/'+name)).hexdigest()!=result['sha256']:bad.append('ARM executable: '+name)
        client=json.loads(read('demo/evidence/arm-build.json'))
        if not client['passed'] or hashlib.sha256(read('runtime/pl_compute.cpp')).hexdigest()!=client['source_sha256'] or hashlib.sha256(read('runtime/pdp_device.hpp')).hexdigest()!=client['header_sha256'] or hashlib.sha256(read('bin/pl_demo')).hexdigest()!=client['sha256']:bad.append('PDP3 ARM client/source identity')
    if 'evidence/report-traceability.json' in manifest:
        trace=json.loads(read('evidence/report-traceability.json'))
        if not trace.get('passed') or trace.get('report_modified'):bad.append('fixed report contract')
        for group in trace['requirements']:
            for name,expected in group['source_sha256'].items():
                if hashlib.sha256(read(name)).hexdigest()!=expected:bad.append('report implementation source: '+name)
        for name,expected in trace['validation_sha256'].items():
            if hashlib.sha256(read(name)).hexdigest()!=expected:bad.append('report validation identity: '+name)
        for name in ['demo/evidence/report-pipeline.json','evidence/report-contract/result.json','evidence/report-consumers/result.json','evidence/report-fixes/result.json']:
            result=json.loads(read(name))
            if not result.get('passed'):bad.append('report validation: '+name)
            for source,expected in result.get('source_sha256',{}).items():
                source='demo/rtl/'+source if '/'not in source else source
                if hashlib.sha256(read(source)).hexdigest()!=expected:bad.append('report validation source: '+source)
    if 'evidence/report-qa.json' in manifest:
        report=json.loads(read('evidence/report-qa.json'))
        if not report['passed'] or hashlib.sha256(read('docs/技术报告_程序一致版.docx')).hexdigest()!=report['docx_sha256']:bad.append('technical report verification')
    if 'evidence/neural-frame/result.json' in manifest:
        neural=json.loads(read('evidence/neural-frame/result.json'))
        if not neural['passed'] or not neural['trained_network_controls_rgb'] or neural['network_is_confidence_classifier']:bad.append('neural frame semantics')
        for name,expected in neural['source_sha256'].items():
            if hashlib.sha256(read(name)).hexdigest()!=expected:bad.append('neural frame source: '+name)
        ui=json.loads(read('evidence/neural-frame/ui-verification.json'))
        if not ui['passed'] or not ui['actual_neural_integer_execution'] or not ui['network_ablation_verified']:bad.append('neural UI verification')
        for name,expected in ui['source_sha256'].items():
            if hashlib.sha256(read(name)).hexdigest()!=expected:bad.append('neural UI source: '+name)
        rtl=json.loads(read('evidence/rtl-verification.json'))
        for name,expected in rtl.get('model_sha256',{}).items():
            if hashlib.sha256(read(name)).hexdigest()!=expected:bad.append('RTL model identity: '+name)
        if read('models/frame/model.pai.kind').strip()!=b'NEURAL_PIXEL_FUSION_V1':bad.append('neural model purpose guard')
    if 'evidence/board-20261103-r1/result.json' in manifest:
        board=json.loads(read('evidence/board-20261103-r1/result.json'))
        if not board['board_demo_passed'] or board['original_boot_image_modified']:
            bad.append('board demo verification')
        for name,expected in board['source_sha256'].items():
            if hashlib.sha256(read(name)).hexdigest()!=expected:bad.append('board source: '+name)
        for name,expected in board['artifact_sha256'].items():
            if hashlib.sha256(read(name)).hexdigest()!=expected:bad.append('board artifact: '+name)
    if 'VERSION.json' in manifest:
        version=json.loads(read('VERSION.json'))
        for name,expected in version.get('hardware_sha256',{}).items():
            if hashlib.sha256(read(name)).hexdigest()!=expected:bad.append('version hardware: '+name)
    if archive:
        crc=archive.testzip();archive.close()
        if crc:bad.append('ZIP CRC: '+crc)
        side=a.zip.with_suffix(a.zip.suffix+'.sha256')
        if side.exists() and hashlib.sha256(a.zip.read_bytes()).hexdigest()!=side.read_text(encoding='utf8').split()[0]:bad.append('ZIP SHA256')
    print(json.dumps({'passed':not bad,'checked_files':len(manifest),'mismatched_files':bad},indent=2));return int(bool(bad))
if __name__=='__main__':raise SystemExit(main())
