// Stable two-pass binning. No color/depth framebuffer is touched on overflow.
module g3_binner #(parameter integer FAST_REFS=32768, CULL_EMPTY_TILES=1)(input logic clk,rstn,start,cull_enable,
 input logic [31:0] command_base,command_count,geometry_base,bin_base,refs_capacity,
 input logic [11:0] width,height,input logic signed [31:0] matrix[0:11],
 output logic busy,done,output logic [3:0] error,
 output logic [31:0] geometry_count,reference_count,
 output g3_pkg::rd_req_t rd,input logic rd_ready,
 input g3_pkg::rd_rsp_t response,output logic response_ready,
 output g3_pkg::wr_req_t wr,input logic wr_ready,
 output g3_pkg::wr_data_t wd,input logic wd_ready,input logic wr_done,wr_error,
 output logic [63:0] setup_cycles,bin_cycles,output logic [31:0] rejected_references);
 import g3_pkg::*;
 assign rd.token=0;
 typedef enum logic [5:0]{IDLE,CLEAR,FETCH,FETCH_DATA,DECODE,SETUP_START,SETUP_WAIT,
  STORE_REQ,STORE_DATA,STORE_ACK,COUNT,ADVANCE,PREFIX,HEADER_REQ,HEADER_DATA,
  HEADER_ACK,READ_DESC,READ_DESC_DATA,RECT,SCATTER_REQ,SCATTER_DATA,
  SCATTER_ACK,NEXT_DESC,FINISH,FAILED,COUNT_ADDRESS,SCATTER_TILE,SCATTER_ADDRESS,
  COUNT_READ,PREFIX_READ,HEADER_READ,SCATTER_READ,
  REFS_REQ,REFS_READ,REFS_WAIT,REFS_DATA,REFS_ACK,CULL_DIFF,CULL_PRODUCTS,CULL_INIT} state_t;
 state_t state;
 // The count is retained until all headers reach DDR. Its upper field then
 // serves as the scatter cursor. One synchronous SDP store replaces three
 // asynchronous distributed tables; no reference order changes.
 logic bin_read,bin_write;logic [9:0] bin_raddr,bin_waddr;logic [63:0] bin_rdata,bin_wdata;
 logic [1023:0] descriptor,setup_descriptor;
 logic [511:0] cmd;logic [31:0] command_no,geom_no,index,sum;
 logic [9:0] item,tiles;logic [5:0] nx,tx,tx0,tx1,ty,ty1;
 logic [4:0] beat;logic half,setup_ready,setup_done,setup_error;
 logic [127:0] header;logic [31:0] scatter_addr;logic [9:0] tile;
 logic fast_refs;logic [14:0] scatter_index,flush_pair;
 logic [31:0] flush_offset,flush_remaining;logic [4:0] flush_beats;
 logic [7:0] flush_strb;
 logic [15:0] packed_ref[0:1];
 logic descriptor_bounds_valid;
 logic cull_scatter,cull_outside,advance_count,advance_scatter;
 logic signed [16:0] cull_dx[0:2],cull_dy[0:2],cull_ax[0:2],cull_ay[0:2];
 logic signed [33:0] cull_p[0:2],cull_q[0:2];
 logic signed [34:0] cull_edge[0:2],cull_row[0:2],cull_step_x[0:2],cull_step_y[0:2];
 logic cull_inclusive[0:2];
 function automatic signed [15:0] cx(input integer n);cx=descriptor[(4+n*2)*32+:16];endfunction
 function automatic signed [15:0] cy(input integer n);cy=descriptor[(5+n*2)*32+:16];endfunction
 function automatic signed [16:0] corner(input logic [5:0] t,input logic high);
  corner=$signed({2'b0,t,9'b0})+(high?17'sd504:17'sd8);
 endfunction
 always_comb begin
  cull_outside=0;
  for(integer ce=0;ce<3;ce=ce+1)
   if(cull_edge[ce]<0||(cull_edge[ce]==0&&!cull_inclusive[ce]))cull_outside=CULL_EMPTY_TILES!=0&&cull_enable;
 end
 assign advance_count=(state==COUNT&&reference_count<refs_capacity)||
  (state==COUNT_ADDRESS&&cull_outside);
 assign advance_scatter=(state==SCATTER_ACK&&(fast_refs||wr_done)&&!wr_error)||
  (state==SCATTER_TILE&&cull_outside);
 assign descriptor_bounds_valid=$signed(descriptor[19*32+:32])>=0&&
  $signed(descriptor[21*32+:32])>=0&&descriptor[20*32+:32]<{20'b0,width}&&
  descriptor[22*32+:32]<{20'b0,height}&&descriptor[19*32+:32]<=descriptor[20*32+:32]&&
  descriptor[21*32+:32]<=descriptor[22*32+:32];
 generate for(genvar bank=0;bank<2;bank=bank+1)begin: local_refs
  g3_ram_sdp #(.WIDTH(16),.AW(14)) ram(.clk(clk),
   .we(state==SCATTER_DATA&&fast_refs&&scatter_index[0]==bank),
   .wa(scatter_index[14:1]),.wd(index[15:0]),
   .re(state==REFS_READ),.ra(flush_pair[13:0]),.q(packed_ref[bank]));
 end endgenerate
 g3_ram_sdp #(.WIDTH(64),.AW(10)) table_ram(.clk(clk),.we(bin_write),.wa(bin_waddr),.wd(bin_wdata),
  .re(bin_read),.ra(bin_raddr),.q(bin_rdata));
 g3_setup setup(.clk(clk),.rstn(rstn),.start(state==SETUP_START),.command(cmd),
  .sprite_half(half),.matrix(matrix),.width(width),.height(height),
  .ready(setup_ready),.done(setup_done),.error(setup_error),.descriptor(setup_descriptor));
 assign busy=state!=IDLE;
 always_comb begin
  bin_read=state==COUNT_READ||state==PREFIX_READ||state==HEADER_READ||state==SCATTER_READ;
  bin_raddr=(state==COUNT_READ||state==SCATTER_READ)?tile:item;
  bin_write=0;bin_waddr=item;bin_wdata=0;
  if(state==CLEAR)bin_write=1;
  else if(state==COUNT&&reference_count<refs_capacity)begin
   bin_write=1;bin_waddr=tile;bin_wdata={48'b0,bin_rdata[15:0]+16'd1};
  end else if(state==PREFIX)begin bin_write=1;bin_wdata={25'b0,sum[22:0],bin_rdata[15:0]};end
  else if(state==SCATTER_ACK&&(fast_refs||wr_done)&&!wr_error)begin
   bin_write=1;bin_waddr=tile;bin_wdata={25'b0,bin_rdata[38:16]+23'd1,16'b0};
  end
  header={32'b0,9'b0,bin_rdata[38:16],16'b0,bin_rdata[15:0],9'b0,bin_rdata[38:16]};
  rd.valid=state==FETCH||state==READ_DESC;
  rd.addr=state==FETCH?command_base+(command_no<<6):geometry_base+(index<<7);
  rd.beats=state==FETCH?8:16;response_ready=state==FETCH_DATA||state==READ_DESC_DATA;
  flush_remaining=reference_count-flush_offset-({27'b0,flush_beats}<<1);
  wr.valid=state==STORE_REQ||state==HEADER_REQ||state==SCATTER_REQ||state==REFS_REQ;
  wr.addr=state==STORE_REQ?geometry_base+(geom_no<<7):state==HEADER_REQ?bin_base+(item<<4):
   state==REFS_REQ?bin_base+16384+(flush_offset<<2):{scatter_addr[31:3],3'b0};
  wr.beats=state==STORE_REQ?16:state==HEADER_REQ?2:state==REFS_REQ?flush_beats:1;
  wd.valid=state==STORE_DATA||state==HEADER_DATA||(state==SCATTER_DATA&&!fast_refs)||state==REFS_DATA;
  wd.data=state==STORE_DATA?descriptor[beat*64+:64]:state==HEADER_DATA?header[beat*64+:64]:
   state==REFS_DATA?{16'b0,packed_ref[1],16'b0,packed_ref[0]}:{index,index};
  wd.strb=state==SCATTER_DATA?(scatter_addr[2]?8'hf0:8'h0f):state==REFS_DATA?flush_strb:8'hff;
 end
 // Payload registers are not validity state. Keeping their writes separate
 // from the global error mux avoids routing AXI RID/error through 1536 data
 // register enables. A faulty response can change discarded payload bits;
 // the controller still enters FAILED before any descriptor is published.
 always_ff @(posedge clk)begin
  if(state==FETCH_DATA&&response.valid)cmd[beat*64+:64]<=response.data;
  if(state==SETUP_WAIT&&setup_done)descriptor<=setup_descriptor;
  else if(state==READ_DESC_DATA&&response.valid)descriptor[beat*64+:64]<=response.data;
 end
 always_ff @(posedge clk)begin
  if(!rstn)begin state<=IDLE;done<=0;error<=0;geometry_count<=0;reference_count<=0;setup_cycles<=0;bin_cycles<=0;rejected_references<=0;end
  else begin
   done<=0;
   if(state==SETUP_START||state==SETUP_WAIT)setup_cycles<=setup_cycles+1;
   else if(busy)bin_cycles<=bin_cycles+1;
   if((response.valid&&response_ready&&response.error)||wr_error)begin error<=2;state<=FAILED;end
   else case(state)
    IDLE:if(start)begin
     error<=0;item<=0;command_no<=0;geom_no<=0;geometry_count<=0;reference_count<=0;
     rejected_references<=0;
     half<=0;sum<=0;nx<=(width+31)>>5;tiles<=((width+31)>>5)*((height+31)>>5);
     setup_cycles<=0;bin_cycles<=0;
     if(!command_count||command_count>16385||!width||width>1280||!height||height>720||!refs_capacity||refs_capacity>4194304)begin error<=1;state<=FAILED;end
     else state<=CLEAR;
    end
    CLEAR:begin
     if(item==1023)state<=FETCH;else item<=item+1;end
    FETCH:if(rd_ready)begin beat<=0;state<=FETCH_DATA;end
    FETCH_DATA:if(response.valid)begin
     beat<=beat+1;
     if(response.last!=(beat==7))begin error<=2;state<=FAILED;end
     else if(response.last)state<=DECODE;
    end
    DECODE:begin
     if(cmd[7:0]==0)begin item<=0;sum<=0;state<=PREFIX_READ;end
     else if(cmd[7:0]>3||geom_no>=16384)begin error<=1;state<=FAILED;end
     else state<=SETUP_START;
    end
    SETUP_START:if(setup_ready)state<=SETUP_WAIT;
    SETUP_WAIT:if(setup_done)begin
     if(setup_error)begin error<=4;state<=FAILED;end else state<=STORE_REQ;
    end
    STORE_REQ:if(wr_ready)begin beat<=0;state<=STORE_DATA;end
    STORE_DATA:if(wd_ready)begin beat<=beat+1;if(beat==15)state<=STORE_ACK;end
    STORE_ACK:if(wr_done)begin
     geometry_count<=geom_no+1;
     tx<=descriptor[19*32+:32]>>5;tx0<=descriptor[19*32+:32]>>5;tx1<=descriptor[20*32+:32]>>5;
     ty<=descriptor[21*32+:32]>>5;ty1<=descriptor[22*32+:32]>>5;
     if(descriptor[96]&&!descriptor_bounds_valid)begin error<=1;state<=FAILED;end
     else if(!descriptor[96])state<=ADVANCE;
     else if(CULL_EMPTY_TILES&&cull_enable)begin cull_scatter<=0;state<=CULL_DIFF;end
     else state<=COUNT_ADDRESS;
    end
    COUNT_ADDRESS:begin
     if(tx>=nx||ty>=((height+31)>>5))begin error<=1;state<=FAILED;end
     else if(cull_outside)rejected_references<=rejected_references+1;
     else begin tile<=ty*nx+tx;state<=COUNT_READ;end
    end
    COUNT_READ:state<=COUNT;
    COUNT:begin
     if(reference_count>=refs_capacity)begin error<=3;state<=FAILED;end
     else begin
      reference_count<=reference_count+1;
     end
    end
    ADVANCE:begin
     geom_no<=geom_no+1;
     if(cmd[7:0]==3&&!half)begin half<=1;state<=DECODE;end
     else if(command_no+1>=command_count)begin error<=1;state<=FAILED;end
     else begin command_no<=command_no+1;half<=0;state<=FETCH;end
    end
    PREFIX_READ:state<=PREFIX;
    PREFIX:begin sum<=sum+bin_rdata[15:0];fast_refs<=reference_count<=FAST_REFS;
     if(item+1==tiles)begin item<=0;state<=HEADER_READ;end else begin item<=item+1;state<=PREFIX_READ;end
    end
    HEADER_READ:state<=HEADER_REQ;
    HEADER_REQ:if(wr_ready)begin beat<=0;state<=HEADER_DATA;end
    HEADER_DATA:if(wd_ready)begin beat<=beat+1;if(beat==1)state<=HEADER_ACK;end
    HEADER_ACK:if(wr_done)begin
     if(item+1==tiles)begin index<=0;state<=geometry_count==0?FINISH:READ_DESC;end
     else begin item<=item+1;state<=HEADER_READ;end
    end
    READ_DESC:if(rd_ready)begin beat<=0;state<=READ_DESC_DATA;end
    READ_DESC_DATA:if(response.valid)begin
     beat<=beat+1;
     if(response.last!=(beat==15))begin error<=2;state<=FAILED;end
     else if(response.last)state<=RECT;
    end
    RECT:begin
     tx<=descriptor[19*32+:32]>>5;tx0<=descriptor[19*32+:32]>>5;tx1<=descriptor[20*32+:32]>>5;
     ty<=descriptor[21*32+:32]>>5;ty1<=descriptor[22*32+:32]>>5;
     if(descriptor[96]&&!descriptor_bounds_valid)begin error<=1;state<=FAILED;end
     else if(!descriptor[96])state<=NEXT_DESC;
     else if(CULL_EMPTY_TILES&&cull_enable)begin cull_scatter<=1;state<=CULL_DIFF;end
     else state<=SCATTER_TILE;
    end
    SCATTER_TILE:if(!cull_outside)begin tile<=ty*nx+tx;state<=SCATTER_READ;end
    SCATTER_READ:state<=SCATTER_ADDRESS;
    SCATTER_ADDRESS:begin
     scatter_addr<=bin_base+16384+({9'b0,bin_rdata[38:16]}<<2);scatter_index<=bin_rdata[30:16];
     state<=fast_refs?SCATTER_DATA:SCATTER_REQ;
    end
    SCATTER_REQ:if(wr_ready)state<=SCATTER_DATA;
    SCATTER_DATA:if(fast_refs||wd_ready)state<=SCATTER_ACK;
    SCATTER_ACK:begin end
    // Max of the same linear edge over all pixel centres in a complete tile.
    // Testing a superset (including the padded last row) is conservative.
    CULL_DIFF:begin
     for(integer ce=0;ce<3;ce=ce+1)begin
      cull_dx[ce]<=cx((ce+2)%3)-cx((ce+1)%3);
      cull_dy[ce]<=cy((ce+2)%3)-cy((ce+1)%3);
      cull_ax[ce]<=corner(tx,cy((ce+2)%3)<cy((ce+1)%3))-$signed(cx((ce+1)%3));
      cull_ay[ce]<=corner(ty,cx((ce+2)%3)>=cx((ce+1)%3))-$signed(cy((ce+1)%3));
      cull_inclusive[ce]<=cy((ce+2)%3)<cy((ce+1)%3)||
       (cy((ce+2)%3)==cy((ce+1)%3)&&cx((ce+2)%3)>cx((ce+1)%3));
     end state<=CULL_PRODUCTS;
    end
    CULL_PRODUCTS:begin
     for(integer ce=0;ce<3;ce=ce+1)begin
      cull_p[ce]<=cull_dx[ce]*cull_ay[ce];cull_q[ce]<=cull_dy[ce]*cull_ax[ce];
      cull_step_x[ce]<=-($signed({{18{cull_dy[ce][16]}},cull_dy[ce]})<<<9);
      cull_step_y[ce]<=$signed({{18{cull_dx[ce][16]}},cull_dx[ce]})<<<9;
     end state<=CULL_INIT;
    end
    CULL_INIT:begin
     for(integer ce=0;ce<3;ce=ce+1)begin
      cull_edge[ce]<=$signed({cull_p[ce][33],cull_p[ce]})-$signed({cull_q[ce][33],cull_q[ce]});
      cull_row[ce]<=$signed({cull_p[ce][33],cull_p[ce]})-$signed({cull_q[ce][33],cull_q[ce]});
     end state<=cull_scatter?SCATTER_TILE:COUNT_ADDRESS;
    end
    NEXT_DESC:if(index+1==geometry_count)begin
     if(fast_refs&&reference_count!=0)begin
      flush_offset<=0;flush_pair<=0;flush_beats<=reference_count>=32?16:(reference_count+1)>>1;state<=REFS_REQ;
     end else state<=FINISH;
    end else begin index<=index+1;state<=READ_DESC;end
    REFS_REQ:if(wr_ready)begin beat<=0;state<=REFS_READ;end
    REFS_READ:begin
     flush_strb<=({16'b0,flush_pair,1'b0}+32'd1)>=reference_count?8'h0f:8'hff;
     state<=REFS_WAIT;
    end
    REFS_WAIT:state<=REFS_DATA;
    REFS_DATA:if(wd_ready)begin
     flush_pair<=flush_pair+1;beat<=beat+1;
     state<=beat+1==flush_beats?REFS_ACK:REFS_READ;
    end
    REFS_ACK:if(wr_done)begin
     if(flush_offset+({27'b0,flush_beats}<<1)>=reference_count)state<=FINISH;
     else begin
      flush_offset<=flush_offset+({27'b0,flush_beats}<<1);
      flush_beats<=flush_remaining>=32?16:(flush_remaining+1)>>1;state<=REFS_REQ;
     end
    end
    FINISH:begin done<=1;state<=IDLE;end
    FAILED:begin done<=1;state<=IDLE;end
    default:state<=IDLE;
   endcase
   if((advance_count||advance_scatter)&&!wr_error&&!(response.valid&&response_ready&&response.error))begin
    state<=advance_scatter?SCATTER_TILE:COUNT_ADDRESS;
    if(tx==tx1)begin
     tx<=tx0;
     if(ty==ty1)state<=advance_scatter?NEXT_DESC:ADVANCE;
     else begin
      ty<=ty+1;
      for(integer ce=0;ce<3;ce=ce+1)begin
       cull_edge[ce]<=cull_row[ce]+cull_step_y[ce];cull_row[ce]<=cull_row[ce]+cull_step_y[ce];
      end
     end
    end else begin
     tx<=tx+1;for(integer ce=0;ce<3;ce=ce+1)cull_edge[ce]<=cull_edge[ce]+cull_step_x[ce];
    end
   end
  end
 end
endmodule
