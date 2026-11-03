// Two independently owned raw-frame banks. The producer never overwrites a
// completed bank until PS explicitly acknowledges it. Continuous acquisition
// can fill the other bank while PS reads the selected bank.
module pcb_adc_capture(
 input wire clk,rstn,input wire host_we,host_re,input wire [16:0] host_addr,
 input wire [31:0] host_wdata,output reg [31:0] host_rdata,output wire irq,
 input wire board_clk,input wire [13:0] adc_data,input wire adc_otr,
 input wire [1:0] grounded_pads,output wire adc_clk,adc_oeb,adc_pwdn
);
 wire fast,fast_raw,fb,fb_raw,locked;
 MMCME2_BASE #(.CLKIN1_PERIOD(40.0),.DIVCLK_DIVIDE(1),.CLKFBOUT_MULT_F(32.0),.CLKOUT0_DIVIDE_F(4.0))
 mmcm(.CLKIN1(board_clk),.CLKFBIN(fb),.CLKFBOUT(fb_raw),.CLKOUT0(fast_raw),.LOCKED(locked),.RST(1'b0),.PWRDWN(1'b0));
 BUFG b0(.I(fb_raw),.O(fb));BUFG b1(.I(fast_raw),.O(fast));
 reg request=0,stop_request=0,seen=0,stop_seen=0,continuous_host=0,continuous_fast=0;
 reg [1:0] acknowledge=0,complete=0;
 (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) reg [2:0] req_sync=0,stop_sync=0,rst_sync=0,continuous_sync=0;
 (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) reg [2:0] ack_sync0=0,ack_sync1=0;
 (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) reg [2:0] done_sync0=0,done_sync1=0,active_sync=0;
 reg busy=0,overrun=0,read_bank=0;reg [31:0] generation=0,sequence_fast=0;
 reg [31:0] bank_generation0=0,bank_generation1=0;
 reg [159:0] host_meta0=0,host_meta1=0;reg [1:0] last_done=0;
 reg [63:0] tick_fast=0,begin_tick0=0,end_tick0=0,begin_tick1=0,end_tick1=0;
 reg [1:0] phase=0;reg [11:0] hb=0;reg [10:0] warm=0;
 reg running=0,capturing=0,warm_done=0,write_bank=0;reg [13:0] wp=0;
 (* ram_style="block" *) reg [31:0] raw_mem[0:32767];
 wire [1:0] owned_fast=complete^{ack_sync1[2],ack_sync0[2]};
 wire [1:0] completed_host={done_sync1[2],done_sync0[2]};
 wire [1:0] ready_host=last_done^acknowledge;
 wire [31:0] packed_word={hb,running,grounded_pads,phase,adc_otr,adc_data};
 assign adc_clk=phase[1];assign adc_oeb=~running;assign adc_pwdn=~running;assign irq=|ready_host;
 always @(posedge fast)begin
  req_sync<={req_sync[1:0],request};stop_sync<={stop_sync[1:0],stop_request};rst_sync<={rst_sync[1:0],rstn};continuous_sync<={continuous_sync[1:0],continuous_host};
  ack_sync0<={ack_sync0[1:0],acknowledge[0]};ack_sync1<={ack_sync1[1:0],acknowledge[1]};hb<=hb+1;tick_fast<=tick_fast+1;
  if(!rst_sync[2]||!locked)begin
   running<=0;capturing<=0;phase<=0;seen<=req_sync[2];stop_seen<=stop_sync[2];warm<=0;warm_done<=0;
   complete<=0;write_bank<=0;wp<=0;sequence_fast<=0;bank_generation0<=0;bank_generation1<=0;continuous_fast<=0;tick_fast<=0;begin_tick0<=0;end_tick0<=0;begin_tick1<=0;end_tick1<=0;
  end else begin
   if(running)phase<=phase+1;else phase<=0;
   if(req_sync[2]!=seen)begin
    seen<=req_sync[2];
    if(!running&&owned_fast!=3)begin running<=1;warm<=0;warm_done<=0;capturing<=0;wp<=0;write_bank<=owned_fast[0];continuous_fast<=continuous_sync[2];end
   end
   if(running&&!capturing)begin
    if(!warm_done)begin if(warm==1023)warm_done<=1;else warm<=warm+1;end
    else if(owned_fast!=3)begin write_bank<=owned_fast[0];wp<=0;capturing<=1;end
   end
   if(capturing)begin
    if(wp==0)begin if(write_bank)begin_tick1<=tick_fast;else begin_tick0<=tick_fast;end
    if(wp==16383)begin
     complete[write_bank]<=~complete[write_bank];sequence_fast<=sequence_fast+1;
     if(write_bank)begin bank_generation1<=sequence_fast+1;end_tick1<=tick_fast;end
     else begin bank_generation0<=sequence_fast+1;end_tick0<=tick_fast;end
     if(continuous_fast)begin
      if(!owned_fast[!write_bank])begin write_bank<=!write_bank;wp<=0;end
      else capturing<=0;
     end else begin capturing<=0;running<=0;end
    end else wp<=wp+1;
   end
   if(stop_sync[2]!=stop_seen)begin stop_seen<=stop_sync[2];running<=0;capturing<=0;end
  end
 end
 always @(posedge fast)if(capturing)raw_mem[{write_bank,wp}]<=packed_word;
 reg [31:0] raw_q;reg read_raw=0;
 always @(posedge clk)begin
  if(host_re&&host_addr[16])raw_q<=raw_mem[{read_bank,host_addr[15:2]}];
  read_raw<=host_re&&host_addr[16];
 end
 always @(posedge clk)begin
  done_sync0<={done_sync0[1:0],complete[0]};done_sync1<={done_sync1[1:0],complete[1]};active_sync<={active_sync[1:0],running};
  if(!rstn)begin request<=0;stop_request<=0;busy<=0;overrun<=0;last_done<=0;generation<=0;acknowledge<=0;read_bank<=0;continuous_host<=0;host_meta0<=0;host_meta1<=0;end
  else begin
   last_done<=completed_host;
   if(completed_host!=last_done)begin
    // Bundled metadata has been stable for the completion synchronizer latency;
    // acknowledge/ownership prevents the producer changing it until release.
    if(completed_host[0]!=last_done[0])host_meta0<={bank_generation0,begin_tick0,end_tick0};
    if(completed_host[1]!=last_done[1])host_meta1<={bank_generation1,begin_tick1,end_tick1};
    generation<=generation+(completed_host[0]!=last_done[0])+(completed_host[1]!=last_done[1]);
    if(!continuous_host)busy<=0;
   end
   if(host_we)case(host_addr)
    0:if(host_wdata==1)begin
      if(busy||ready_host!=0||active_sync[2])overrun<=1;
      else begin request<=~request;busy<=1;overrun<=0;end
     end else if(host_wdata==2)begin stop_request<=~stop_request;busy<=0;end
    32:read_bank<=host_wdata[0];
    36:begin if(host_wdata[0])acknowledge[0]<=completed_host[0];if(host_wdata[1])acknowledge[1]<=completed_host[1];end
    40:if(!busy&&!active_sync[2])continuous_host<=host_wdata[0];
   endcase
  end
  if(read_raw)host_rdata<=raw_q;
  else if(host_re&&!host_addr[16])case(host_addr)
   4:host_rdata<={27'b0,active_sync[2],locked,overrun,|ready_host,busy};
   8:host_rdata<=32'h50414432;12:host_rdata<=generation;16:host_rdata<=16384;20:host_rdata<=50000000;
   24:host_rdata<=2;28:host_rdata<={30'b0,ready_host};32:host_rdata<={31'b0,read_bank};
   40:host_rdata<={31'b0,continuous_host};44:host_rdata<=host_meta0[159:128];48:host_rdata<=host_meta1[159:128];
   52:host_rdata<=host_meta0[95:64];56:host_rdata<=host_meta0[127:96];60:host_rdata<=host_meta0[31:0];64:host_rdata<=host_meta0[63:32];
   68:host_rdata<=host_meta1[95:64];72:host_rdata<=host_meta1[127:96];76:host_rdata<=host_meta1[31:0];80:host_rdata<=host_meta1[63:32];
   default:host_rdata<=0;
  endcase
 end
endmodule
