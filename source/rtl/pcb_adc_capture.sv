// Freeze-on-complete full raw 200MHz packed32 frame. PS reads without JTAG.
// No assertion of ADC external IO timing/analog bandwidth is made here.
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
 reg request=0;reg seen=0,complete=0;
 (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) reg [2:0] req_sync=0,rst_sync=0;
 (* ASYNC_REG="TRUE" *) reg [2:0] done_sync=0;
 reg busy,done,overrun;reg [31:0] generation;
 reg [1:0] phase=0;reg [11:0] hb=0;reg [10:0] warm=0;
 reg running=0,capturing=0,warm_done=0;reg [13:0] wp=0;
 (* ram_style="block" *) reg [31:0] raw_mem[0:16383];
 wire [31:0] packed_word={hb,running,grounded_pads,phase,adc_otr,adc_data};
 assign adc_clk=phase[1];assign adc_oeb=~running;assign adc_pwdn=~running;assign irq=done;
 always @(posedge fast)begin
  req_sync<={req_sync[1:0],request};rst_sync<={rst_sync[1:0],rstn};hb<=hb+1;
  if(!rst_sync[2]||!locked)begin running<=0;capturing<=0;phase<=0;seen<=req_sync[2];complete<=0;warm<=0;warm_done<=0;end
  else begin
   if(running)phase<=phase+1;else phase<=0;
   if(req_sync[2]!=seen&&!capturing&&!running)begin seen<=req_sync[2];running<=1;warm<=0;warm_done<=0;wp<=0;end
   if(running&&!capturing)begin
    warm_done<=warm==1022;
    if(warm_done)capturing<=1;else warm<=warm+1;
   end
   if(capturing)begin
    if(wp==16383)begin capturing<=0;running<=0;complete<=~complete;end else wp<=wp+1;
   end
  end
 end
 // Separate simple dual-clock BRAM ports from register selection. Combining
 // status and RAM reads in one assignment makes Vivado 2018.3 infer LUT RAM.
 always @(posedge fast)if(capturing)raw_mem[wp]<=packed_word;
 reg [31:0] raw_q;reg read_raw;
 always @(posedge clk)begin
  if(host_re&&host_addr[16])raw_q<=raw_mem[host_addr[15:2]];
  read_raw<=host_re&&host_addr[16];
 end
 reg last_done;
 always @(posedge clk)begin
  done_sync<={done_sync[1:0],complete};
  if(!rstn)begin request<=0;busy<=0;done<=0;overrun<=0;last_done<=0;generation<=0;end
  else begin
   last_done<=done_sync[2];
   if(done_sync[2]!=last_done)begin busy<=0;done<=1;generation<=generation+1;end
   if(host_we&&host_addr==0&&host_wdata==1)begin
    if(busy)overrun<=1;
    else begin request<=~request;busy<=1;done<=0;overrun<=0;end
   end
  end
  if(read_raw)host_rdata<=raw_q;
  else if(host_re&&!host_addr[16])begin
   case(host_addr)
    4:host_rdata<={28'b0,locked,overrun,done,busy};8:host_rdata<=32'h50414431;
    12:host_rdata<=generation;16:host_rdata<=16384;20:host_rdata<=50000000;
    default:host_rdata<=0;
   endcase
  end
 end
endmodule
