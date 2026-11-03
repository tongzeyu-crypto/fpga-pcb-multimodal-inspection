"""One-shot compatible ABI3 depth extension. Operates only on submission copy."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def edit(rel,changes):
    p=ROOT/rel;s=p.read_text(encoding='utf8')
    for old,new in changes:
        if old not in s:raise ValueError('source anchor missing '+str(rel)+': '+old[:50])
        s=s.replace(old,new)
    p.write_text(s,encoding='utf8',newline='\n')
def main():
    edit('graphics/rtl/g3_resolve.sv',[
      ('frame_base,object_base,thumbnail_base,input logic make_thumbnail','frame_base,object_base,thumbnail_base,depth_base,input logic make_thumbnail,make_depth'),
      ('enum logic [3:0]','enum logic [4:0]'),
      ('THUMB_ACK,NEXT_ROW,FINISH','THUMB_ACK,NEXT_ROW,FINISH,DEPTH_REQ,DEPTH_DATA,DEPTH_ACK'),
      ('colors[0:15],objects[0:7],thumb[0:7]','colors[0:15],objects[0:7],thumb[0:7],depths[0:7]'),
      ('frame_address,object_address,thumbnail_address;','frame_address,object_address,thumbnail_address,depth_address;'),
      ('state==ID_REQ||state==THUMB_REQ','state==ID_REQ||state==THUMB_REQ||state==DEPTH_REQ'),
      ('state==ID_REQ?object_address:thumbnail_address','state==ID_REQ?object_address:state==DEPTH_REQ?depth_address:thumbnail_address'),
      ('state==ID_DATA||state==THUMB_DATA','state==ID_DATA||state==THUMB_DATA||state==DEPTH_DATA'),
      ('state==ID_DATA?objects[beat]:thumb[beat]','state==ID_DATA?objects[beat]:state==DEPTH_DATA?depths[beat]:thumb[beat]'),
      ('thumbnail_address<=thumbnail_base','depth_address<=depth_base+(pixel_offset<<1);\n  thumbnail_address<=thumbnail_base'),
      ('objects[pair>>1][pair[0]*32+:32]<=','depths[pair>>1][pair[0]*32+:32]<={tile_pixel[1][47:32],tile_pixel[0][47:32]};\n     objects[pair>>1][pair[0]*32+:32]<='),
      ('ID_ACK:if(wr_done)state<=make_thumbnail&&row[0]?THUMB_REQ:NEXT_ROW;', 'ID_ACK:if(wr_done)state<=make_depth?DEPTH_REQ:make_thumbnail&&row[0]?THUMB_REQ:NEXT_ROW;\n    DEPTH_REQ:if(wr_ready)begin beat<=0;state<=DEPTH_DATA;end\n    DEPTH_DATA:if(wd_ready)begin beat<=beat+1;if(beat==7)state<=DEPTH_ACK;end\n    DEPTH_ACK:if(wr_done)state<=make_thumbnail&&row[0]?THUMB_REQ:NEXT_ROW;')])
    edit('graphics/rtl/g3_engine.sv',[
      ('frame_base,object_base,thumbnail_base,rgb_base','frame_base,object_base,thumbnail_base,depth_base,rgb_base'),
      ('input logic make_thumbnail,','input logic make_thumbnail,make_depth,'),
      ('.object_base(object_base),.thumbnail_base(thumbnail_base),.make_thumbnail(make_thumbnail),','.object_base(object_base),.thumbnail_base(thumbnail_base),.depth_base(depth_base),.make_depth(make_depth),.make_thumbnail(make_thumbnail),')])
    edit('graphics/rtl/g3_device.sv',[
      ('logic start,quiet,fatal','logic [31:0] depth_base;\n logic start,quiet,fatal'),
      ('144:read_register=rendered_id;','448:read_register=depth_base;144:read_register=rendered_id;'),
      ("32'h00000f00","32'h00001f00"),
      ('.frame_base(cfg[7]),.object_base(cfg[8]),.thumbnail_base(cfg[9]),','.frame_base(cfg[7]),.object_base(cfg[8]),.thumbnail_base(cfg[9]),.depth_base(depth_base),.make_depth(cfg[21][4]),'),
      ('for(i=0;i<36;i=i+1)cfg[i]<=0;','depth_base<=0;for(i=0;i<36;i=i+1)cfg[i]<=0;'),
      ('else if(awaddr>=8&&awaddr<=140)begin','else if(awaddr==448)begin if(state==IDLE&&wstrb==15)depth_base<=wdata;else s_axi_bresp<=2;end\n    else if(awaddr>=8&&awaddr<=140)begin')])
    for rel in ['graphics/include/gfx3_uapi.h','runtime/display/include/gfx3_uapi.h']:
        edit(rel,[('GFX3_BINS,GFX3_PREVIEW','GFX3_BINS,GFX3_PREVIEW,GFX3_DEPTH'),('GFX3_LAYER_JOB=8','GFX3_LAYER_JOB=8,GFX3_DEPTH_JOB=16'),('#define GFX3_FEAT_DIAGNOSTIC','#define GFX3_FEAT_DEPTH 4096U\n/* With DEPTH_JOB, job.reserved[1] is a typed uint16 depth-plane BO.\n * Size and existing ABI3 structs stay unchanged; clear capability => reject. */\n#define GFX3_FEAT_DIAGNOSTIC')])
    edit('graphics/driver/pcb_gfx3.c',[
      ('#define MAX_JOB_BOS 10','#define MAX_JOB_BOS 11'),('u->kind>GFX3_PREVIEW','u->kind>GFX3_DEPTH'),
      ('GFX3_TEXTURE,GFX3_TEXTURE,GFX3_TEXTURE,GFX3_FRAME};','GFX3_TEXTURE,GFX3_TEXTURE,GFX3_TEXTURE,GFX3_FRAME,GFX3_DEPTH};'),
      ('j->thermal.handle,j->reserved[0]};','j->thermal.handle,j->reserved[0],j->reserved[1]};'),
      ('||j->reserved[1]||j->width==0','||((j->flags&GFX3_DEPTH_JOB)?(!j->reserved[1]||!(readl(g->regs+G3_FEATURES)&GFX3_FEAT_DEPTH)):j->reserved[1])||j->width==0'),
      ('GFX3_NATIVE_DISPLAY|GFX3_LAYER_JOB)','GFX3_NATIVE_DISPLAY|GFX3_LAYER_JOB|GFX3_DEPTH_JOB)'),
      ('if(k==9&&!(j->flags&GFX3_LAYER_JOB))continue;','if(k==9&&!(j->flags&GFX3_LAYER_JOB))continue;\n  if(k==10&&!(j->flags&GFX3_DEPTH_JOB))continue;'),
      ('if(k>=1&&k<=5&&s->bo[k]->users)','if(((k>=1&&k<=5)||k==10)&&s->bo[k]->users)'),
      ('((j->flags&GFX3_LAYER_JOB)&&!g3_size(s->bo[9],1280*720*4ULL)))','((j->flags&GFX3_LAYER_JOB)&&!g3_size(s->bo[9],1280*720*4ULL))||\n  ((j->flags&GFX3_DEPTH_JOB)&&!g3_size(s->bo[10],j->width*(u64)j->height*2)))'),
      ('g3_wr(g,G3_FRAME_ID,(u32)j->sequence);','if(readl(g->regs+G3_FEATURES)&GFX3_FEAT_DEPTH)g3_wr(g,448,s->bo[10]?(u32)s->bo[10]->dma:0);\n g3_wr(g,G3_FRAME_ID,(u32)j->sequence);')])
    # Generate a structurally identical AXI slave front end for ADC's native bus.
    s=(ROOT/'rtl/pcb_ai_axi.sv').read_text().replace('module pcb_ai_axi','module pcb_adc_axi')
    s=s.replace('output wire irq\n','output wire irq,\n input wire board_clk,input wire [13:0] adc_data,input wire adc_otr,input wire [1:0] grounded_pads,output wire adc_clk,adc_oeb,adc_pwdn\n')
    s=s.replace('pcb_ai_core core','pcb_adc_capture core').replace('.host_addr(host_addr)', '.host_addr(host_addr[16:0])').replace('.irq(irq));','.irq(irq),.board_clk(board_clk),.adc_data(adc_data),.adc_otr(adc_otr),.grounded_pads(grounded_pads),.adc_clk(adc_clk),.adc_oeb(adc_oeb),.adc_pwdn(adc_pwdn));')
    (ROOT/'rtl/pcb_adc_axi.sv').write_text(s)
    # Two-stage CDCs only; frozen memory is a dual-clock BRAM interface.
    (ROOT/'rtl/compute_cdc.xdc').write_text('set_false_path -to [get_pins -hier -regexp {.*req_sync_reg\\[0\\]/D}]\nset_false_path -to [get_pins -hier -regexp {.*rst_sync_reg\\[0\\]/D}]\nset_false_path -to [get_pins -hier -regexp {.*done_sync_reg\\[0\\]/D}]\n')
if __name__=='__main__':main()
