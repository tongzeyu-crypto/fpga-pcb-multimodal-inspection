`timescale 1ns/1ps
module tb_store_stream;
 logic clk=0;always #5 clk=~clk;logic rstn=0,clear=0,clear_page=0;
 logic [8:0] clear_index=0,resolve_index=0;logic [31:0] background=32'hff182838;
 logic query=0,query_page=0,query_ready,commit=0,commit_page=0,commit_ready,busy;
 logic [9:0] query_index=0,commit_index=0;logic [63:0] queried[0:1],old_pixel[0:1],resolved[0:1];
 logic [1:0] commit_mask=0;logic [15:0] commit_z[0:1],object_id=0;logic [31:0] color[0:1];
 logic sprite=0,resolve=0,resolve_page=0;
 logic [31:0] inputs[0:53247],expected[0:4095];integer n,l,p,stalls=0;
 g3_tile_store dut(.*);
 initial begin
  for(integer product=0;product<=65025;product=product+1)if(dut.blend_div255(product)!==g3_pkg::div255(product))$fatal(1,"blend rounding product=%0d",product);
  $readmemh("sim/store-input.mem",inputs);$readmemh("sim/store-expected.mem",expected);
  if((^inputs[0]===1'bx)||(^expected[4095]===1'bx))$fatal(1,"missing reference vectors");
  for(l=0;l<2;l=l+1)begin old_pixel[l]=0;commit_z[l]=0;color[l]=0;end
  repeat(25)@(negedge clk);rstn=1;
  for(p=0;p<2;p=p+1)begin
   for(n=0;n<512;n=n+1)begin clear=1;clear_page=p;clear_index=n;@(negedge clk);end
  end
  clear=0;
  for(n=0;n<4096;n=n+1)begin
   commit_page=inputs[n*13];commit_index=inputs[n*13+1];commit_mask=inputs[n*13+2];sprite=inputs[n*13+3];object_id=inputs[n*13+4];
   commit_z[0]=inputs[n*13+5];commit_z[1]=inputs[n*13+6];color[0]=inputs[n*13+7];color[1]=inputs[n*13+8];
   old_pixel[0]={inputs[n*13+10],inputs[n*13+9]};old_pixel[1]={inputs[n*13+12],inputs[n*13+11]};commit=1;
   do begin @(posedge clk);if(!commit_ready)stalls=stalls+1;end while(!commit_ready);
   @(negedge clk);commit=0;
  end
  while(busy)@(negedge clk);repeat(3)@(negedge clk);
  for(p=0;p<1024;p=p+1)begin
   query=1;query_page=p/512;query_index=(p%512)*2;@(posedge clk);
   if(!query_ready)$fatal(1,"unexpected drained query stall");
   @(negedge clk);query=0;
   for(l=0;l<2;l=l+1)if(queried[l]!=={expected[p*4+l*2+1],expected[p*4+l*2]})$fatal(1,"storage mismatch pair=%0d lane=%0d actual=%h expected=%h",p,l,queried[l],{expected[p*4+l*2+1],expected[p*4+l*2]});
  end
  if(stalls==0)$fatal(1,"same-address hazard not exercised");
  $display("TB_STORE_STREAM_PASS commits=4096 pixels=2048 waw_stalls=%0d color_depth_id=exact",stalls);$finish;
 end
 initial begin #10000000;$fatal(1,"watchdog");end
endmodule
