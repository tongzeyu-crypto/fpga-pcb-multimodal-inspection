"""Independent OOC implementation at the existing 100MHz target."""
from pathlib import Path
import argparse,json,os,shutil,subprocess,re
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser();p.add_argument('--vivado-bin',type=Path,required=True);p.add_argument('--work',type=Path,required=True);a=p.parse_args();a.work.mkdir(parents=True,exist_ok=True)
    os.environ['TEMP']=os.environ['TMP']=str(a.work)
    for n in ['pcb_ai_core.sv','pcb_ai_axi.sv']:shutil.copyfile(ROOT/'rtl'/n,a.work/n)
    tcl='''set_param general.maxThreads 2
set_param synth.maxThreads 1
read_verilog -sv pcb_ai_core.sv
read_verilog -sv pcb_ai_axi.sv
synth_design -top pcb_ai_axi -part xc7z020clg400-1 -mode out_of_context -fsm_extraction off
create_clock -name core_clk -period 10 [get_ports clk]
set_input_delay -clock core_clk 2 [get_ports {rstn s_axi_awaddr[*] s_axi_awvalid s_axi_wdata[*] s_axi_wstrb[*] s_axi_wvalid s_axi_bready s_axi_araddr[*] s_axi_arvalid s_axi_rready}]
set_output_delay -clock core_clk 2 [get_ports {s_axi_awready s_axi_wready s_axi_bresp[*] s_axi_bvalid s_axi_arready s_axi_rdata[*] s_axi_rresp[*] s_axi_rvalid irq}]
report_utilization -file utilization-synth.rpt
write_checkpoint -force ai-synth.dcp
opt_design
place_design
route_design
report_utilization -file utilization-routed.rpt
report_timing_summary -delay_type min_max -report_unconstrained -file timing-routed.rpt
report_drc -file drc.rpt
write_checkpoint -force ai-routed.dcp
set setup [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set hold [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
set f [open slacks.txt w];puts $f "$setup $hold";close $f
if {$setup < 0 || $hold < 0} {error "AI_OOC_TIMING_FAILED"}
puts {AI_OOC_PASS}
exit
'''
    (a.work/'build.tcl').write_text(tcl)
    with (a.work/'console.log').open('wb') as f:r=subprocess.run([str(a.vivado_bin/'vivado.bat'),'-mode','batch','-source','build.tcl','-nojournal','-log','vivado.log'],cwd=a.work,stdout=f,stderr=subprocess.STDOUT)
    dest=ROOT/'evidence/ai-ooc';dest.mkdir(exist_ok=True)
    for p in a.work.iterdir():
        if p.is_file() and p.suffix in {'.rpt','.log','.txt','.tcl'}:shutil.copyfile(p,dest/p.name)
    result={'exit_code':r.returncode,'independent_ooc_only':True,'clock_mhz':100,'board_tested':False,'passed':r.returncode==0 and 'AI_OOC_PASS' in (a.work/'console.log').read_text(errors='replace')}
    if (a.work/'slacks.txt').exists():result['setup_ns'],result['hold_ns']=map(float,(a.work/'slacks.txt').read_text().split())
    if (a.work/'utilization-routed.rpt').exists():
        text=(a.work/'utilization-routed.rpt').read_text();result['resources']={}
        for k,n in [('lut','Slice LUTs'),('ff','Slice Registers'),('bram36','Block RAM Tile'),('dsp','DSPs')]:
            m=re.search(r'\|\s*'+n+r'\*?\s*\|\s*([\d.]+)',text)
            if m:result['resources'][k]=float(m.group(1))
    (dest/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));return r.returncode
if __name__=='__main__':raise SystemExit(main())
