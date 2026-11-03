// One descriptor lookahead. Reference line retained across adjacent tile bins.
module g3_bin_reader(input logic clk,rstn,start,invalidate,input logic [9:0] tile,
 input logic [31:0] bin_base,geometry_base,geometry_count,
 output logic valid,input logic ready,output logic last,complete,error,
 output logic [1023:0] descriptor,
 output g3_pkg::rd_req_t rd,input logic rd_ready,
 input g3_pkg::rd_rsp_t rsp,output logic rsp_ready);
 import g3_pkg::*;
 typedef enum logic [3:0]{IDLE,HEADER_REQ,HEADER_DATA,REF_CHECK,REF_REQ,REF_DATA,
  REF_SELECT,DESC_REQ,DESC_DATA,OUTPUT,FINISH} state_t;
 state_t state;logic [31:0] offset,count,position,index,ref_address,cache_tag;
 logic cache_valid;logic [63:0] cache[0:15];logic [4:0] beat;
 logic [9:0] tile_id;
 always_comb begin
  ref_address=bin_base+16384+((offset+position)<<2);
  rd.valid=state==HEADER_REQ||state==REF_REQ||state==DESC_REQ;
  rd.addr=state==HEADER_REQ?bin_base+(tile_id<<4):state==REF_REQ?{ref_address[31:7],7'b0}:geometry_base+(index<<7);
  rd.token=0;rd.beats=state==HEADER_REQ?2:16;
  rsp_ready=state==HEADER_DATA||state==REF_DATA||state==DESC_DATA;
  valid=state==OUTPUT;last=position+1==count;
 end
 always_ff @(posedge clk)begin
  if(!rstn)begin state<=IDLE;complete<=0;error<=0;cache_valid<=0;end
  else begin if(invalidate)cache_valid<=0;case(state)
   IDLE:if(start)begin tile_id<=tile;position<=0;complete<=0;error<=0;state<=HEADER_REQ;end
   HEADER_REQ:if(rd_ready)begin beat<=0;state<=HEADER_DATA;end
   HEADER_DATA:if(rsp.valid)begin
    if(beat==0)begin offset<=rsp.data[31:0];count<=rsp.data[63:32];end
    beat<=beat+1;if(rsp.error||rsp.last!=(beat==1))begin error<=1;state<=FINISH;end
    else if(rsp.last)state<=count==0?FINISH:REF_CHECK;
   end
   REF_CHECK:if(cache_valid&&cache_tag=={ref_address[31:7],7'b0})state<=REF_SELECT;else state<=REF_REQ;
   REF_REQ:if(rd_ready)begin beat<=0;state<=REF_DATA;end
   REF_DATA:if(rsp.valid)begin
    cache[beat]<=rsp.data;beat<=beat+1;
    if(rsp.error||rsp.last!=(beat==15))begin error<=1;state<=FINISH;end
    else if(rsp.last)begin cache_valid<=1;cache_tag<={ref_address[31:7],7'b0};state<=REF_SELECT;end
   end
   REF_SELECT:begin index<=ref_address[2]?cache[ref_address[6:3]][63:32]:cache[ref_address[6:3]][31:0];state<=DESC_REQ;end
   DESC_REQ:if(index>=geometry_count)begin error<=1;state<=FINISH;end
    else if(rd_ready)begin beat<=0;state<=DESC_DATA;end
   DESC_DATA:if(rsp.valid)begin
    descriptor[beat*64+:64]<=rsp.data;beat<=beat+1;
    if(rsp.error||rsp.last!=(beat==15))begin error<=1;state<=FINISH;end
    else if(rsp.last)state<=OUTPUT;
   end
   OUTPUT:if(ready)begin if(last)state<=FINISH;else begin position<=position+1;state<=REF_CHECK;end end
   FINISH:begin complete<=1;state<=IDLE;end
   default:state<=IDLE;
  endcase end
 end
endmodule
