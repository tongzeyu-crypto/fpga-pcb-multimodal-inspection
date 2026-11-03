"""Independent small demonstration IP only; never updates the combined design."""
from pathlib import Path
import argparse,hashlib,json,os,re,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser();p.add_argument('--vivado-bin',type=Path,required=True);p.add_argument('--work',type=Path,required=True);a=p.parse_args();a.work.mkdir(parents=True,exist_ok=True)
    os.environ['TEMP']=os.environ['TMP']=str(a.work)
    for source in (ROOT/'rtl').iterdir():shutil.copyfile(source,a.work/source.name)
    tcl='''set_param general.maxThreads 2
set_param synth.maxThreads 1
read_verilog -sv pcb_demo_core.sv
read_verilog -sv pcb_demo_axi.sv
synth_design -top pcb_demo_axi -part xc7z020clg400-1 -mode out_of_context -fsm_extraction off
create_clock -name demo_clk -period 16 [get_ports clk]
set_input_delay -clock demo_clk 2 [get_ports {rstn s_axi_awaddr[*] s_axi_awvalid s_axi_wdata[*] s_axi_wstrb[*] s_axi_wvalid s_axi_bready s_axi_araddr[*] s_axi_arvalid s_axi_rready}]
set_output_delay -clock demo_clk 2 [get_ports {s_axi_awready s_axi_wready s_axi_bresp[*] s_axi_bvalid s_axi_arready s_axi_rdata[*] s_axi_rresp[*] s_axi_rvalid irq}]
opt_design
place_design
route_design
report_utilization -file utilization.rpt
report_timing_summary -delay_type min_max -report_unconstrained -file timing.rpt
report_drc -file drc.rpt
write_checkpoint -force demo-routed.dcp
set setup [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set hold [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
set f [open slacks.txt w];puts $f "$setup $hold";close $f
if {$setup<0 || $hold<0} {error "DEMO_OOC_TIMING_FAILED"}
puts {DEMO_OOC_PASS}
exit
'''
    (a.work/'build.tcl').write_text(tcl)
    with (a.work/'console.log').open('wb') as out:r=subprocess.run([str(a.vivado_bin/'vivado.bat'),'-mode','batch','-source','build.tcl','-nojournal'],cwd=a.work,stdout=out,stderr=subprocess.STDOUT)
    dest=ROOT/'evidence/ooc';dest.mkdir(exist_ok=True)
    for path in a.work.iterdir():
        if path.is_file() and path.suffix in {'.rpt','.log','.txt','.tcl'}:shutil.copyfile(path,dest/path.name)
    result={'passed':r.returncode==0 and 'DEMO_OOC_PASS' in (a.work/'console.log').read_text(errors='replace'),'exit_code':r.returncode,'core_clock_mhz':62.5,'independent_ip_only':True,'integrated_in_prior_bitstream':False,'board_connected':False,'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'rtl').iterdir()}}
    if (a.work/'slacks.txt').exists():result['setup_ns'],result['hold_ns']=map(float,(a.work/'slacks.txt').read_text().split())
    if (a.work/'utilization.rpt').exists():
        text=(a.work/'utilization.rpt').read_text();result['resources']={}
        for name,label in [('lut','Slice LUTs'),('ff','Slice Registers'),('bram36','Block RAM Tile'),('dsp','DSPs')]:
            match=re.search(r'\|\s*'+label+r'\*?\s*\|\s*([\d.]+)',text)
            if match:result['resources'][name]=float(match.group(1))
    (dest/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2));return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
