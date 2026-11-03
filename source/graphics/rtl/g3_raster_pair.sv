`default_nettype none
// Two adjacent pixels/handshake, Q12.4 coverage, exact shared-edge_value convention.
module g3_raster_pair(input wire logic clk,rstn,start,input wire logic [1023:0] descriptor,
 input wire logic [11:0] width,height,input wire logic [5:0] tile_x,tile_y,
 output logic ready,done,valid,input wire logic accept,output logic [1:0] mask,
 output logic [9:0] index,output logic [15:0] z[0:1],u[0:1],v[0:1]);
 import g3_pkg::*;
 typedef enum logic [3:0]{IDLE,BOUNDS,INITIALIZE,MULTIPLY,SUM,PIXELS,FINISH,SKIP_APPLY,MULTIPLY_Y} state_t;
 state_t state;
 logic signed [15:0] x[0:2],y[0:2],xs,ys,xe,ye,px,py;
 logic signed [31:0] gx[0:2],gy[0:2];logic [15:0] origin[0:2];
 logic signed [34:0] edge_value[0:2],row_edge[0:2];
 logic signed [47:0] value[0:2],row_value[0:2];
 logic signed [48:0] ix[0:2],iy[0:2];logic signed [33:0] ea[0:2],eb[0:2];
 // Initialization only: reuse X/Y multipliers on adjacent clocks. Pixel
 // stepping remains one adjacent pair per clock; no precision is removed.
 (* use_dsp="yes" *) logic signed [48:0] gradient_product[0:2];
 (* use_dsp="yes" *) logic signed [33:0] edge_product[0:2];
 logic signed [16:0] dx[0:2],dy[0:2],ax[0:2],ay[0:2],vx,vy;
 generate for(genvar m=0;m<3;m=m+1)begin
  assign iy[m]=gradient_product[m];assign eb[m]=edge_product[m];
  always_ff @(posedge clk)if(state==MULTIPLY||state==MULTIPLY_Y)begin
   gradient_product[m]<=(state==MULTIPLY?gx[m]:gy[m])*(state==MULTIPLY?vx:vy);
   edge_product[m]<=(state==MULTIPLY?dx[m]:dy[m])*(state==MULTIPLY?ay[m]:ax[m]);
  end
 end endgenerate
 logic signed [49:0] initial_delta[0:2];
 integer i,l;logic inclusive[0:2];logic signed [34:0] test_edge;
 logic [2:0] step_log,next_step,saved_step;logic [5:0] step_pixels;
 logic [5:0] skip;logic signed [34:0] x_delta[0:2],block_edge;
 assign ready=state==IDLE;
 always_comb begin
  mask=0;
  skip=0;
  for(integer ci=0;ci<3;ci=ci+1)initial_delta[ci]=$signed({ix[ci][48],ix[ci]})+$signed({iy[ci][48],iy[ci]});
  for(integer cl=0;cl<2;cl=cl+1)begin
   // px is an aligned pair already inside this 32-pixel row. Only the
   // second lane can cross xe; avoid a 32-bit add/compare on query enable.
   mask[cl]=cl==0||px[4:0]<xe[4:0];
   for(integer ci=0;ci<3;ci=ci+1)begin
    test_edge=edge_value[ci]-(cl?($signed(dy[ci])<<<4):0);
    if(test_edge<0||(test_edge==0&&!inclusive[ci]))mask[cl]=0;
   end
   z[cl]=sat16((value[0]+(cl?gx[0]:0))>>>8);
   u[cl]=sat16((value[1]+(cl?gx[1]:0))>>>8);
   v[cl]=sat16((value[2]+(cl?gx[2]:0))>>>8);
  end
  valid=state==PIXELS&&mask!=0;index={py[4:0],px[4:0]};
  // A linear half-plane which excludes both ends excludes every sample
  // between them. Test the conservative x+K endpoint, not a guessed span.
  for(integer distance=2;distance<=5;distance=distance+1)begin
   for(integer ci=0;ci<3;ci=ci+1)begin
    block_edge=edge_value[ci]+(x_delta[ci]<<<distance);
    if((edge_value[ci]<0||(edge_value[ci]==0&&!inclusive[ci]))&&
       (block_edge<0||(block_edge==0&&!inclusive[ci])))skip[distance]=1;
   end
  end
  next_step=1;
  for(integer distance=2;distance<=5;distance=distance+1)
   if(skip[distance]&&((6'd1<<distance)-1)<=({1'b0,xe[4:0]}-{1'b0,px[4:0]}))next_step=distance;
  step_log=state==SKIP_APPLY?saved_step:3'd1;
  step_pixels=6'd1<<step_log;
 end
 always_ff @(posedge clk)begin
  if(!rstn)begin state<=IDLE;done<=0;end
  else begin done<=0;case(state)
   IDLE:if(start)begin
    for(i=0;i<3;i=i+1)begin
     x[i]<=descriptor[(4+i*2)*32+:16];y[i]<=descriptor[(5+i*2)*32+:16];
     origin[i]<=descriptor[(10+i)*32+:16];
     gx[i]<=$signed(descriptor[(13+i*2)*32+:32]);gy[i]<=$signed(descriptor[(14+i*2)*32+:32]);
    end
    xs<=($signed(descriptor[19*32+:32])>$signed({1'b0,tile_x,5'b0})?descriptor[19*32+:32]:{tile_x,5'b0})&16'hfffe;
    ys<=$signed(descriptor[21*32+:32])>$signed({1'b0,tile_y,5'b0})?descriptor[21*32+:32]:{tile_y,5'b0};
    xe<=$signed(descriptor[20*32+:32])<$signed({1'b0,tile_x,5'b11111})?descriptor[20*32+:32]:{tile_x,5'b11111};
    ye<=$signed(descriptor[22*32+:32])<$signed({1'b0,tile_y,5'b11111})?descriptor[22*32+:32]:{tile_y,5'b11111};state<=BOUNDS;
   end
   BOUNDS:if(xs>xe||ys>ye)state<=FINISH;else state<=INITIALIZE;
   INITIALIZE:begin
    px<=xs;py<=ys;vx<=($signed(xs)<<<4)+8-$signed(x[0]);vy<=($signed(ys)<<<4)+8-$signed(y[0]);
    for(i=0;i<3;i=i+1)begin
     dx[i]<=$signed(x[(i+2)%3])-$signed(x[(i+1)%3]);dy[i]<=$signed(y[(i+2)%3])-$signed(y[(i+1)%3]);
     ax[i]<=($signed(xs)<<<4)+8-$signed(x[(i+1)%3]);ay[i]<=($signed(ys)<<<4)+8-$signed(y[(i+1)%3]);
     inclusive[i]<=y[(i+2)%3]<y[(i+1)%3]||(y[(i+2)%3]==y[(i+1)%3]&&x[(i+2)%3]>x[(i+1)%3]);
    end state<=MULTIPLY;
   end
   MULTIPLY:begin for(i=0;i<3;i=i+1)begin
    
    x_delta[i]<=-($signed(dy[i])<<<4);
   end state<=MULTIPLY_Y;end
   MULTIPLY_Y:begin for(i=0;i<3;i=i+1)begin ix[i]<=gradient_product[i];ea[i]<=edge_product[i];end state<=SUM;end
   SUM:begin for(i=0;i<3;i=i+1)begin
    edge_value[i]<=ea[i]-eb[i];row_edge[i]<=ea[i]-eb[i];
    value[i]<=($signed({1'b0,origin[i]})<<<8)+(initial_delta[i]>>>4);
    row_value[i]<=($signed({1'b0,origin[i]})<<<8)+(initial_delta[i]>>>4);end state<=PIXELS;end
   PIXELS,SKIP_APPLY:if(state==PIXELS&&mask==0)begin saved_step<=next_step;state<=SKIP_APPLY;end
   else if(state==SKIP_APPLY||accept)begin
    state<=PIXELS;
    if(({1'b0,px[4:0]}+step_pixels)>{1'b0,xe[4:0]})begin
     if(py==ye)state<=FINISH;
     else begin px<=xs;py<=py+1;for(i=0;i<3;i=i+1)begin
      edge_value[i]<=row_edge[i]+($signed(dx[i])<<<4);row_edge[i]<=row_edge[i]+($signed(dx[i])<<<4);
      value[i]<=row_value[i]+gy[i];row_value[i]<=row_value[i]+gy[i];end end
    end else begin px<=px+step_pixels;for(i=0;i<3;i=i+1)begin edge_value[i]<=edge_value[i]+(x_delta[i]<<<step_log);value[i]<=value[i]+($signed(gx[i])<<<step_log);end end
   end
   FINISH:begin done<=1;state<=IDLE;end
   default:state<=IDLE;
  endcase end
 end
endmodule

`default_nettype wire
