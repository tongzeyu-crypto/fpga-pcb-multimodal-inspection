// PCB AI ABI1. Full multichannel CHW layer engine; four signed INT8 products.
// Host schedules layers for task_id 1 (registration) or 2 (frame confidence).
// SRAM access is synchronous. No PC, random weights, or silent SW fallback.
module pcb_ai_core(
 input wire clk,rstn,
 input wire host_we,host_re,input wire [17:0] host_addr,
 input wire [31:0] host_wdata,output reg [31:0] host_rdata,
 output wire irq
);
 localparam IDLE=0,INIT=1,ADDR=2,READ=3,LATCH=4,MUL=5,SUM=6,STORE=7,
            GAP_ADDR=8,GAP_READ=9,GAP_ADD=10,GAP_STORE=11,GAP_DIV=12,CHECK1=13,CHECK2=14,CHECK3=15,ADDR2=16,SHIFT_RESULT=17,SAT_RESULT=18;
 reg [4:0] state;
 reg done,error;reg [31:0] cycles;
 reg [7:0] iw,ih,ci,co,ow,oh;reg [1:0] kernel,stride,pad;
 reg [4:0] shift;reg relu,op_gap;reg [1:0] task_id;
 reg [7:0] ox,oy,oc,ic;reg [1:0] ky,kx,lane;
 reg [13:0] ia,oa;reg [11:0] wa;reg pad_sample,last_group,tap_last;
 reg [13:0] input_base;reg [11:0] weight_base,weights_per_oc;
 reg signed [15:0] input_row;reg signed [8:0] input_x;
 reg signed [7:0] xq,wq,xlane[0:3],wlane[0:3],result;
 (* ram_style="block" *) reg signed [7:0] input_mem[0:16383];
 (* ram_style="block" *) reg signed [7:0] weight_mem[0:4095];
 (* ram_style="block" *) reg signed [7:0] output_mem[0:16383];
 reg signed [31:0] bias_mem[0:31];
 reg signed [31:0] acc;
 reg signed [31:0] shifted;
 reg [13:0] gap_rem;reg [7:0] gap_quot;reg gap_negative;
 wire signed [13:0] gap_total=$signed(acc[13:0])+$signed({{6{xq[7]}},xq});
 (* use_dsp="yes" *) reg signed [15:0] p0,p1,p2,p3;
 (* use_dsp="no" *) wire signed [16:0] s01={p0[15],p0}+{p1[15],p1};
 (* use_dsp="no" *) wire signed [16:0] s23={p2[15],p2}+{p3[15],p3};
 (* use_dsp="no" *) wire signed [17:0] sum4={s01[16],s01}+{s23[16],s23};
 wire signed [31:0] total=acc+{{14{sum4[17]}},sum4};
 (* use_dsp="no" *) wire signed [17:0] xx=$signed({1'b0,ox})*$signed({1'b0,stride})+$signed({1'b0,kx})-$signed({1'b0,pad});
 (* use_dsp="no" *) wire signed [17:0] yy=$signed({1'b0,oy})*$signed({1'b0,stride})+$signed({1'b0,ky})-$signed({1'b0,pad});
 wire busy=state!=IDLE;assign irq=done||error;
 reg [15:0] in_plane,out_plane,weight_channels;reg [3:0] kernel_area;
 reg [23:0] input_count,output_count,weight_count;
 reg [9:0] expected_w,expected_h;
 always @(posedge clk)begin
  in_plane<=iw*ih;out_plane<=ow*oh;weight_channels<=ci*co;kernel_area<=kernel*kernel;
  input_count<=in_plane*ci;output_count<=out_plane*co;weight_count<=weight_channels*kernel_area;
  weights_per_oc<=ci*kernel_area;
  expected_w<=((iw+2*pad-kernel)>>(stride==2?1:0))+1;
  expected_h<=((ih+2*pad-kernel)>>(stride==2?1:0))+1;
 end
 function automatic [7:0] quantize(input signed [31:0] a,input [4:0] sh,input re);
  reg signed [31:0] q;begin q=a>>>sh;
   if(re&&q<0)q=0;
   quantize=q>127?8'h7f:q< -128?8'h80:q[7:0];end
 endfunction
 // CPU output port is synchronous, deliberately avoiding LUT-backed frame RAM.
 reg signed [7:0] host_output;
 always @(posedge clk)begin
  if(host_re)host_output<=output_mem[host_addr[15:2]];
  if(host_we&&!busy)begin
   if(host_addr[17:16]==1)input_mem[host_addr[15:2]]<=host_wdata[7:0];
   if(host_addr>=18'h30000&&host_addr<18'h34000)weight_mem[host_addr[13:2]]<=host_wdata[7:0];
   if(host_addr>=18'h38000&&host_addr<18'h38080)bias_mem[host_addr[6:2]]<=host_wdata;
  end
  xq<=input_mem[ia];wq<=weight_mem[wa];
  if(state==STORE||state==GAP_STORE)output_mem[oa]<=result;
 end
 reg read_output;
 always @(posedge clk)begin
  read_output<=host_re&&host_addr[17:16]==2;
  if(read_output)host_rdata<={{24{host_output[7]}},host_output};
  else if(host_re)case(host_addr)
   4:host_rdata<={29'b0,error,done,busy};8:host_rdata<=32'h50414931;
   12:host_rdata<=task_id;64:host_rdata<=cycles;68:host_rdata<=32'h20261103;
   default:host_rdata<=0;
  endcase
 end
 integer i;
 always @(posedge clk)begin
  if(!rstn)begin
   state<=IDLE;done<=0;error<=0;cycles<=0;task_id<=0;iw<=0;ih<=0;ci<=0;co<=0;ow<=0;oh<=0;
   kernel<=0;stride<=0;pad<=0;shift<=0;relu<=0;op_gap<=0;
   ox<=0;oy<=0;oc<=0;ic<=0;kx<=0;ky<=0;lane<=0;ia<=0;wa<=0;oa<=0;acc<=0;
   result<=0;p0<=0;p1<=0;p2<=0;p3<=0;last_group<=0;tap_last<=0;pad_sample<=0;
  end else begin
   if(busy)cycles<=cycles+1;
   if(host_we&&host_addr==0&&host_wdata==2)begin state<=IDLE;done<=0;error<=0;cycles<=0;end
   else begin
    if(host_we&&!busy&&host_addr<18'h10000)case(host_addr)
     12:task_id<=host_wdata[1:0];16:iw<=host_wdata[7:0];20:ih<=host_wdata[7:0];
     24:ci<=host_wdata[7:0];28:co<=host_wdata[7:0];32:kernel<=host_wdata[1:0];
     36:stride<=host_wdata[1:0];40:pad<=host_wdata[1:0];44:shift<=host_wdata[4:0];
     48:relu<=host_wdata[0];52:op_gap<=host_wdata[0];56:ow<=host_wdata[7:0];60:oh<=host_wdata[7:0];
    endcase
    case(state)
     IDLE:if(host_we&&host_addr==0&&host_wdata==1)begin
      done<=0;error<=0;cycles<=0;
      state<=CHECK1;
     end
     CHECK1:state<=CHECK2;
     CHECK2:state<=CHECK3;
     CHECK3:begin
      if((task_id!=1&&task_id!=2)||iw==0||ih==0||ci==0||co==0||ci>32||co>32||
       iw>80||ih>48||input_count>16384||ow==0||oh==0||output_count>16384||
       (!op_gap&&((kernel!=1&&kernel!=3)||(stride!=1&&stride!=2)||pad>1||weight_count>4096||
         ow!=expected_w||oh!=expected_h))||
       (op_gap&&(iw!=8||ih!=6||co!=ci||ow!=1||oh!=1)))begin error<=1;state<=IDLE;end
      else begin ox<=0;oy<=0;oc<=0;ic<=0;ia<=0;oa<=0;weight_base<=0;state<=op_gap?GAP_ADDR:INIT;acc<=0;end
     end
     INIT:begin acc<=bias_mem[oc];ic<=0;kx<=0;ky<=0;lane<=0;last_group<=0;input_base<=0;wa<=weight_base;state<=ADDR;end
     ADDR:begin
      input_row<=yy*$signed({1'b0,iw});input_x<=xx[8:0];
      pad_sample<=xx<0||yy<0||xx>=iw||yy>=ih;
      tap_last<=ic==ci-1&&ky==kernel-1&&kx==kernel-1;state<=ADDR2;
     end
     ADDR2:begin ia<=input_base+input_row+input_x;state<=READ;end
     READ:state<=LATCH;
     LATCH:begin
      xlane[lane]<=pad_sample?8'sd0:xq;wlane[lane]<=wq;
      wa<=wa+1;
      if(tap_last)begin
       for(i=0;i<4;i=i+1)if(i>lane)begin xlane[i]<=0;wlane[i]<=0;end
       last_group<=1;state<=MUL;
      end else begin
       if(kx==kernel-1)begin kx<=0;if(ky==kernel-1)begin ky<=0;ic<=ic+1;input_base<=input_base+in_plane;end else ky<=ky+1;end else kx<=kx+1;
       if(lane==3)begin lane<=0;state<=MUL;end else begin lane<=lane+1;state<=ADDR;end
      end
     end
     MUL:begin p0<=xlane[0]*wlane[0];p1<=xlane[1]*wlane[1];p2<=xlane[2]*wlane[2];p3<=xlane[3]*wlane[3];state<=SUM;end
     SUM:begin acc<=total;if(last_group)state<=SHIFT_RESULT;else state<=ADDR;end
     SHIFT_RESULT:begin shifted<=acc>>>shift;state<=SAT_RESULT;end
     SAT_RESULT:begin
      if(relu&&shifted<0)result<=0;
      else if(shifted>127)result<=127;
      else if(shifted< -128)result<=-128;
      else result<=shifted[7:0];
      state<=STORE;
     end
     STORE:begin
      oa<=oa+1;
      if(ox==ow-1)begin ox<=0;if(oy==oh-1)begin oy<=0;if(oc==co-1)begin done<=1;state<=IDLE;end else begin oc<=oc+1;weight_base<=weight_base+weights_per_oc;state<=INIT;end end else begin oy<=oy+1;state<=INIT;end end
      else begin ox<=ox+1;state<=INIT;end
     end
     GAP_ADDR:state<=GAP_READ;
     GAP_READ:state<=GAP_ADD;
     GAP_ADD:begin
      if(ox==47)begin gap_rem<=gap_total<0?-gap_total:gap_total;gap_negative<=gap_total<0;gap_quot<=0;oa<=oc;state<=GAP_DIV;end
      else begin acc<=acc+$signed(xq);ox<=ox+1;ia<=ia+1;state<=GAP_ADDR;end
     end
     GAP_DIV:begin
      if(gap_rem>=48)begin gap_rem<=gap_rem-48;gap_quot<=gap_quot+1;end
      else begin result<=gap_negative?-$signed(gap_quot):$signed(gap_quot);state<=GAP_STORE;end
     end
     GAP_STORE:begin
      if(oc==ci-1)begin done<=1;state<=IDLE;end
      else begin oc<=oc+1;ox<=0;acc<=0;ia<=ia+1;state<=GAP_ADDR;end
     end
     default:state<=IDLE;
    endcase
   end
  end
 end
endmodule
