// Independent demonstration core, not included in the earlier combined bitstream.
// OP1: 64-point rectangular-window DFT, integer mean removal, 33 power bins.
// OP2: Kelvin*16 -> milli-Celsius plus min/max/index/threshold pixel count.
// OP3: shared RGB888 grayscale / thermal affine clipping -> signed INT8.
module pcb_demo_core(input wire clk,rstn,input wire host_we,host_re,
 input wire [15:0] host_addr,input wire [31:0] host_wdata,
 output reg [31:0] host_rdata,output wire irq);
 localparam IDLE=0,MEAN_RD=1,MEAN_SUM=2,DFT_RD=3,DFT_MUL=4,DFT_ACC=5,
  DFT_NORM=6,DFT_SQ=7,DFT_STORE=8,PIX_RD=9,PIX_CALC=10,PIX_STORE=11,FINISH=12;
 reg [3:0] state=IDLE;reg busy=0,done=0,error=0;
 reg [31:0] op=1,count=64,threshold_mc=40000,mode=0,base=4370,shift=2,generation=0;
 reg signed [31:0] min_mc=0,max_mc=0,pixel_result;
 reg [31:0] max_index=0,hot_count=0;reg [7:0] index=0;reg [5:0] bin=0,phase=0;
 (* ram_style="block" *) reg [31:0] input_mem[0:255],output_mem[0:255];
 (* rom_style="block" *) reg signed [15:0] cos_rom[0:63],sin_rom[0:63];
 initial begin $readmemh("cos_q14.mem",cos_rom);$readmemh("negsin_q14.mem",sin_rom);end
 reg [31:0] input_q,output_q;reg read_output;
 reg signed [15:0] coeff_r,coeff_i,mean,norm_r,norm_i;
 reg signed [23:0] mean_sum;
 (* use_dsp="yes" *) reg signed [31:0] prod_r,prod_i;
 (* use_dsp="yes" *) reg [31:0] square_r,square_i;
 reg signed [39:0] acc_r,acc_i;
 wire signed [15:0] centered=$signed(input_q[15:0])-mean;
 wire [31:0] power=square_r+square_i;
 wire reading=state==MEAN_RD||state==DFT_RD||state==PIX_RD;
 wire writing=rstn&&(state==DFT_STORE||state==PIX_STORE);
 wire [7:0] write_index=state==DFT_STORE?{2'b0,bin}:index;
 wire [31:0] write_data=state==DFT_STORE?power:pixel_result;
 // Narrow, constant arithmetic for the pixel path; no variable divider.
 (* use_dsp="no" *) wire [22:0] raw125=({7'b0,input_q[15:0]}<<7)-({7'b0,input_q[15:0]}<<1)-{7'b0,input_q[15:0]};
 wire signed [31:0] temp_mc=$signed({10'b0,raw125[22:1]})-32'sd273150;
 (* use_dsp="no" *) wire [15:0] gray_sum=input_q[23:16]*16'd77+input_q[15:8]*16'd150+input_q[7:0]*16'd29;
 wire signed [17:0] delta=$signed({2'b0,input_q[15:0]})-$signed({2'b0,base[15:0]});
 wire signed [17:0] scaled=delta>>>shift[3:0];
 wire signed [31:0] rgb_quant=$signed({24'b0,gray_sum[15:8]})-32'sd128;
 wire signed [31:0] thermal_quant=scaled<0?-32'sd128:scaled>255?32'sd127:scaled-32'sd128;
 assign irq=done;
 // Explicit RAM templates keep host/control selection outside BRAM ports.
 always @(posedge clk)begin
  if(rstn&&host_we&&!busy&&host_addr[15:12]==1)input_mem[host_addr[9:2]]<=host_wdata;
  if(reading)input_q<=input_mem[index];
  if(state==DFT_RD)begin coeff_r<=cos_rom[phase];coeff_i<=sin_rom[phase];end
  if(writing)output_mem[write_index]<=write_data;
  if(host_re&&host_addr[15:12]==2)output_q<=output_mem[host_addr[9:2]];
  read_output<=host_re&&host_addr[15:12]==2;
  if(read_output)host_rdata<=output_q;
  else if(host_re)case(host_addr)
   4:host_rdata<={29'b0,error,done,busy};8:host_rdata<=32'h50445031;
   12:host_rdata<=op;16:host_rdata<=count;20:host_rdata<=threshold_mc;
   24:host_rdata<=mode;28:host_rdata<=base;32:host_rdata<=shift;
   36:host_rdata<=min_mc;40:host_rdata<=max_mc;44:host_rdata<=max_index;
   48:host_rdata<=hot_count;52:host_rdata<=generation;56:host_rdata<=64;
   default:host_rdata<=0;
  endcase
 end
 always @(posedge clk)begin
  if(!rstn)begin
   state<=IDLE;busy<=0;done<=0;error<=0;generation<=0;op<=1;count<=64;
   threshold_mc<=40000;mode<=0;base<=4370;shift<=2;min_mc<=0;max_mc<=0;
   max_index<=0;hot_count<=0;index<=0;bin<=0;phase<=0;
   mean_sum<=0;mean<=0;acc_r<=0;acc_i<=0;
  end else if(host_we&&host_addr==0&&host_wdata==2)begin
   state<=IDLE;busy<=0;done<=0;error<=0;
  end else begin
   if(host_we)begin
    if(busy)error<=1;
    else if(host_addr[15:12]==0)case(host_addr)
     0:begin
      if(host_wdata!=1||op<1||op>3||count==0||count>256||(op==1&&count!=64)||(op==3&&(mode>1||shift>8)))begin error<=1;done<=0;end
      else begin
       busy<=1;done<=0;error<=0;index<=0;bin<=0;phase<=0;mean_sum<=0;mean<=0;
       acc_r<=0;acc_i<=0;min_mc<=0;max_mc<=0;max_index<=0;hot_count<=0;
       state<=op==1?MEAN_RD:PIX_RD;
      end
     end
     12:op<=host_wdata;16:count<=host_wdata;20:threshold_mc<=host_wdata;
     24:mode<=host_wdata;28:base<=host_wdata;32:shift<=host_wdata;
     default:error<=1;
    endcase
   end
   case(state)
    MEAN_RD:state<=MEAN_SUM;
    MEAN_SUM:begin
     mean_sum<=mean_sum+{{8{input_q[15]}},input_q[15:0]};
     if(index==63)begin mean<=$signed(mean_sum+{{8{input_q[15]}},input_q[15:0]})>>>6;index<=0;state<=DFT_RD;end
     else begin index<=index+1;state<=MEAN_RD;end
    end
    DFT_RD:state<=DFT_MUL;
    DFT_MUL:begin prod_r<=centered*coeff_r;prod_i<=centered*coeff_i;state<=DFT_ACC;end
    DFT_ACC:begin
     acc_r<=acc_r+{{8{prod_r[31]}},prod_r};acc_i<=acc_i+{{8{prod_i[31]}},prod_i};
     if(index==63)state<=DFT_NORM;
     else begin index<=index+1;phase<=phase+bin;state<=DFT_RD;end
    end
    DFT_NORM:begin norm_r<=acc_r>>>20;norm_i<=acc_i>>>20;state<=DFT_SQ;end
    DFT_SQ:begin square_r<=norm_r*norm_r;square_i<=norm_i*norm_i;state<=DFT_STORE;end
    DFT_STORE:begin
     if(bin==32)state<=FINISH;
     else begin bin<=bin+1;index<=0;phase<=0;acc_r<=0;acc_i<=0;state<=DFT_RD;end
    end
    PIX_RD:state<=PIX_CALC;
    PIX_CALC:begin pixel_result<=op==2?temp_mc:(mode==0?rgb_quant:thermal_quant);state<=PIX_STORE;end
    PIX_STORE:begin
     if(op==2)begin
      if(index==0||pixel_result<min_mc)min_mc<=pixel_result;
      if(index==0||pixel_result>max_mc)begin max_mc<=pixel_result;max_index<=index;end
      if(pixel_result>=$signed(threshold_mc))hot_count<=hot_count+1;
     end
     if(index+1==count)state<=FINISH;
     else begin index<=index+1;state<=PIX_RD;end
    end
    FINISH:begin busy<=0;done<=1;generation<=generation+1;state<=IDLE;end
    default:begin end
   endcase
  end
 end
endmodule
