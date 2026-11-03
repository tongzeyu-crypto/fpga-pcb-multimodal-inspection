// Independent AW/W channels, one outstanding read/write, byte strobe validation.
module pcb_adc_axi(
 (* X_INTERFACE_PARAMETER="ASSOCIATED_BUSIF s_axi,ASSOCIATED_RESET rstn,FREQ_HZ 62500000" *) input wire clk,
 (* X_INTERFACE_PARAMETER="POLARITY ACTIVE_LOW" *) input wire rstn,
 input wire [17:0] s_axi_awaddr,input wire s_axi_awvalid,output wire s_axi_awready,
 input wire [31:0] s_axi_wdata,input wire [3:0] s_axi_wstrb,input wire s_axi_wvalid,output wire s_axi_wready,
 output reg [1:0] s_axi_bresp,output reg s_axi_bvalid,input wire s_axi_bready,
 input wire [17:0] s_axi_araddr,input wire s_axi_arvalid,output wire s_axi_arready,
 output reg [31:0] s_axi_rdata,output reg [1:0] s_axi_rresp,output reg s_axi_rvalid,input wire s_axi_rready,
 output wire irq,
 input wire board_clk,input wire [13:0] adc_data,input wire adc_otr,input wire [1:0] grounded_pads,output wire adc_clk,adc_oeb,adc_pwdn
);
 reg ap,wp;reg [17:0] aw,ar;reg [31:0] wd;reg [3:0] ws;reg [2:0] read_wait;
 reg host_we,host_re;reg [17:0] host_addr;reg [31:0] host_wdata;wire [31:0] host_rdata;
 // Serialize read requests against buffered writes to the single host port.
 assign s_axi_awready=!ap&&!s_axi_bvalid&&read_wait==0&&!(s_axi_arvalid&&s_axi_arready);
 assign s_axi_wready=!wp&&!s_axi_bvalid&&read_wait==0&&!(s_axi_arvalid&&s_axi_arready);
 assign s_axi_arready=read_wait==0&&!s_axi_rvalid&&!ap&&!wp&&!host_we;
 pcb_adc_capture core(.clk(clk),.rstn(rstn),.host_we(host_we),.host_re(host_re),.host_addr(host_addr[16:0]),.host_wdata(host_wdata),.host_rdata(host_rdata),.irq(irq),.board_clk(board_clk),.adc_data(adc_data),.adc_otr(adc_otr),.grounded_pads(grounded_pads),.adc_clk(adc_clk),.adc_oeb(adc_oeb),.adc_pwdn(adc_pwdn));
 always @(posedge clk)begin
  if(!rstn)begin ap<=0;wp<=0;s_axi_bvalid<=0;s_axi_bresp<=0;s_axi_rvalid<=0;s_axi_rdata<=0;s_axi_rresp<=0;read_wait<=0;host_we<=0;host_re<=0;host_addr<=0;host_wdata<=0;end
  else begin
   host_we<=0;host_re<=0;
   if(s_axi_bvalid&&s_axi_bready)s_axi_bvalid<=0;
   if(s_axi_rvalid&&s_axi_rready)s_axi_rvalid<=0;
   if(s_axi_awvalid&&s_axi_awready)begin ap<=1;aw<=s_axi_awaddr;end
   if(s_axi_wvalid&&s_axi_wready)begin wp<=1;wd<=s_axi_wdata;ws<=s_axi_wstrb;end
   if(ap&&wp)begin
    ap<=0;wp<=0;s_axi_bvalid<=1;s_axi_bresp<=ws==15&&aw[1:0]==0?0:2;
    if(ws==15&&aw[1:0]==0)begin host_we<=1;host_addr<=aw;host_wdata<=wd;end
   end
   if(s_axi_arvalid&&s_axi_arready)begin host_re<=1;host_addr<=s_axi_araddr;read_wait<=4;s_axi_rresp<=s_axi_araddr[1:0]==0?0:2;end
   if(read_wait!=0)begin read_wait<=read_wait-1;if(read_wait==1)begin s_axi_rdata<=host_rdata;s_axi_rvalid<=1;end end
  end
 end
endmodule
