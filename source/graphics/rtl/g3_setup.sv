// Three parallel vertex MACs and six exact 64/32 setup dividers.
// Descriptor word layout is shared with reference/scene.py.
module g3_setup(input logic clk,rstn,start,
 input logic [511:0] command,input logic sprite_half,
 input logic signed [31:0] matrix[0:11],input logic [11:0] width,height,
 output logic ready,done,error,output logic [1023:0] descriptor);
 import g3_pkg::*;
 typedef enum logic [4:0]{IDLE,TRANSFORM,WAIT_VERTEX,SCREEN,AREA,ORIENT,
  BOUNDS,PRODUCTS,NUMERATORS,DIVIDE,WAIT_DIV,PACK,FINISH,AREA_DIFF,AREA_MULT,CLAMP_BOUNDS,PRODUCTS_Q} state_t;
 state_t state;logic [511:0] cmd;logic half;
 logic vertex_ready[0:2],vertex_valid[0:2],vertex_overflow[0:2];
 logic signed [15:0] sx[0:2],sy[0:2],x[0:2],y[0:2];
 logic [15:0] sz[0:2],a[0:2][0:2];
 // Differences of signed 16-bit screen vertices require 17 bits; their
 // determinant fits 35 bits. Register each operation before the next carry.
 logic signed [34:0] area;
 logic signed [16:0] dx1,dx2,dy1,dy2;
 logic signed [16:0] area_dx1,area_dx2,area_dy1,area_dy2;
 logic signed [33:0] area_p,area_q;
 logic signed [17:0] d1[0:2],d2[0:2];
 logic signed [35:0] p[0:5],q[0:5];
 logic signed [17:0] mul_a[0:5],mul_b[0:5];
 (* use_dsp="yes" *) logic signed [35:0] products[0:5];
 // Area and X/Y numerator products are never needed in the same cycle.
 // Six multiplier slots preserve all signed bits and share those phases.
 generate for(genvar n=0;n<6;n=n+1)begin
  assign q[n]=products[n];
  always_comb begin
   if(n%2==0)begin mul_a[n]=state==PRODUCTS_Q?d2[n/2]:d1[n/2];mul_b[n]=state==PRODUCTS_Q?dy1:dy2;end
   else begin mul_a[n]=state==PRODUCTS_Q?d1[n/2]:d2[n/2];mul_b[n]=state==PRODUCTS_Q?dx2:dx1;end
   if(state==AREA_MULT)begin
    if(n==0)begin mul_a[n]=area_dx1;mul_b[n]=area_dy2;end
    if(n==1)begin mul_a[n]=area_dy1;mul_b[n]=area_dx2;end
   end
  end
  always_ff @(posedge clk)if(state==AREA_MULT||state==PRODUCTS||state==PRODUCTS_Q)products[n]<=mul_a[n]*mul_b[n];
 end endgenerate
 assign area_p=products[0][33:0];assign area_q=products[1][33:0];
 logic signed [63:0] numerator[0:5],gradient[0:5];
 logic div_busy[0:5],div_done[0:5],div_zero[0:5];
 logic signed [15:0] xmin,xmax,ymin,ymax;
 logic keep;integer i,k;
 generate for(genvar v=0;v<3;v=v+1)begin: vertices
  gfx_vertex unit(.clk(clk),.rstn(rstn),.in_valid(state==TRANSFORM),
   .in_ready(vertex_ready[v]),.x($signed(cmd[(4+v*4)*32+:32])),
   .y($signed(cmd[(5+v*4)*32+:32])),.z($signed(cmd[(6+v*4)*32+:32])),
   .matrix(matrix),.out_valid(vertex_valid[v]),.out_ready(state==WAIT_VERTEX),
   .sx(sx[v]),.sy(sy[v]),.depth(sz[v]),.overflow(vertex_overflow[v]));
 end endgenerate
 generate for(genvar d=0;d<6;d=d+1)begin: dividers
  gfx_div unit(.clk(clk),.rstn(rstn),.start(state==DIVIDE),.numerator(numerator[d]),
   .denominator(area[31:0]),.busy(div_busy[d]),.done(div_done[d]),
   .zero(div_zero[d]),.quotient(gradient[d]));
 end endgenerate
 function automatic signed [15:0] imin(input logic signed [15:0] a,b,c);
  imin=a<b?(a<c?a:c):(b<c?b:c);
 endfunction
 function automatic signed [15:0] imax(input logic signed [15:0] a,b,c);
  imax=a>b?(a>c?a:c):(b>c?b:c);
 endfunction
 assign ready=state==IDLE;
 always_ff @(posedge clk)begin
  if(!rstn)begin state<=IDLE;done<=0;error<=0;descriptor<=0;keep<=0;end
  else begin
   done<=0;
   case(state)
    IDLE:if(start)begin cmd<=command;half<=sprite_half;error<=0;keep<=1;state<=command[7:0]==2?SCREEN:TRANSFORM;end
    TRANSFORM:if(vertex_ready[0]&&vertex_ready[1]&&vertex_ready[2])state<=WAIT_VERTEX;
    WAIT_VERTEX:if(vertex_valid[0]&&vertex_valid[1]&&vertex_valid[2])begin
     if(vertex_overflow[0]||(cmd[7:0]!=3&&(vertex_overflow[1]||vertex_overflow[2])))begin error<=1;state<=FINISH;end
     else begin
      for(i=0;i<3;i=i+1)begin x[i]<=sx[i];y[i]<=sy[i];a[0][i]<=sz[i];a[1][i]<=cmd[(7+i*4)*32+:16];a[2][i]<=cmd[(7+i*4)*32+16+:16];end
      if(cmd[7:0]==3)begin
       x[0]<=sx[0]-($signed(cmd[8*32+:32])>>>13);y[0]<=sy[0]-($signed(cmd[9*32+:32])>>>13);
       x[1]<=sx[0]+($signed(cmd[8*32+:32])>>>13);
       y[1]<=half?sy[0]+($signed(cmd[9*32+:32])>>>13):sy[0]-($signed(cmd[9*32+:32])>>>13);
       x[2]<=half?sx[0]-($signed(cmd[8*32+:32])>>>13):sx[0]+($signed(cmd[8*32+:32])>>>13);
       y[2]<=sy[0]+($signed(cmd[9*32+:32])>>>13);
       for(i=0;i<3;i=i+1)a[0][i]<=sz[0];
       a[1][0]<=0;a[2][0]<=0;a[1][1]<=65535;a[2][1]<=half?65535:0;
       a[1][2]<=half?0:65535;a[2][2]<=65535;
      end
      state<=AREA_DIFF;
     end
    end
    SCREEN:begin
     for(i=0;i<3;i=i+1)begin
      x[i]<=$signed(cmd[(4+i*4)*32+:32])>>>12;y[i]<=$signed(cmd[(5+i*4)*32+:32])>>>12;
      a[0][i]<=cmd[(6+i*4)*32+:16];a[1][i]<=cmd[(7+i*4)*32+:16];a[2][i]<=cmd[(7+i*4)*32+16+:16];
      if(($signed(cmd[(4+i*4)*32+:32])>>>12)>32767||($signed(cmd[(4+i*4)*32+:32])>>>12)<-32768||
       ($signed(cmd[(5+i*4)*32+:32])>>>12)>32767||($signed(cmd[(5+i*4)*32+:32])>>>12)<-32768)error<=1;
     end
     state<=AREA_DIFF;
    end
    AREA_DIFF:begin
     area_dx1<=$signed({x[1][15],x[1]})-$signed({x[0][15],x[0]});
     area_dx2<=$signed({x[2][15],x[2]})-$signed({x[0][15],x[0]});
     area_dy1<=$signed({y[1][15],y[1]})-$signed({y[0][15],y[0]});
     area_dy2<=$signed({y[2][15],y[2]})-$signed({y[0][15],y[0]});state<=AREA_MULT;
    end
    AREA_MULT:state<=AREA;
    AREA:begin area<=$signed({area_p[33],area_p})-$signed({area_q[33],area_q});state<=ORIENT;end
    ORIENT:begin
     if(area==0||(area<0&&cmd[10])||error)begin keep<=0;state<=PACK;end
     else if(area>64'sd2147483647||area< -64'sd2147483647)begin keep<=0;error<=1;state<=PACK;end
     else begin
      if(area<0)begin area<=-area;x[1]<=x[2];x[2]<=x[1];y[1]<=y[2];y[2]<=y[1];
       for(i=0;i<3;i=i+1)begin a[i][1]<=a[i][2];a[i][2]<=a[i][1];end end
      state<=BOUNDS;
     end
    end
    BOUNDS:begin
     // Shift in a signed-only context. An unsigned width/height branch of
     // ?: otherwise makes a negative vertex zero-extend before >>>.
     xmin<=imin(x[0],x[1],x[2])>>>4;ymin<=imin(y[0],y[1],y[2])>>>4;
     xmax<=imax(x[0],x[1],x[2])>>>4;ymax<=imax(y[0],y[1],y[2])>>>4;
     dx1<=$signed(x[1])-$signed(x[0]);dx2<=$signed(x[2])-$signed(x[0]);
     dy1<=$signed(y[1])-$signed(y[0]);dy2<=$signed(y[2])-$signed(y[0]);
     for(i=0;i<3;i=i+1)begin d1[i]<=$signed({1'b0,a[i][1]})-$signed({1'b0,a[i][0]});d2[i]<=$signed({1'b0,a[i][2]})-$signed({1'b0,a[i][0]});end
     state<=CLAMP_BOUNDS;
    end
    CLAMP_BOUNDS:begin
     if(xmax<0||ymax<0||xmin>=$signed({4'b0,width})||ymin>=$signed({4'b0,height}))begin
      keep<=0;state<=PACK;
     end else begin
      if(xmin<0)xmin<=0;if(ymin<0)ymin<=0;
      if(xmax>=$signed({4'b0,width}))xmax<=$signed({4'b0,width})-16'sd1;
      if(ymax>=$signed({4'b0,height}))ymax<=$signed({4'b0,height})-16'sd1;
      state<=PRODUCTS;
     end
    end
    PRODUCTS:begin
     if(xmin>xmax||ymin>ymax)begin keep<=0;state<=PACK;end
     else state<=PRODUCTS_Q;
    end
    PRODUCTS_Q:begin for(i=0;i<6;i=i+1)p[i]<=products[i];state<=NUMERATORS;end
    NUMERATORS:begin for(i=0;i<6;i=i+1)numerator[i]<=($signed({{28{p[i][35]}},p[i]})-$signed({{28{q[i][35]}},q[i]}))<<<12;state<=DIVIDE;end
    DIVIDE:state<=WAIT_DIV;
    WAIT_DIV:if(div_done[0]&&div_done[1]&&div_done[2]&&div_done[3]&&div_done[4]&&div_done[5])begin
     for(i=0;i<6;i=i+1)if(gradient[i]>64'sd2147483647||gradient[i]< -64'sd2147483648)error<=1;
     state<=PACK;
    end
    PACK:begin
     descriptor<=0;descriptor[0+:32]<=cmd[0+:32];descriptor[32+:32]<=cmd[32+:32];
     descriptor[64+:32]<=cmd[64+:32];descriptor[96+:32]<=keep;
     for(i=0;i<3;i=i+1)begin
      descriptor[(4+i*2)*32+:32]<={{16{x[i][15]}},x[i]};
      descriptor[(5+i*2)*32+:32]<={{16{y[i][15]}},y[i]};
      descriptor[(10+i)*32+:32]<={16'b0,a[i][0]};
      descriptor[(13+i*2)*32+:32]<=gradient[i*2][31:0];
      descriptor[(14+i*2)*32+:32]<=gradient[i*2+1][31:0];
     end
     descriptor[19*32+:32]<={{16{xmin[15]}},xmin};descriptor[20*32+:32]<={{16{xmax[15]}},xmax};
     descriptor[21*32+:32]<={{16{ymin[15]}},ymin};descriptor[22*32+:32]<={{16{ymax[15]}},ymax};state<=FINISH;
    end
    FINISH:begin done<=1;state<=IDLE;end
    default:state<=IDLE;
   endcase
  end
 end
endmodule
