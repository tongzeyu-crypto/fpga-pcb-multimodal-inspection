`timescale 1ns/1ps
module tb_ai;
 reg clk=0;always #5 clk=~clk;
 reg rstn=0;reg [17:0] aw=0,ar=0;reg av=0,wv=0,br=0,rv=0,rr=0;
 wire aready,wready,bvalid,arready,rvalid,irq;reg [31:0] wd=0;wire [31:0] rd;wire [1:0] bp,rp;
 pcb_ai_axi dut(.clk(clk),.rstn(rstn),.s_axi_awaddr(aw),.s_axi_awvalid(av),.s_axi_awready(aready),.s_axi_wdata(wd),.s_axi_wstrb(4'hf),.s_axi_wvalid(wv),.s_axi_wready(wready),.s_axi_bresp(bp),.s_axi_bvalid(bvalid),.s_axi_bready(br),.s_axi_araddr(ar),.s_axi_arvalid(rv),.s_axi_arready(arready),.s_axi_rdata(rd),.s_axi_rresp(rp),.s_axi_rvalid(rvalid),.s_axi_rready(rr),.irq(irq));
 `include "command_count.vh"
 reg [31:0] commands[0:COMMAND_WORDS-1];integer pc,checks=0,cases=0,reads=0,writes=0,waits;reg [31:0] got,held;
 task write_reg(input [17:0] addr,input [31:0] val);
  begin
   // Alternate AW-first and W-first transactions, hold responses under stalls.
   if(writes%2==0)begin
    @(negedge clk);aw=addr;av=1;do @(posedge clk);while(!aready);@(negedge clk);av=0;
    repeat(writes%3)@(negedge clk);wd=val;wv=1;do @(posedge clk);while(!wready);@(negedge clk);wv=0;
   end else begin
    @(negedge clk);wd=val;wv=1;do @(posedge clk);while(!wready);@(negedge clk);wv=0;
    repeat(writes%3)@(negedge clk);aw=addr;av=1;do @(posedge clk);while(!aready);@(negedge clk);av=0;
   end
   while(!bvalid)@(negedge clk);
   repeat(writes%3)begin @(negedge clk);if(!bvalid)$fatal(1,"BVALID stall");end
   if(bp!=0)$fatal(1,"write error");br=1;@(negedge clk);br=0;writes=writes+1;
  end
 endtask
 task read_reg(input [17:0] addr,output [31:0] value);
  begin
   @(negedge clk);ar=addr;rv=1;do @(posedge clk);while(!arready);@(negedge clk);rv=0;
   while(!rvalid)@(negedge clk);held=rd;
   repeat(reads%3)begin @(negedge clk);if(!rvalid||rd!==held)$fatal(1,"R stall");end
   if(rp!=0)$fatal(1,"read error");value=rd;rr=1;@(negedge clk);rr=0;reads=reads+1;
  end
 endtask
 initial begin
  $readmemh("commands.hex",commands);repeat(6)@(negedge clk);rstn=1;
  read_reg(8,got);if(got!==32'h50414931)$fatal(1,"ABI");
  for(pc=0;pc<COMMAND_WORDS;pc=pc+3)case(commands[pc])
   0:begin $display("ALL_AI_PASS cases=%0d checked_elements=%0d writes=%0d reads=%0d",cases,checks,writes,reads);$finish;end
   1:write_reg(commands[pc+1],commands[pc+2]);
   2:begin read_reg(commands[pc+1],got);if(got!==commands[pc+2])$fatal(1,"Mismatch pc=%0d addr=%h expected=%h got=%h",pc,commands[pc+1],commands[pc+2],got);checks=checks+1;end
   3:begin waits=0;got=1;while(got[0]&&waits<2000000)begin repeat(16)@(negedge clk);read_reg(4,got);waits=waits+1;end
    if(got[2]||!got[1]||waits==2000000)$fatal(1,"Task failed status=%h",got);end
   4:begin cases=cases+1;read_reg(64,got);$display("LAYER_PASS index=%0d cycles=%0d",commands[pc+1],got);end
   5:begin
    // An invalid descriptor must fail, reset must recover; abort busy work.
    write_reg(0,2);write_reg(16,0);write_reg(0,1);read_reg(4,got);if(!got[2])$fatal(1,"Invalid length accepted");
    write_reg(0,2);read_reg(4,got);if(got!==0)$fatal(1,"Reset status");
    write_reg(16,7);write_reg(0,1);repeat(20)@(negedge clk);write_reg(0,2);read_reg(4,got);if(got!==0)$fatal(1,"Abort status");
   end
   default:$fatal(1,"command");
  endcase
  $fatal(1,"No end marker");
 end
 initial begin #2000000000;$fatal(1,"Global watchdog");end
endmodule
