`timescale 1ns/1ps
module tb_store;
 logic clk=0;always #5 clk=~clk;logic rstn=0,clear=0,clear_page=0;
 logic [8:0] clear_index=0,resolve_index=0;logic [31:0] background=32'hff000000;
 logic query=0,query_page=0,query_ready,commit=0,commit_page=0,commit_ready,busy;
 logic [9:0] query_index=0,commit_index=0;logic [63:0] queried[0:1],old_pixel[0:1],resolved[0:1];
 logic [1:0] commit_mask=3;logic [15:0] commit_z[0:1],object_id=7;logic [31:0] color[0:1];
 logic sprite=0,resolve=0,resolve_page=1;integer l,n,stalls=0;
 g3_tile_store dut(.*);
 task send_pixel(input logic [31:0] argb,input integer z,id,input logic additive);
  begin commit=1;for(l=0;l<2;l=l+1)begin color[l]=argb;commit_z[l]=z;end object_id=id;sprite=additive;
   do begin @(posedge clk);if(!commit_ready)stalls=stalls+1;end while(!commit_ready);
   @(negedge clk);commit=0;
  end
 endtask
 task read_pixel(input logic [63:0] expected);
  begin query=1;n=0;do begin @(posedge clk);n=n+1;end while(!query_ready&&n<20);
   if(!query_ready)$fatal(1,"query hazard never released");
   @(negedge clk);query=0;
   for(l=0;l<2;l=l+1)begin if(queried[l]!==expected)$fatal(1,"forward/depth/blend got %h expected %h",queried[l],expected);old_pixel[l]=queried[l];end
  end
 endtask
 initial begin
  for(l=0;l<2;l=l+1)begin old_pixel[l]=64'h0000ffff_ff000000;color[l]=0;commit_z[l]=0;end
  repeat(4)@(negedge clk);rstn=1;clear=1;@(negedge clk);clear=0;
  send_pixel(32'h80400000,100,7,0);
  send_pixel(32'h80004000,90,8,0);
  read_pixel(64'h0008005a_ff204000);
  send_pixel(32'hff0000ff,110,9,0);while(busy)@(negedge clk);read_pixel(64'h0008005a_ff204000);
  send_pixel(32'h40000020,80,10,1);while(busy)@(negedge clk);read_pixel(64'h0008005a_ff204020);
  if(stalls==0)$fatal(1,"same-address pipeline conflict was not exercised");
  rstn=0;@(negedge clk);rstn=1;if(busy)$fatal(1,"reset left pending commit");
  $display("TB_STORE_PASS waw_stalls=%d",stalls);$finish;
 end
 initial begin #100000;$fatal(1,"watchdog");end
endmodule
