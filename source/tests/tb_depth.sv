`timescale 1ns/1ps
module tb_depth;
 import g3_pkg::*;
 reg clk=0;always #5 clk=~clk;
 reg rstn=0,start=0,enable=1;wire ready,done,error,re,rpage;wire [8:0] index;
 logic [63:0] pixel[0:1];wr_req_t wr;wr_data_t wd;reg wready=0,dready=0,wdone=0;
 integer tick=0,beats=0,seen=0,depth_words=0,total_depth=0,frames=0;reg active=0,pending_ack=0;reg [31:0] addr;
 g3_resolve dut(.clk(clk),.rstn(rstn),.start(start),.page(1'b0),.tile_x(6'd0),.tile_y(6'd22),.width(12'd1280),.height(12'd720),.frame_base(32'h100000),.object_base(32'h500000),.thumbnail_base(32'h700000),.depth_base(32'h900000),.make_thumbnail(1'b0),.make_depth(enable),.ready(ready),.done(done),.error(error),.read_tile(re),.read_page(rpage),.read_index(index),.tile_pixel(pixel),.wr(wr),.wr_ready(wready),.wd(wd),.wd_ready(dready),.wr_done(wdone),.wr_error(1'b0));
 integer row,b,k;reg [15:0] expected;
 always @(posedge clk)begin
  tick<=tick+1;wready<=!active&&!pending_ack&&(tick%3!=0);dready<=active&&(tick%4!=0);wdone<=0;
  if(re)begin pixel[0]<={16'h1234,{index,1'b0},6'b0,32'hffabcdef};pixel[1]<={16'h5678,{index,1'b0},6'b0,32'hff123456};
   pixel[0][47:32]<={6'b0,index,1'b0};pixel[1][47:32]<={6'b0,index,1'b1};end
  if(wr.valid&&wready)begin active<=1;addr<=wr.addr;beats<=wr.beats;seen<=0;wready<=0;end
  if(wd.valid&&dready)begin
   if(addr>=32'h900000)begin
    row=(addr-32'h900000)/2560-704;
    if(row<0||row>15)$fatal(1,"depth address row");
    for(k=0;k<4;k=k+1)begin expected=row*32+seen*4+k;if(wd.data[k*16+:16]!==expected)$fatal(1,"depth payload row=%0d beat=%0d lane=%0d got=%h want=%h",row,seen,k,wd.data[k*16+:16],expected);end
    depth_words<=depth_words+1;total_depth<=total_depth+1;
   end
   seen<=seen+1;if(seen==beats-1)begin active<=0;pending_ack<=1;dready<=0;end
  end
  if(pending_ack)begin pending_ack<=0;wdone<=1;end
 end
 initial begin
  repeat(5)@(negedge clk);rstn=1;@(negedge clk);start=1;@(negedge clk);start=0;
  while(!done)@(negedge clk);if(error||depth_words!=128)$fatal(1,"depth count %0d",depth_words);
  @(negedge clk);enable=0;depth_words=0;start=1;@(negedge clk);start=0;
  while(!done)@(negedge clk);if(error||depth_words!=0)$fatal(1,"legacy depth disabled");
  $display("DEPTH_PASS words=%0d partial_rows=16 legacy_compatible=1",total_depth);$finish;
 end
 initial begin #2000000;$fatal(1,"depth watchdog");end
endmodule
