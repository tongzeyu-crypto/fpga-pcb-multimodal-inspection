"""Extract global (not first clock-group) timing and resources from real reports."""
from pathlib import Path
import argparse,hashlib,json,re
def summarize(folder):
    text=(folder/'board-timing.rpt').read_text(errors='replace');section=text[text.index('Design Timing Summary'):];timing=None
    for line in section.splitlines():
        f=line.split()
        if len(f)<12:continue
        try:row={'setup_wns_ns':float(f[0]),'setup_tns_ns':float(f[1]),'setup_failing_endpoints':int(f[2]),'hold_whs_ns':float(f[4]),'hold_ths_ns':float(f[5]),'hold_failing_endpoints':int(f[6])}
        except ValueError:continue
        timing=row;break
    if timing is None:raise ValueError('global timing row missing')
    clocks={}
    for line in text.splitlines():
        f=line.split()
        if len(f)>=8 and f[0] in {'clk_fpga_0','clk_fpga_1','fast_raw'}:
            try:clocks[f[0]]={'setup_wns_ns':float(f[1]),'setup_failing_endpoints':int(f[3]),'hold_whs_ns':float(f[5])}
            except ValueError:pass
    util=(folder/'board-utilization.rpt').read_text(errors='replace');resources={}
    for key,label in [('lut','Slice LUTs'),('ff','Slice Registers'),('slices','Slice'),('bram36','Block RAM Tile'),('dsp','DSPs')]:
        m=re.search(r'\|\s*'+label+r'\*?\s*\|\s*([\d.]+)\s*\|\s*\d+\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)',util)
        if m:resources[key]={'used':float(m[1]),'available':float(m[2]),'percent':float(m[3])}
    cdc=(folder/'board-cdc.rpt').read_text(errors='replace');cdc_counts={m[0]:{'severity':m[1],'count':int(m[2])} for m in re.findall(r'^(CDC-\d+)\s+(Info|Warning|Critical)\s+(\d+)\s+',cdc,re.M)}
    frequencies={m[0]:float(m[2]) for m in re.findall(r'^\s*(clk_fpga_0|clk_fpga_1|fast_raw)\s+\{[^}]+\}\s+([\d.]+)\s+([\d.]+)',text,re.M)}
    result={'global_timing':timing,'clocks':clocks,'resources':resources,'cdc_summary':cdc_counts,'clock_targets_mhz':{'PS_graphics_AI':frequencies.get('clk_fpga_1',frequencies.get('clk_fpga_0',100)),'HDMI_reference':frequencies.get('clk_fpga_0',100),'ADC_raw':frequencies.get('fast_raw',200)},'resolution':[1280,720],'internal_timing_passed':timing['setup_wns_ns']>=0 and timing['hold_whs_ns']>=0,'external_adc_io_signed_off':False,'adc_input_false_paths':'inherited original diagnostic constraints; not an external ADC timing signoff','board_tested':False,'report_sha256':{n:hashlib.sha256((folder/n).read_bytes()).hexdigest() for n in ['board-timing.rpt','board-utilization.rpt','board-cdc.rpt','board-bus-skew.rpt','board-drc.rpt']}}
    (folder/'summary.json').write_text(json.dumps(result,indent=2));return result
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('folder',type=Path);x=a.parse_args();print(json.dumps(summarize(x.folder),indent=2))
