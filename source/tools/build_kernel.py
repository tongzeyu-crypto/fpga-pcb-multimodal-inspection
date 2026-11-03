"""Build modules in a separately configured Linux build machine, never the board."""
from pathlib import Path
import argparse,io,tarfile,subprocess,json,hashlib,shlex
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser();p.add_argument('--ssh',type=Path,required=True);p.add_argument('--ssh-config',type=Path,required=True);p.add_argument('--build-host',required=True);p.add_argument('--toolbase',required=True);p.add_argument('--remote-work',required=True);a=p.parse_args()
    remote=a.remote_work;base=a.toolbase;quote=shlex.quote
    if not remote.startswith('/home/') or 'submission' not in remote:raise ValueError('dedicated Linux build directory required')
    buf=io.BytesIO()
    with tarfile.open(fileobj=buf,mode='w') as tf:
        for folder in ['drivers','graphics/driver','graphics/include']:
            for path in (ROOT/folder).glob('*'):
                if path.is_file() and (path.suffix in {'.h','.c','.dts','.dtsi'} or path.name=='Makefile'):tf.add(path,arcname=path.relative_to(ROOT).as_posix())
        # Source allowlist importer deliberately omits unknown no-suffix files.
        content=b'obj-m += pcb_gfx3.o\n';info=tarfile.TarInfo('graphics/driver/Makefile');info.size=len(content);tf.addfile(info,io.BytesIO(content))
        public_dtsi=ROOT/'resources/kernel-dts/zynq-7000.dtsi'
        if public_dtsi.exists():
            if hashlib.sha256(public_dtsi.read_bytes()).hexdigest()!='d8613c281acc7c2bb7248e93dd9cbccbe75df7f684fa33211de1338c1f30d593':raise ValueError('Public Xilinx v2020.2 DTSI dependency changed')
            tf.add(public_dtsi,arcname='resources/kernel-dts/zynq-7000.dtsi')
    ssh=[str(a.ssh),'-F',str(a.ssh_config),'-o','BatchMode=yes',a.build_host];out=ROOT/'evidence/kernel';out.mkdir(exist_ok=True)
    r=subprocess.run(ssh+['mkdir -p '+quote(remote)+' && tar -xf - -C '+quote(remote)],input=buf.getvalue(),capture_output=True,timeout=60)
    (out/'transfer.log').write_bytes(r.stdout+r.stderr);results={'transfer_exit':r.returncode,'board_contacted':False,'modules':{},'payload_sha256':hashlib.sha256(buf.getvalue()).hexdigest(),'source_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for folder in ['drivers','graphics/driver','graphics/include'] for p in (ROOT/folder).glob('*') if p.is_file() and (p.suffix in {'.h','.c','.dts','.dtsi'} or p.name=='Makefile')}}
    if public_dtsi.exists():results['source_sha256']['resources/kernel-dts/zynq-7000.dtsi']=hashlib.sha256(public_dtsi.read_bytes()).hexdigest()
    if r.returncode==0:
        cc=base+'/sdk/sysroots/x86_64-petalinux-linux/usr/bin/arm-xilinx-linux-gnueabi/arm-xilinx-linux-gnueabi-';host=base+'/toolroot/usr/bin/x86_64-linux-gnu-gcc-15'
        env=subprocess.run(ssh+['cd '+quote(base+'/zynq-linux-xlnx')+' && cat include/config/kernel.release && sha256sum .config Module.symvers include/generated/autoconf.h && '+quote(cc+'gcc')+' --version'],capture_output=True,timeout=30)
        (out/'build-environment.txt').write_bytes(env.stdout+env.stderr)
        for folder,module in [('drivers','pcb_compute'),('graphics/driver','pcb_gfx3')]:
            cmd='export PATH='+quote(base+'/bin')+':'+quote(base+'/toolroot/usr/bin')+':$PATH; make -C '+quote(base+'/zynq-linux-xlnx')+' M='+quote(remote+'/'+folder)+' ARCH=arm CROSS_COMPILE='+quote(cc)+' CC='+quote(cc+'gcc -B'+cc)+' HOSTCC='+quote(host+' -B'+base+'/toolroot/usr/libexec/gcc/x86_64-linux-gnu/15/')+' modules'
            r=subprocess.run(ssh+[cmd],capture_output=True,timeout=240);(out/(module+'.log')).write_bytes(r.stdout+r.stderr);result={'exit_code':r.returncode,'board_loaded':False};results['modules'][module]=result
            if not r.returncode:
                r2=subprocess.run(ssh+['cat '+quote(remote+'/'+folder+'/'+module+'.ko')],capture_output=True,timeout=30)
                if not r2.returncode:
                    (ROOT/'bin'/ (module+'.ko')).write_bytes(r2.stdout);result['sha256']=hashlib.sha256(r2.stdout).hexdigest()
                    result['elf32_little_endian_arm']=r2.stdout[:6]==b'\x7fELF\x01\x01' and int.from_bytes(r2.stdout[18:20],'little')==40
                    inspect=subprocess.run(ssh+['file '+quote(remote+'/'+folder+'/'+module+'.ko')+'; modinfo '+quote(remote+'/'+folder+'/'+module+'.ko')],capture_output=True,timeout=30)
                    (out/(module+'-metadata.txt')).write_bytes(inspect.stdout+inspect.stderr)
                    result['metadata_exit_code']=inspect.returncode
                    result['vermagic']=next((line.split(':',1)[1].strip() for line in inspect.stdout.decode(errors='replace').splitlines() if line.startswith('vermagic:')),None)
        if (ROOT/'drivers/demo-7020.dts').exists():
            kernel=base+'/zynq-linux-xlnx';source=remote+'/drivers/demo-7020.dts';preprocessed=remote+'/drivers/demo-7020.pp.dts';dtb=remote+'/drivers/demo-7020.dtb'
            dependency=remote+'/resources/kernel-dts';url='https://raw.githubusercontent.com/Xilinx/linux-xlnx/xilinx-v2020.2/arch/arm/boot/dts/zynq-7000.dtsi'
            cmd=quote(cc+'gcc')+' -B'+quote(cc)+' -E -x assembler-with-cpp -nostdinc -undef -D__DTS__ -I'+quote(dependency)+' -I'+quote(kernel+'/arch/arm/boot/dts')+' -I'+quote(kernel+'/include')+' '+quote(source)+' -o '+quote(preprocessed)+' && '+quote(kernel+'/scripts/dtc/dtc')+' -I dts -O dtb -o '+quote(dtb)+' '+quote(preprocessed)
            r=subprocess.run(ssh+[cmd],capture_output=True,timeout=60);(out/'device-tree.log').write_bytes(r.stdout+r.stderr)
            results['device_tree']={'exit_code':r.returncode,'board_installed':False}
            if r.returncode==0:
                r=subprocess.run(ssh+['cat '+quote(dtb)],capture_output=True,timeout=30)
                if r.returncode==0:
                    (ROOT/'bin/demo-7020.dtb').write_bytes(r.stdout)
                    results['device_tree'].update(sha256=hashlib.sha256(r.stdout).hexdigest(),valid_fdt_magic=r.stdout[:4]==b'\xd0\x0d\xfe\xed')
                    public=subprocess.run(ssh+['cat '+quote(dependency+'/zynq-7000.dtsi')],capture_output=True,timeout=30)
                    if public.returncode==0:
                        dest=ROOT/'resources/kernel-dts';dest.mkdir(exist_ok=True)
                        (dest/'zynq-7000.dtsi').write_bytes(public.stdout)
                        results['device_tree']['public_dependency']={'url':url,'sha256':hashlib.sha256(public.stdout).hexdigest(),'license':'GPL-2.0+'}
    results['modules_passed']=len(results['modules'])==2 and all(m.get('exit_code')==0 and m.get('elf32_little_endian_arm') and m.get('vermagic') and m.get('metadata_exit_code')==0 for m in results['modules'].values())
    results['passed']=results['modules_passed']
    if 'device_tree' in results:results['passed']=results['passed'] and results['device_tree'].get('valid_fdt_magic',False)
    (out/'result.json').write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2))
    return 0 if results['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
