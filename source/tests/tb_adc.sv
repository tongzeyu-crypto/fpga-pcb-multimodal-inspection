`timescale 1ns/1ps
// Functional clock primitive fixture only; not a physical clock/timing test.
module MMCME2_BASE #(parameter CLKIN1_PERIOD=40.0,DIVCLK_DIVIDE=1,CLKFBOUT_MULT_F=32.0,CLKOUT0_DIVIDE_F=4.0)(input CLKIN1,CLKFBIN,RST,PWRDWN,output CLKFBOUT,CLKOUT0,LOCKED);
 reg fast=0;always #2.5 fast=~fast;assign CLKOUT0=fast;assign CLKFBOUT=fast;assign LOCKED=1'b1;
endmodule
module BUFG(input I,output O);assign O=I;endmodule
module tb_adc;
 reg clk=0,board_clk=0;always #5 clk=~clk;always #20 board_clk=~board_clk;
 reg rstn=0,we=0,re=0;reg [16:0]addr=0;reg [31:0]data=0;wire [31:0]q;wire irq,ac,oe,pdn;
 wire [13:0] adc_data={dut.sequence_fast[1:0],dut.hb};
 pcb_adc_capture dut(.clk(clk),.rstn(rstn),.host_we(we),.host_re(re),.host_addr(addr),.host_wdata(data),.host_rdata(q),.irq(irq),.board_clk(board_clk),.adc_data(adc_data),.adc_otr(1'b0),.grounded_pads(2'b0),.adc_clk(ac),.adc_oeb(oe),.adc_pwdn(pdn));
 task wr(input [16:0]a,input [31:0]v);begin @(negedge clk);addr=a;data=v;we=1;@(negedge clk);we=0;end endtask
 task rd(input [16:0]a,output [31:0]v);begin @(negedge clk);addr=a;re=1;@(negedge clk);re=0;@(negedge clk);v=q;end endtask
 reg [31:0]v,old,again;integer i,n;reg [11:0] hb;reg [1:0] phase;
 initial begin
  repeat(10)@(negedge clk);rstn=1;repeat(10)@(negedge clk);rd(8,v);if(v!==32'h50414432)$fatal(1,"ADC ABI");
  rd(24,v);if(v!=2)$fatal(1,"two frame banks required");
  wr(0,1);wr(0,1);rd(4,v);if(!v[2]||!v[0])$fatal(1,"overrun not latched");
  while(!irq)@(negedge clk);rd(12,v);if(v!=1)$fatal(1,"generation");
  for(i=0;i<16384;i=i+1)begin rd(17'h10000+i*4,v);
   if(!v[19]||v[18:17]!=0||v[14])$fatal(1,"raw flags");
   if(v[13:0]!={2'b0,v[31:20]})$fatal(1,"data pattern");
   if(i>0&&((v[31:20]-hb)&4095)!=1)$fatal(1,"heartbeat");
   if(i>0&&((v[16:15]-phase)&3)!=1)$fatal(1,"phase");hb=v[31:20];phase=v[16:15];if(i==37)old=v;
  end
  rd(17'h10000+37*4,again);if(old!==again)$fatal(1,"frozen frame changed");
  rd(52,old);rd(60,again);if(again-old!=16383)$fatal(1,"sample clock timestamps");
  wr(36,1);repeat(10)@(negedge clk);wr(40,1);wr(0,1);
  rd(28,v);while(v!=3)rd(28,v);
  rd(12,v);if(v!=3)$fatal(1,"two prefetched generations");
  wr(32,0);rd(17'h10000+37*4,old);if(old[13:12]!=1)$fatal(1,"bank0 frame generation");
  repeat(100)@(negedge clk);rd(17'h10000+37*4,again);if(old!==again)$fatal(1,"full banks overwritten");
  wr(32,1);rd(17'h10000+37*4,old);if(old[13:12]!=2)$fatal(1,"bank1 frame generation");
  wr(36,1);repeat(20)@(negedge clk);
  rd(4,v);if(!v[4]||!dut.capturing)$fatal(1,"producer must fill free bank while PS owns other bank");
  rd(17'h10000+37*4,again);if(old!==again)$fatal(1,"owned bank changed during other capture");
  rd(28,v);while(v!=3)rd(28,v);
  rd(12,v);if(v!=4)$fatal(1,"third prefetched generation");
  rd(17'h10000+37*4,again);if(old!==again)$fatal(1,"bank1 retention");
  wr(32,0);rd(17'h10000+37*4,v);if(v[13:12]!=3)$fatal(1,"reused bank0 must contain new frame");
  wr(0,2);repeat(20)@(negedge clk);wr(36,3);rd(28,v);if(v!=0)$fatal(1,"acknowledgement did not release banks");
  $display("ADC_PASS words=16384 banks=2 ownership=1 producer_consumer_overlap=1 backpressure=1 generations=4 behavioral_clock_only=1");$finish;
 end
 initial begin #3000000;$fatal(1,"ADC watchdog");end
endmodule
