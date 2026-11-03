`timescale 1ns/1ps
module tb_cache_dual;
 import g3_pkg::*;logic clk=0;always #5 clk=~clk;logic rstn=0,invalidate=0,in_valid=0,in_ready,out_valid,out_ready=0,error;
 logic [31:0] address[0:7],sampled[0:7];rd_req_t req;rd_rsp_t rsp;logic req_ready,rsp_ready;logic [63:0] misses,stall_cycles,request_wait,first_return_wait,bank_conflict_wait;
 logic [1:0] pending=0;logic [31:0] base[0:1];integer beats[0:1];integer tick=0,requests=0,max_pending=0,selected=0,i;
 g3_tex_cache #(.CACHE_BYTES(4096)) dut(.*);
 always @(negedge clk)begin tick=tick+1;req_ready=tick%3!=0;rsp='0;
  if(pending==3)max_pending=2;
  if(pending!=0&&tick%4!=0&&(requests%2==0||tick%19==0))begin selected=pending[1]?1:0;rsp.valid=1;rsp.token=selected;rsp.last=beats[selected]==15;
   rsp.data={((base[selected]+beats[selected]*8+4)^32'h5a55a500),((base[selected]+beats[selected]*8)^32'h5a55a500)};end
 end
 always @(posedge clk)begin
  if(req.valid&&req_ready)begin if(pending[req.token])$fatal(1,"slot reused while active");pending[req.token]<=1;base[req.token]<=req.addr;beats[req.token]<=0;requests<=requests+1;end
  if(rsp.valid&&rsp_ready)begin beats[rsp.token]<=beats[rsp.token]+1;if(rsp.last)pending[rsp.token]<=0;end
 end
 task sample_pair(input integer a,input integer b);
  begin @(negedge clk);for(i=0;i<8;i=i+1)address[i]=(i<4?a:b)+(i%4)*4;
   in_valid=1;while(!in_ready)@(negedge clk);@(negedge clk);in_valid=0;while(!out_valid)@(negedge clk);
   repeat(7)begin for(i=0;i<8;i=i+1)if(sampled[i]!=(address[i]^32'h5a55a500))$fatal(1,"dual fill sample mismatch %0d %h",i,sampled[i]);@(negedge clk);end
   if(error)$fatal(1,"cache error");out_ready=1;@(negedge clk);out_ready=0;
  end
 endtask
 initial begin repeat(5)@(negedge clk);rstn=1;
  sample_pair('h10000,'h10800);sample_pair('h10000,'h10800);sample_pair('h11000,'h11200);
  if(max_pending!=2)$fatal(1,"no two outstanding requests observed");
  invalidate=1;@(negedge clk);invalidate=0;sample_pair('h10000,'h10800);
  rstn=0;repeat(3)@(negedge clk);pending=0;rstn=1;sample_pair('h10000,'h10800);
  $display("TB_CACHE_DUAL_PASS requests=%0d max_pending=%0d",requests,max_pending);$finish;
 end
 initial begin #2000000;$fatal(1,"watchdog");end
endmodule
