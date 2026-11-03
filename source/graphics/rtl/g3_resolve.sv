// Synchronous BRAM reading overlaps retirement of the previous pair.
// Streams one completed tile directly to compact frame/ID/thumbnail planes.
module g3_resolve(input logic clk,rstn,start,input logic page,
 input logic [5:0] tile_x,tile_y,input logic [11:0] width,height,
 input logic [31:0] frame_base,object_base,thumbnail_base,depth_base,input logic make_thumbnail,make_depth,
 output logic ready,done,error,output logic read_tile,read_page,
 output logic [8:0] read_index,input logic [63:0] tile_pixel[0:1],
 output g3_pkg::wr_req_t wr,input logic wr_ready,output g3_pkg::wr_data_t wd,
 input logic wd_ready,wr_done,wr_error);
 import g3_pkg::*;
 typedef enum logic [4:0]{IDLE,READ_ROW,WAIT_PIXEL,FRAME_REQ,FRAME_DATA,FRAME_ACK,
  ID_REQ,ID_DATA,ID_ACK,THUMB_REQ,THUMB_DATA,THUMB_ACK,NEXT_ROW,FINISH,DEPTH_REQ,DEPTH_DATA,DEPTH_ACK} state_t;
 state_t state;logic current_page;logic [5:0] tx,ty,row;
 logic [4:0] pair,beat;
 logic [63:0] colors[0:15],objects[0:7],thumb[0:7];
 (* ram_style="registers" *) logic [63:0] depths[0:7];
 logic [35:0] previous_sum[0:15];
 logic [8:0] sum_now[0:3];logic [9:0] total;integer c;
 logic thumb_pending,thumb_odd;logic [4:0] thumb_pair;logic [35:0] thumb_sum,thumb_prior;
 logic [31:0] pixel_offset,thumb_offset;
 logic [10:0] source_y;logic [22:0] row_pixels,row_thumbs;
 logic [31:0] frame_address,object_address,thumbnail_address,depth_address;
 assign ready=state==IDLE;
 always_comb begin
  read_tile=state==READ_ROW||(state==WAIT_PIXEL&&pair<15);read_page=current_page;
  read_index={row[4:0],pair[3:0]+(state==WAIT_PIXEL?4'd1:4'd0)};
  wr.valid=state==FRAME_REQ||state==ID_REQ||state==THUMB_REQ||state==DEPTH_REQ;
  wr.addr=state==FRAME_REQ?frame_address:state==ID_REQ?object_address:state==DEPTH_REQ?depth_address:thumbnail_address;
  wr.beats=state==FRAME_REQ?16:8;
  wd.valid=state==FRAME_DATA||state==ID_DATA||state==THUMB_DATA||state==DEPTH_DATA;
  wd.data=state==FRAME_DATA?colors[beat]:state==ID_DATA?objects[beat]:state==DEPTH_DATA?depths[beat]:thumb[beat];wd.strb=8'hff;
  for(integer cc=0;cc<4;cc=cc+1)sum_now[cc]={1'b0,tile_pixel[0][cc*8+:8]}+{1'b0,tile_pixel[1][cc*8+:8]};
 end
 // Separate BRAM -> horizontal sum from vertical average/RAM write.
 // The delayed thumbnail commit overlaps READ_ROW/FRAME_REQ; no extra FSM
 // cycle is added, and all thumbnail words commit long before THUMB_REQ.
 always_ff @(posedge clk)begin
  if(!rstn)thumb_pending<=0;
  else begin
   thumb_pending<=state==WAIT_PIXEL&&!wr_error;
   if(state==WAIT_PIXEL&&!wr_error)begin
    thumb_pair<=pair;thumb_odd<=row[0];thumb_prior<=previous_sum[pair];
    for(integer tc=0;tc<4;tc=tc+1)thumb_sum[tc*9+:9]<=sum_now[tc];
   end
   if(thumb_pending&&!wr_error)begin
    for(c=0;c<4;c=c+1)begin
     if(!thumb_odd)previous_sum[thumb_pair][c*9+:9]<=thumb_sum[c*9+:9];
     else begin total={1'b0,thumb_prior[c*9+:9]}+thumb_sum[c*9+:9]+2;
      thumb[thumb_pair>>1][thumb_pair[0]*32+c*8+:8]<=total>>2;end
    end
   end
  end
 end
 always_ff @(posedge clk)begin
  // Row addresses settle while the 16 source pairs are read. Each product is
  // limited to its actual unsigned width, then base addresses are registered.
  source_y<={ty,5'b0}+row;
  row_pixels<=source_y*width;row_thumbs<=source_y[10:1]*(width>>1);
  pixel_offset<=row_pixels+{tx,5'b0};thumb_offset<=row_thumbs+{tx,4'b0};
  frame_address<=frame_base+(pixel_offset<<2);object_address<=object_base+(pixel_offset<<1);
  depth_address<=depth_base+(pixel_offset<<1);
  thumbnail_address<=thumbnail_base+(thumb_offset<<2);
  if(!rstn)begin state<=IDLE;done<=0;error<=0;end
  else begin done<=0;
   if(wr_error)begin error<=1;state<=FINISH;end
   else case(state)
    IDLE:if(start)begin current_page<=page;tx<=tile_x;ty<=tile_y;row<=0;pair<=0;error<=0;state<=READ_ROW;end
    READ_ROW:state<=WAIT_PIXEL;
    WAIT_PIXEL:begin
     colors[pair]<={tile_pixel[1][31:0],tile_pixel[0][31:0]};
     depths[pair>>1][pair[0]*32+:32]<={tile_pixel[1][47:32],tile_pixel[0][47:32]};
     objects[pair>>1][pair[0]*32+:32]<={tile_pixel[1][63:48],tile_pixel[0][63:48]};

     if(pair==15)begin beat<=0;state<=FRAME_REQ;end else begin pair<=pair+1;state<=WAIT_PIXEL;end
    end
    FRAME_REQ:if(wr_ready)begin beat<=0;state<=FRAME_DATA;end
    FRAME_DATA:if(wd_ready)begin beat<=beat+1;if(beat==15)state<=FRAME_ACK;end
    FRAME_ACK:if(wr_done)state<=ID_REQ;
    ID_REQ:if(wr_ready)begin beat<=0;state<=ID_DATA;end
    ID_DATA:if(wd_ready)begin beat<=beat+1;if(beat==7)state<=ID_ACK;end
    ID_ACK:if(wr_done)state<=make_depth?DEPTH_REQ:make_thumbnail&&row[0]?THUMB_REQ:NEXT_ROW;
    DEPTH_REQ:if(wr_ready)begin beat<=0;state<=DEPTH_DATA;end
    DEPTH_DATA:if(wd_ready)begin beat<=beat+1;if(beat==7)state<=DEPTH_ACK;end
    DEPTH_ACK:if(wr_done)state<=make_thumbnail&&row[0]?THUMB_REQ:NEXT_ROW;
    THUMB_REQ:if(wr_ready)begin beat<=0;state<=THUMB_DATA;end
    THUMB_DATA:if(wd_ready)begin beat<=beat+1;if(beat==7)state<=THUMB_ACK;end
    THUMB_ACK:if(wr_done)state<=NEXT_ROW;
    NEXT_ROW:if(row==31||(ty<<5)+row+1>=height)state<=FINISH;
     else begin row<=row+1;pair<=0;state<=READ_ROW;end
    FINISH:begin done<=1;state<=IDLE;end
    default:state<=IDLE;
   endcase
  end
 end
endmodule
