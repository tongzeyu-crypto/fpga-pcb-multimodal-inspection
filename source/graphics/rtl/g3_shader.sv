// Address/fetch front end overlaps filtering/compositing of the previous pair.
// Metadata stays ordered; idle means BOTH stages have drained at triangle end.
module g3_shader(input logic clk,rstn,invalidate,
 input logic in_valid,output logic in_ready,output logic idle,input logic [1:0] in_mask,
 input logic [9:0] in_index,input logic [15:0] in_z[0:1],in_u[0:1],in_v[0:1],
 input logic [63:0] in_old[0:1],input logic [31:0] rgba,
 input logic textured,thermal_on,sprite,input logic [7:0] alpha,
 input logic [31:0] rgb_base,thermal_base,input logic [11:0] rgb_width,rgb_height,thermal_width,thermal_height,
 output logic out_valid,input logic out_ready,output logic [1:0] out_mask,
 output logic [9:0] out_index,output logic [15:0] out_z[0:1],
 output logic [63:0] out_old[0:1],output logic [31:0] out_color[0:1],
 output logic out_sprite,error,output logic [63:0] misses,stall_cycles,
 output logic [63:0] diagnostic[0:4],
 output g3_pkg::rd_req_t rd[0:1],input logic [1:0] rd_ready,
 input g3_pkg::rd_rsp_t rsp[0:1],output logic [1:0] rsp_ready);
 import g3_pkg::*;
 typedef struct packed {logic [1:0] mask;logic [9:0] index;logic [31:0] color;logic [7:0] alpha;
  logic tex,heat,spr;logic [31:0] z,u,v;logic [127:0] old;} meta_t;
 meta_t meta[0:4],current,ctx_fifo[0:7];
 logic [7:0] ctx_fifo_fx[0:7][0:3],ctx_fifo_fy[0:7][0:3];
 logic [2:0] head,tail;logic [3:0] count;logic pop,head_fetch,head_heat,front_fetch,front_heat;
 logic [4:0] valid;logic advance,take,math_ready,math_idle;
 
 logic [27:0] xp0[0:3],yp0[0:3],xp1[0:3],yp1[0:3];
 (* use_dsp="yes" *) logic [19:0] rows1[0:3];
 logic [23:0] offsets3[0:1][0:7];logic [31:0] addr4[0:1][0:7],addresses[0:1][0:7];
 logic [7:0] fx2[0:3],fy2[0:3],fx3[0:3],fy3[0:3],fx4[0:3],fy4[0:3],fx[0:3],fy[0:3];
 logic [31:0] saved[0:1][0:7],samples[0:1][0:7];logic [15:0] z[0:1],uu[0:1],vv[0:1];logic [63:0] old[0:1];
 logic [63:0] request_wait[0:1],first_wait[0:1],conflicts[0:1];
 logic [1:0] sent,got,cache_ready,cache_valid,cache_error;logic [63:0] cache_miss[0:1],cache_stall[0:1];
 logic [19:0] rows2[0:3];logic [11:0] source_y2[0:3],x2[0:1][0:7],y2[0:1][0:7];
 logic [11:0] w,h,tx,ty,xx,yy;integer t,l,j;
 wire [11:0] width_minus[0:1],height_minus[0:1];wire [11:0] width_padded[0:1];wire [8:0] block_stride[0:1];
 assign width_minus[0]=rgb_width-12'd1;assign width_minus[1]=thermal_width-12'd1;
 assign height_minus[0]=rgb_height-12'd1;assign height_minus[1]=thermal_height-12'd1;
 assign width_padded[0]=rgb_width+12'd7;assign width_padded[1]=thermal_width+12'd7;
 assign block_stride[0]=width_padded[0][11:3];assign block_stride[1]=width_padded[1][11:3];
 function automatic [23:0] offset_of(input logic [19:0] r,input logic [11:0] w,ty,x,y);
  logic [19:0] block;begin block=r+(x>>3);if((y>>2)!=(ty>>2))block=block+((w+12'd7)>>3);
   offset_of={block[16:0],y[1],x[2:1],y[0],x[0],2'b0};end
 endfunction
 assign current=ctx_fifo[head];
 assign head_fetch=current.tex&&!current.spr&&current.mask!=0;
 assign head_heat=head_fetch&&current.heat;
 assign front_fetch=meta[4].tex&&!meta[4].spr&&meta[4].mask!=0;
 assign front_heat=front_fetch&&meta[4].heat;
// Eight metadata credits decouple front-end admission from downstream retirement.
 // Capacity supplies the lookup latency; readiness depends only on registered occupancy.
 assign pop=count!=0&&math_ready&&(!head_fetch||cache_valid[0])&&(!head_heat||cache_valid[1]);
 assign take=valid[4]&&(count<8)&&(!front_fetch||(cache_ready[0]&&(!front_heat||cache_ready[1])));
 assign advance=!valid[4]||take;assign in_ready=advance;
 assign idle=valid==0&&count==0&&math_idle;
 generate for(genvar m=0;m<4;m=m+1)begin assign fx[m]=ctx_fifo_fx[head][m];assign fy[m]=ctx_fifo_fy[head][m];end endgenerate
 assign diagnostic[0]=request_wait[0]+request_wait[1];assign diagnostic[1]=first_wait[0]+first_wait[1];assign diagnostic[2]=conflicts[0]+conflicts[1];
 always_ff @(posedge clk)begin
  if(!rstn)begin diagnostic[3]<=0;diagnostic[4]<=0;end
  else begin if(count!=0&&((head_fetch&&!cache_valid[0])||(head_heat&&!cache_valid[1])))diagnostic[3]<=diagnostic[3]+1;
   if(out_valid&&!out_ready)diagnostic[4]<=diagnostic[4]+1;end
 end
 assign error=|cache_error;assign misses=cache_miss[0]+cache_miss[1];assign stall_cycles=cache_stall[0]+cache_stall[1];
 generate for(genvar b=0;b<2;b=b+1)begin: caches
  assign z[b]=current.z[b*16+:16];assign uu[b]=current.u[b*16+:16];assign vv[b]=current.v[b*16+:16];assign old[b]=current.old[b*64+:64];
  g3_tex_cache #(.CACHE_BYTES(b==0?65536:32768)) cache(.clk(clk),.rstn(rstn),.invalidate(invalidate),
   .in_valid(take&&front_fetch&&(b==0||front_heat)),.in_ready(cache_ready[b]),.address(addr4[b]),
   .out_valid(cache_valid[b]),.out_ready(pop&&head_fetch&&(b==0||head_heat)),.sampled(samples[b]),
   .req(rd[b]),.req_ready(rd_ready[b]),.rsp(rsp[b]),.rsp_ready(rsp_ready[b]),
   .error(cache_error[b]),.misses(cache_miss[b]),.stall_cycles(cache_stall[b]),
   .request_wait(request_wait[b]),.first_return_wait(first_wait[b]),.bank_conflict_wait(conflicts[b]));
 end endgenerate
 g3_shader_pair math(.clk(clk),.rstn(rstn),.idle(math_idle),.in_valid(count!=0&&(!head_fetch||cache_valid[0])&&(!head_heat||cache_valid[1])),.in_ready(math_ready),
  .in_mask(current.mask),.in_index(current.index),.in_z(z),.in_u(uu),.in_v(vv),.in_old(old),.rgba(current.color),.textured(current.tex),.thermal_on(current.heat),
  .sprite(current.spr),.alpha(current.alpha),.in_samples(samples),.in_fx(fx),.in_fy(fy),
  .out_valid(out_valid),.out_ready(out_ready),.out_mask(out_mask),.out_index(out_index),.out_z(out_z),
  .out_old(out_old),.out_color(out_color),.out_sprite(out_sprite));
 // Five elastic address stages. The global CE stalls data and valid flags
 // together; no data resets or input-to-output combinational address chain.
 always_ff @(posedge clk)begin
  if(!rstn)begin valid<=0;head<=0;tail<=0;count<=0;end
  else begin
   if(advance)begin
    valid<={valid[3:0],in_valid};for(t=1;t<5;t=t+1)meta[t]<=meta[t-1];
    if(in_valid)begin
     meta[0].mask<=in_mask;meta[0].index<=in_index;meta[0].color<=rgba;meta[0].alpha<=alpha;
     meta[0].tex<=textured;meta[0].heat<=thermal_on&&alpha!=0;meta[0].spr<=sprite;
     for(l=0;l<2;l=l+1)begin meta[0].z[l*16+:16]<=in_z[l];meta[0].u[l*16+:16]<=in_u[l];meta[0].v[l*16+:16]<=in_v[l];meta[0].old[l*64+:64]<=in_old[l];end
    end
    for(t=0;t<2;t=t+1)for(l=0;l<2;l=l+1)begin
     xp0[t*2+l]<=in_u[l]*width_minus[t];
     yp0[t*2+l]<=in_v[l]*height_minus[t];
    end
    for(t=0;t<4;t=t+1)begin
     xp1[t]<=xp0[t];yp1[t]<=yp0[t];rows1[t]<=yp0[t][27:18]*block_stride[t/2];
    end
    for(t=0;t<2;t=t+1)for(l=0;l<2;l=l+1)begin
     fx2[t*2+l]<=xp1[t*2+l][15:8];fy2[t*2+l]<=yp1[t*2+l][15:8];
     w=t==0?rgb_width:thermal_width;h=t==0?rgb_height:thermal_height;tx=xp1[t*2+l]>>16;ty=yp1[t*2+l]>>16;
     rows2[t*2+l]<=rows1[t*2+l];source_y2[t*2+l]<=ty;
     for(j=0;j<4;j=j+1)begin x2[t][l*4+j]<=j[0]&&tx+1<w?tx+1:tx;y2[t][l*4+j]<=j[1]&&ty+1<h?ty+1:ty;end
    end
    for(t=0;t<2;t=t+1)for(l=0;l<2;l=l+1)for(j=0;j<4;j=j+1)offsets3[t][l*4+j]<=offset_of(rows2[t*2+l],t==0?rgb_width:thermal_width,source_y2[t*2+l],x2[t][l*4+j],y2[t][l*4+j]);
    for(t=0;t<4;t=t+1)begin fx3[t]<=fx2[t];fy3[t]<=fy2[t];fx4[t]<=fx3[t];fy4[t]<=fy3[t];end
    for(t=0;t<2;t=t+1)for(j=0;j<8;j=j+1)addr4[t][j]<=(t==0?rgb_base:thermal_base)+{8'b0,offsets3[t][j]};
   end
   case({take,pop})2'b10:count<=count+1;2'b01:count<=count-1;default:begin end endcase
   if(pop)head<=head+1;
   if(take)begin
    ctx_fifo[tail]<=meta[4];tail<=tail+1;
    for(t=0;t<4;t=t+1)begin ctx_fifo_fx[tail][t]<=fx4[t];ctx_fifo_fy[tail][t]<=fy4[t];end
   end
  end
 end
endmodule
