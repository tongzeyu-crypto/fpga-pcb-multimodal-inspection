"""Fresh graphics+AI+ADC design, no programming/deployment commands.

The small factory clock/PHY preset is an explicit development input. All other
sources are in the submission. No original project or boot image is modified.
"""
from pathlib import Path
import argparse,datetime,hashlib,json,os,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1]
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--vivado-bin',type=Path,required=True);ap.add_argument('--work',type=Path,required=True);ap.add_argument('--factory',type=Path);ap.add_argument('--adc-xdc',type=Path);a=ap.parse_args()
    a.work.mkdir(parents=True,exist_ok=True);os.environ['TEMP']=os.environ['TMP']=str(a.work)
    evidence=ROOT/'evidence/combined'
    if evidence.exists():
        archive=ROOT/'evidence'/('combined-before-'+a.work.name+'-'+datetime.datetime.now().strftime('%H%M%S'))
        evidence.rename(archive)
    evidence.mkdir()
    # Only the minimum board preset and DVI RTL are imported; never keys/caches.
    vendor=ROOT/'resources/factory'
    if a.factory:
        paths=['HZ_B2B_7z020/HZ_B2B_7z020.gen/sources_1/bd/system/hw_handoff/system_bd.tcl']+['FPGA_PL/hdmi_colorbar/hdmi_colorbar.srcs/sources_1/new/'+n+'.v' for n in ['asyn_rst_syn','dvi_encoder','serializer_10_to_1','dvi_transmitter_top']]
        for p in paths:
            q=vendor/p;q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(a.factory/p,q)
    if a.adc_xdc:shutil.copyfile(a.adc_xdc,ROOT/'resources/adc_bringup.xdc')
    for src,dst in [(ROOT/'graphics/rtl','rtl'),(ROOT/'graphics/integration','integration'),(vendor,'vendor_7020_1g'),(ROOT/'rtl','compute')]:shutil.copytree(src,a.work/dst,dirs_exist_ok=True)
    source_hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for folder in ['graphics','rtl'] for p in (ROOT/folder).rglob('*') if p.is_file()}
    (a.work/'adc_verified').mkdir(exist_ok=True);shutil.copyfile(ROOT/'resources/adc_bringup.xdc',a.work/'adc_verified/adc_bringup.xdc')
    sources=sorted((a.work/'rtl').glob('*.sv'),key=lambda p:(p.name!='g3_pkg.sv',p.name));sources=[p for p in sources if p.name not in ['g3_scanout.sv','g3_line_ram.sv','g3_cursor_rom.sv']]
    common='set_param general.maxThreads 2\nset_param synth.maxThreads 1\n'
    pre=common+'create_project shader -in_memory -part xc7z020clg400-1\n'+''.join('read_verilog -sv {'+p.as_posix()+'}\n' for p in sources)
    pre+='synth_design -top g3_shader -part xc7z020clg400-1 -mode out_of_context -control_set_opt_threshold 16\nreset_timing\nwrite_checkpoint -force shader-synth.dcp\nexit\n'
    def run(name,tcl):
        (a.work/(name+'.tcl')).write_text(tcl,encoding='utf8',newline='\n')
        with (a.work/(name+'.log')).open('wb') as f:r=subprocess.run([str(a.vivado_bin/'vivado.bat'),'-mode','batch','-nojournal','-source',name+'.tcl','-log',name+'-vivado.log'],cwd=a.work,stdout=f,stderr=subprocess.STDOUT)
        return r.returncode
    def collect(stage,code):
        dest=ROOT/'evidence/combined';dest.mkdir(exist_ok=True)
        for p in a.work.iterdir():
            if p.is_file() and p.suffix in {'.tcl','.rpt','.log','.txt','.xdc'}:shutil.copyfile(p,dest/p.name)
        result={'last_stage':stage,'exit_code':code,'passed':code==0 and stage=='implementation' and 'BOARD_G3_BUILT_NOT_PROGRAMMED' in (a.work/'implementation.log').read_text(errors='replace'),'board_connected':False,'programmed':False,'resolution':[1280,720],'profile':'demonstration','clock_target_mhz':62.5,'hdmi_reference_mhz':100,'adc_raw_mhz':200,'source_hashes':source_hashes}
        (dest/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='source_hashes'}),flush=True)
        staged={p.relative_to(a.work).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for folder in ['rtl','compute','integration','vendor_7020_1g','adc_verified'] for p in (a.work/folder).rglob('*') if p.is_file()}
        (dest/'staged-hardware-source-sha256.json').write_text(json.dumps(staged,indent=2))
    code=run('shader',pre)
    if code:collect('shader',code);return code
    p=a.work/'rtl/g3_shader.sv';s=p.read_text();p.write_text('(* black_box="true" *) '+s[s.index('module g3_shader'):s.index(' import g3_pkg::*;')]+'\nendmodule\n')
    package=common+'create_project graphics gp -part xc7z020clg400-1 -force\n'+''.join('read_verilog -sv {'+p.as_posix()+'}\n' for p in sources)
    package+='set_property file_type Verilog [get_files *g3_axi_device.sv]\nsource integration/package_ip.tcl\nclose_project\ncreate_project scan sp -part xc7z020clg400-1 -force\n'
    for n in ['g3_cursor_rom','g3_line_ram','g3_scanout']:package+='read_verilog -sv rtl/'+n+'.sv\n'
    package+='read_verilog integration/g3_scanout_axi.sv\nset_property file_type Verilog [get_files *g3_scanout_axi.sv]\nsource integration/package_scanout.tcl\nclose_project\n'
    for kind,top,names,range_,version in [('dvi','dvi_transmitter_top',['asyn_rst_syn','dvi_encoder','serializer_10_to_1','dvi_transmitter_top'],0,'3.0'),('adc','pcb_adc_axi',['pcb_adc_capture','pcb_adc_axi'],131072,'3.0'),('ai','pcb_ai_axi',['pcb_ai_core','pcb_ai_axi'],262144,'1.0')]:
        package+=f'create_project {kind}_pkg {kind}_project -part xc7z020clg400-1 -force\n'
        for n in names:package+=('read_verilog vendor_7020_1g/FPGA_PL/hdmi_colorbar/hdmi_colorbar.srcs/sources_1/new/'+n+'.v\n') if kind=='dvi' else 'read_verilog -sv compute/'+n+'.sv\n'
        package+=f'set_property top {top} [current_fileset]\nupdate_compile_order -fileset sources_1\nipx::package_project -root_dir packaged_{kind} -vendor pcb.local -library graphics -taxonomy /UserIP -import_files -set_current true\nset core [ipx::current_core]\nset_property name '+('ai1' if kind=='ai' else kind+'3')+' $core\nset_property version '+version+' $core\n'
        package+='ipx::infer_bus_interfaces xilinx.com:interface:aximm_rtl:1.0 $core\nipx::infer_bus_interfaces xilinx.com:signal:clock_rtl:1.0 $core\nipx::infer_bus_interfaces xilinx.com:signal:reset_rtl:1.0 $core\n'
        if range_:
            package+='ipx::associate_bus_interfaces -busif s_axi -clock clk $core\nset map [ipx::get_memory_maps s_axi -of_objects $core]\nif {![llength $map]} {set map [ipx::add_memory_map s_axi $core]}\nset block [ipx::get_address_blocks Reg -of_objects $map]\nif {![llength $block]} {set block [ipx::add_address_block Reg $map]}\nset_property -dict {range '+str(range_)+' width 32 usage register} $block\nset_property slave_memory_map_ref s_axi [ipx::get_bus_interfaces s_axi -of_objects $core]\n'
        package+='ipx::create_xgui_files $core\nipx::update_checksums $core\nipx::check_integrity -quiet $core\nipx::save_core $core\nclose_project\n'
    code=run('package',package+'exit\n')
    if code:collect('package',code);return code
    board=(a.work/'integration/board_hdmi.tcl').read_text()
    board=board.replace('set scan [create_bd_cell','set ai [create_bd_cell -type ip -vlnv pcb.local:graphics:ai1:1.0 pcb_ai]\nset scan [create_bd_cell',1)
    board=board.replace('CONFIG.NUM_MI {2}','CONFIG.NUM_MI {4}').replace('M00_ACLK M01_ACLK','M00_ACLK M01_ACLK M02_ACLK M03_ACLK').replace('M00_ARESETN M01_ARESETN','M00_ARESETN M01_ARESETN M02_ARESETN M03_ARESETN')
    board=board.replace('assign_bd_address\n','connect_bd_intf_net [get_bd_intf_pins $ctrl/M02_AXI] [get_bd_intf_pins $ai/s_axi]\nconnect_bd_intf_net [get_bd_intf_pins $ctrl/M03_AXI] [get_bd_intf_pins $adc/s_axi]\nforeach dev [list $ai $adc] {connect_bd_net [get_bd_pins $ps/FCLK_CLK1] [get_bd_pins $dev/clk];connect_bd_net [get_bd_pins $rst/peripheral_aresetn] [get_bd_pins $dev/rstn]}\n# Automatic placement follows explicit peripheral addresses.\n',1)
    board=board.replace('validate_bd_design\n','assign_bd_address -offset 0x43C40000 -range 0x40000 -target_address_space [get_bd_addr_spaces $ps/Data] [get_bd_addr_segs $ai/s_axi/Reg]\nassign_bd_address -offset 0x43C80000 -range 0x20000 -target_address_space [get_bd_addr_spaces $ps/Data] [get_bd_addr_segs $adc/s_axi/Reg]\nassign_bd_address\nvalidate_bd_design\n',1)
    board=board.replace('update_compile_order -fileset sources_1\nsynth_design','read_xdc compute/compute_cdc.xdc\nupdate_compile_order -fileset sources_1\nsynth_design')
    # Do not write an image on failed timing. No programming commands exist.
    (a.work/'integration/board_hdmi.tcl').write_text(board)
    tcl=common+'package require msgcat\ncreate_project integration project -part xc7z020clg400-1 -force\nset_property ip_repo_paths [list [file normalize packaged_ip] [file normalize packaged_scanout] [file normalize packaged_dvi] [file normalize packaged_adc] [file normalize packaged_ai]] [current_project]\nupdate_ip_catalog\nsource integration/board_hdmi.tcl\nexit\n'
    code=run('implementation',tcl);collect('implementation',code);return code
if __name__=='__main__':raise SystemExit(main())
