"""Check actual Vivado clock periods against the compiled candidate DTB."""
from pathlib import Path
import argparse,hashlib,json,re,struct,zipfile
ROOT=Path(__file__).resolve().parents[1]

def read_fdt(blob):
    header=struct.unpack_from('>10I',blob)
    if header[0]!=0xd00dfeed or header[1]!=len(blob):raise ValueError('Invalid FDT header')
    pos=header[2];strings=blob[header[3]:header[3]+header[8]];stack=[];nodes={}
    while True:
        token=struct.unpack_from('>I',blob,pos)[0];pos+=4
        if token==1:
            end=blob.index(0,pos);stack.append(blob[pos:end].decode());pos=(end+4)&~3;nodes['/'.join(stack)]={}
        elif token==2:stack.pop()
        elif token==3:
            length,nameoff=struct.unpack_from('>II',blob,pos);pos+=8
            end=strings.index(0,nameoff);name=strings[nameoff:end].decode()
            nodes['/'.join(stack)][name]=blob[pos:pos+length];pos=(pos+length+3)&~3
        elif token==4:continue
        elif token==9:break
        else:raise ValueError('Unknown FDT token')
    return nodes

def main():
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);a=p.parse_args()
    clock_report=a.work/'board-clocks.rpt';text=clock_report.read_text(errors='replace')
    periods={m[0]:float(m[1]) for m in re.findall(r'^\s*(clk_fpga_0|clk_fpga_1|fast_raw|clk_out1_board_hdmi_clock_0|clk_out2_board_hdmi_clock_0)\s+([\d.]+)\s+\{',text,re.M)}
    expected={'clk_fpga_0':10,'clk_fpga_1':16,'fast_raw':5,'clk_out1_board_hdmi_clock_0':1000/74.25,'clk_out2_board_hdmi_clock_0':1000/371.25}
    if any(abs(periods.get(n,0)-v)>.001 for n,v in expected.items()):raise ValueError('Actual hardware clock mismatch')
    blob=(ROOT/'bin/demo-7020.dtb').read_bytes();nodes=read_fdt(blob)
    controllers={struct.unpack('>I',p['phandle'])[0]:p for p in nodes.values() if 'phandle' in p and 'clock-output-names' in p}
    bindings={}
    for name in ['graphics@43c00000','gpio@41200000','pcb_ai@43c40000','pcb_adc@43c80000']:
        matches=[p for path,p in nodes.items() if path.endswith('/'+name)]
        if len(matches)!=1:raise ValueError('Missing/duplicate candidate device '+name)
        handle,index=struct.unpack('>II',matches[0]['clocks']);controller=controllers[handle]
        clock_names=controller['clock-output-names'].rstrip(b'\0').split(b'\0')
        if index!=16 or clock_names[index]!=b'fclk1' or struct.unpack('>I',controller['fclk-enable'])[0]!=3:raise ValueError('Device does not hold the configured FCLK1')
        bindings[name]={'clock_index':index,'clock_name':'fclk1'}
    hdf=a.work/'board.hdf'
    with zipfile.ZipFile(hdf) as archive:init=archive.read('ps7_init.c').decode()
    writes=re.findall(r'EMIT_MASKWRITE\(\s*0x(f8000170|f8000180)\s*,[^,]+,\s*(0x[0-9a-f]+)u?\s*\)',init,re.I)
    registers={}
    for address,value in writes:
        word=int(value,16);d0=(word>>8)&63;d1=(word>>20)&63;source=(word>>4)&3
        target=10 if address.lower()=='f8000170' else 16
        if source!=0 or d0*d1!=target:raise ValueError('Exported PS initialization has the wrong FCLK divider')
        registers[address.lower()]={'source':'IO PLL','divisor0':d0,'divisor1':d1,'product':d0*d1}
    if len(registers)!=2:raise ValueError('Exported PS initialization omits FCLK controls')
    result={'passed':True,'periods_ns':periods,'device_bindings':bindings,'fclk_enable_mask':3,'exported_ps_clock_registers':registers,'board_tested':False,'dtb_sha256':hashlib.sha256(blob).hexdigest(),'hdf_sha256':hashlib.sha256(hdf.read_bytes()).hexdigest(),'clock_report_sha256':hashlib.sha256(clock_report.read_bytes()).hexdigest()}
    (ROOT/'evidence/candidate-clocks.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
if __name__=='__main__':main()
