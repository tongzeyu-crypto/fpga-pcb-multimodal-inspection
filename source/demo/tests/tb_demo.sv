`timescale 1ns/1ps
module tb_demo;
 reg clk=0;always #8 clk=~clk;reg rstn=0;
 reg [15:0] s_axi_awaddr=0,s_axi_araddr=0;reg s_axi_awvalid=0,s_axi_wvalid=0,s_axi_bready=0,s_axi_arvalid=0,s_axi_rready=0;
 reg [31:0] s_axi_wdata=0;reg [3:0] s_axi_wstrb=15;
 wire s_axi_awready,s_axi_wready,s_axi_bvalid,s_axi_arready,s_axi_rvalid,irq;
 wire [1:0] s_axi_bresp,s_axi_rresp;wire [31:0] s_axi_rdata;
 pcb_demo_axi dut(.*);
 `include "fixture_count.svh"
 reg [31:0] commands[0:131071];integer step,attempts,fd;reg [31:0] value,held;
 task aw(input [15:0] address);begin
  @(negedge clk);s_axi_awaddr=address;s_axi_awvalid=1;do @(posedge clk);while(!s_axi_awready);@(negedge clk);s_axi_awvalid=0;
 end endtask
 task wd(input [31:0] data);begin
  @(negedge clk);s_axi_wdata=data;s_axi_wvalid=1;do @(posedge clk);while(!s_axi_wready);@(negedge clk);s_axi_wvalid=0;
 end endtask
 task wr(input [15:0] address,input [31:0] data);begin
  if(step%2)begin wd(data);repeat(2)@(negedge clk);aw(address);end else begin aw(address);repeat(2)@(negedge clk);wd(data);end
  wait(s_axi_bvalid);repeat(2)@(negedge clk);if(s_axi_bresp)$fatal(1,"AXI write error");s_axi_bready=1;@(negedge clk);s_axi_bready=0;
 end endtask
 task rd(input [15:0] address,output [31:0] data);begin
  @(negedge clk);s_axi_araddr=address;s_axi_arvalid=1;do @(posedge clk);while(!s_axi_arready);@(negedge clk);s_axi_arvalid=0;
  wait(s_axi_rvalid);held=s_axi_rdata;
  repeat(2)begin @(negedge clk);if(!s_axi_rvalid||s_axi_rdata!==held)$fatal(1,"AXI stalled output changed");end
  if(s_axi_rresp)$fatal(1,"AXI read error");data=s_axi_rdata;s_axi_rready=1;@(negedge clk);s_axi_rready=0;
 end endtask
 initial begin
  $readmemh("commands.mem",commands,0,TOTAL*3-1);if((^commands[TOTAL*3-1])===1'bx)$fatal(1,"fixture missing");
  fd=$fopen("actual.txt","w");repeat(4)@(negedge clk);rstn=1;
  for(step=0;step<TOTAL;step=step+1)case(commands[step*3])
   1:wr(commands[step*3+1],commands[step*3+2]);
   2:begin rd(commands[step*3+1],value);$fdisplay(fd,"%08x %08x",step,value);if(value!==commands[step*3+2])$fatal(1,"read mismatch step=%0d address=%h got=%h expected=%h",step,commands[step*3+1],value,commands[step*3+2]);end
   3:begin
    attempts=0;value=1;
    while(value[0])begin rd(4,value);attempts=attempts+1;if(attempts>2000||value[2])$fatal(1,"job timeout/error %h",value);end
    if(value!=2||!irq)$fatal(1,"completion/IRQ missing");
   end
   4:repeat(commands[step*3+2])@(negedge clk);
   5:begin rstn=0;repeat(3)@(negedge clk);rstn=1;repeat(2)@(negedge clk);end
   default:$fatal(1,"bad fixture opcode");
  endcase
  $fclose(fd);$display("PL_PS_DEMO_RTL_PASS commands=%0d",TOTAL);$finish;
 end
 initial begin #100000000;$fatal(1,"watchdog");end
endmodule
