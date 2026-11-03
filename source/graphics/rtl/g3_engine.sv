module g3_engine(input logic clk,rstn,invalidate,begin_frame,
 input logic tile_valid,output logic tile_ready,input logic [9:0] tile_id,
 input logic [5:0] tile_x,tile_y,
 input logic [11:0] width,height,input logic [31:0] bin_base,geometry_base,geometry_count,
 input logic [31:0] frame_base,object_base,thumbnail_base,depth_base,rgb_base,ground_base,thermal_base,
 input logic [11:0] rgb_width,rgb_height,ground_width,ground_height,thermal_width,thermal_height,
 input logic [3:0] rgb_levels,ground_levels,thermal_levels,input logic [7:0] alpha,
 input logic [31:0] background,input logic make_thumbnail,make_depth,
 output logic idle,error,output logic [63:0] pixels,tiles,cache_misses,cache_stalls,mix_wait_cycles,
 output logic [63:0] diagnostic[0:5],
 output g3_pkg::rd_req_t rd[0:2],input logic [2:0] rd_ready,
 input g3_pkg::rd_rsp_t rsp[0:2],output logic [2:0] rsp_ready,
 output g3_pkg::wr_req_t wr,input logic wr_ready,output g3_pkg::wr_data_t wd,
 input logic wd_ready,wr_done,wr_error);
 import g3_pkg::*;

 typedef enum logic [4:0]{IDLE,CLEAR,GET_DESC,MIP_INIT,MIP_STEP,RASTER_START,DRAW,DRAIN,RESOLVE_WAIT,
  MIP_GRADIENT,MIP_PRODUCTS,MIP_SUM,MIP_EXTENT,MIP_AREA,MIP_BYTES,MIP_PRODUCTS_HIGH} state_t;
 state_t state;logic page;logic [5:0] tx,ty;logic [9:0] tile_number;
 logic [8:0] clear_index;logic [1:0] occupied;
 logic reader_valid,reader_last,reader_complete,reader_error,desc_last;
 logic [1023:0] fetched,desc;
 logic raster_ready,raster_done,raster_valid,raster_accept;
 logic [1:0] raster_mask,early_mask;logic [9:0] raster_index,early_index;
 logic [15:0] raster_z[0:1],raster_u[0:1],raster_v[0:1],early_z[0:1],early_u[0:1],early_v[0:1];
 logic [63:0] queried[0:1],old_pixel[0:1],resolved[0:1];
 logic query_pending,early_valid,raster_finished,query_advance;
 logic [1:0] query_mask;logic [9:0] query_index;
 logic [15:0] query_z[0:1],query_u[0:1],query_v[0:1];
 logic shader_ready,shader_valid,shader_error,shader_sprite,shader_idle;
 logic store_query_ready,store_commit_ready,store_busy;
 logic [1:0] shader_mask;logic [9:0] shader_index;
 logic [15:0] shader_z[0:1];logic [63:0] shader_old[0:1];logic [31:0] shader_color[0:1];
 logic resolve_ready,resolve_done,resolve_error,resolve_start,resolve_page,resolve_read;
 logic [8:0] resolve_index;logic [5:0] resolve_tx,resolve_ty;
 logic output_page;logic [31:0] mip_base[0:1];logic [11:0] mip_w[0:1],mip_h[0:1];
 logic [3:0] mip_level[0:1],mip_limit[0:1];logic [47:0] footprint[0:1];
 logic [31:0] derivative;logic [1:0] mip_step;integer l,c;
 logic [31:0] gradient_abs[0:3];logic [27:0] footprint_low[0:1],footprint_high[0:1];
 logic [11:0] mip_dimension[0:1];
 logic [11:0] padded_w[0:1],padded_h[0:1];
 logic [23:0] mip_area[0:1];logic [25:0] level_bytes[0:1];
 (* use_dsp="yes" *) logic [27:0] mip_product[0:1];
 generate for(genvar m=0;m<2;m=m+1)begin
  assign footprint_high[m]=mip_product[m];assign mip_area[m]=mip_product[m][23:0];
  // Mipmap selection is triangle setup, not the per-pixel hot path.
  always_ff @(posedge clk)if(state==MIP_PRODUCTS||state==MIP_PRODUCTS_HIGH||state==MIP_AREA)
   mip_product[m]<=(state==MIP_AREA?{4'b0,padded_w[m]}:(state==MIP_PRODUCTS?derivative[15:0]:derivative[31:16]))*
                   (state==MIP_AREA?padded_h[m]:mip_dimension[m]);
 end endgenerate
 function automatic [31:0] abs32(input logic signed [31:0] a);abs32=a<0?-a:a;endfunction
 function automatic [31:0] maximum_gradient(input logic [1023:0] d);
  logic [31:0] a,b,c,e;begin a=abs32(d[15*32+:32]);b=abs32(d[16*32+:32]);c=abs32(d[17*32+:32]);e=abs32(d[18*32+:32]);maximum_gradient=(a>b?a:b)>(c>e?c:e)?(a>b?a:b):(c>e?c:e);end
 endfunction
 function automatic [31:0] mip_bytes(input logic [11:0] w,h);
  logic [25:0] s;begin s=((w+7)&12'hff8)*((h+3)&12'hffc)*4;mip_bytes=(s+127)&32'hffffff80;end
 endfunction
 assign tile_ready=state==IDLE&&!occupied[page]&&!error;
 assign idle=state==IDLE&&occupied==0;
 g3_bin_reader reader(.clk(clk),.rstn(rstn),.start(tile_valid&&tile_ready),.invalidate(begin_frame),.tile(tile_id),
  .bin_base(bin_base),.geometry_base(geometry_base),.geometry_count(geometry_count),
  .valid(reader_valid),.ready(state==GET_DESC),.last(reader_last),.complete(reader_complete),
  .error(reader_error),.descriptor(fetched),.rd(rd[0]),.rd_ready(rd_ready[0]),.rsp(rsp[0]),.rsp_ready(rsp_ready[0]));
 g3_raster_pair raster(.clk(clk),.rstn(rstn),.start(state==RASTER_START),.descriptor(desc),
  .width(width),.height(height),.tile_x(tx),.tile_y(ty),.ready(raster_ready),.done(raster_done),
  .valid(raster_valid),.accept(raster_accept),.mask(raster_mask),.index(raster_index),.z(raster_z),.u(raster_u),.v(raster_v));
 assign query_advance=query_pending&&(!early_valid||shader_ready);
 assign raster_accept=state==DRAW&&(!query_pending||query_advance)&&store_query_ready;
 g3_shader shader(.clk(clk),.rstn(rstn),.invalidate(invalidate),.in_valid(early_valid),.in_ready(shader_ready),.idle(shader_idle),
  .in_mask(early_mask),.in_index(early_index),.in_z(early_z),.in_u(early_u),.in_v(early_v),.in_old(old_pixel),
  .rgba(desc[32+:32]),.textured(desc[8]),.thermal_on(desc[9]),.sprite(desc[7:0]==3),.alpha(alpha),
  .rgb_base(mip_base[0]),.thermal_base(mip_base[1]),.rgb_width(mip_w[0]),.rgb_height(mip_h[0]),
  .thermal_width(mip_w[1]),.thermal_height(mip_h[1]),
  .out_valid(shader_valid),.out_ready(store_commit_ready),.out_mask(shader_mask),.out_index(shader_index),
  .out_z(shader_z),.out_old(shader_old),.out_color(shader_color),.out_sprite(shader_sprite),
  .error(shader_error),.misses(cache_misses),.stall_cycles(cache_stalls),.diagnostic(diagnostic[0:4]),
  .rd(rd[1:2]),.rd_ready(rd_ready[2:1]),.rsp(rsp[1:2]),.rsp_ready(rsp_ready[2:1]));
 g3_tile_store store(.clk(clk),.rstn(rstn),.clear(state==CLEAR),.clear_page(page),.clear_index(clear_index),.background(background),
  .query(raster_valid&&raster_accept),.query_page(page),.query_index(raster_index),.queried(queried),.query_ready(store_query_ready),
  .commit(shader_valid&&store_commit_ready&&(|shader_mask)),.commit_page(page),.commit_index(shader_index),.commit_mask(shader_mask),.commit_ready(store_commit_ready),.busy(store_busy),
  .commit_z(shader_z),.old_pixel(shader_old),.object_id(desc[64+:16]),.color(shader_color),.sprite(shader_sprite),
  .resolve(resolve_read),.resolve_page(resolve_page),.resolve_index(resolve_index),.resolved(resolved));
 g3_resolve resolve(.clk(clk),.rstn(rstn),.start(resolve_start),.page(output_page),
  .tile_x(resolve_tx),.tile_y(resolve_ty),.width(width),.height(height),.frame_base(frame_base),
  .object_base(object_base),.thumbnail_base(thumbnail_base),.depth_base(depth_base),.make_depth(make_depth),.make_thumbnail(make_thumbnail),
  .ready(resolve_ready),.done(resolve_done),.error(resolve_error),.read_tile(resolve_read),
  .read_page(resolve_page),.read_index(resolve_index),.tile_pixel(resolved),
  .wr(wr),.wr_ready(wr_ready),.wd(wd),.wd_ready(wd_ready),.wr_done(wr_done),.wr_error(wr_error));
 always_comb begin
  for(integer cl=0;cl<2;cl=cl+1)mip_dimension[cl]=mip_w[cl]>mip_h[cl]?mip_w[cl]:mip_h[cl];
  for(integer cl=0;cl<2;cl=cl+1)mip_step[cl]=footprint[cl]>48'd33554431&&mip_level[cl]+1<mip_limit[cl]&&(mip_w[cl]>1||mip_h[cl]>1);
 end
 always_ff @(posedge clk)begin
  if(!rstn)begin state<=IDLE;page<=0;occupied<=0;error<=0;pixels<=0;tiles<=0;resolve_start<=0;
   query_pending<=0;early_valid<=0;raster_finished<=0;mix_wait_cycles<=0;diagnostic[5]<=0;end
  else begin
   resolve_start<=0;if(state==IDLE)diagnostic[5]<=diagnostic[5]+1;
   if(early_valid&&!shader_ready)mix_wait_cycles<=mix_wait_cycles+1;
   if(resolve_done)occupied[output_page]<=0;
   if(reader_error||shader_error||resolve_error)error<=1;
   if(early_valid&&shader_ready)early_valid<=0;
   case({raster_valid&&raster_accept,query_advance})
    2'b10:query_pending<=1;
    2'b01:query_pending<=0;
    default:begin end
   endcase
   if(raster_valid&&raster_accept)begin
    query_mask<=raster_mask;query_index<=raster_index;
    for(l=0;l<2;l=l+1)begin query_z[l]<=raster_z[l];query_u[l]<=raster_u[l];query_v[l]<=raster_v[l];end
   end
   if(query_advance)begin
    early_valid<=|(query_mask & {query_z[1]<=queried[1][47:32],query_z[0]<=queried[0][47:32]});early_index<=query_index;
    for(l=0;l<2;l=l+1)begin
     old_pixel[l]<=queried[l];early_mask[l]<=query_mask[l]&&query_z[l]<=queried[l][47:32];
     early_z[l]<=query_z[l];early_u[l]<=query_u[l];early_v[l]<=query_v[l];
    end
   end
   if(shader_valid&&store_commit_ready)pixels<=pixels+shader_mask[0]+shader_mask[1];
   if(raster_done)raster_finished<=1;
   case(state)
    IDLE:if(tile_valid&&tile_ready)begin
     tile_number<=tile_id;tx<=tile_x;ty<=tile_y;
     clear_index<=0;occupied[page]<=1;state<=CLEAR;
    end
    CLEAR:if(clear_index==511)state<=GET_DESC;else clear_index<=clear_index+1;
    GET_DESC:if(reader_valid)begin desc<=fetched;desc_last<=reader_last;state<=(!fetched[8]||fetched[7:0]==3)?RASTER_START:MIP_INIT;end
     else if(reader_complete)state<=RESOLVE_WAIT;
    MIP_INIT:begin
     mip_base[0]<=desc[14]?ground_base:rgb_base;mip_w[0]<=desc[14]?ground_width:rgb_width;
     mip_h[0]<=desc[14]?ground_height:rgb_height;mip_limit[0]<=desc[14]?ground_levels:rgb_levels;
     mip_base[1]<=thermal_base;mip_w[1]<=thermal_width;mip_h[1]<=thermal_height;mip_limit[1]<=thermal_levels;
     for(l=0;l<4;l=l+1)gradient_abs[l]<=abs32(desc[(15+l)*32+:32]);
     mip_level[0]<=0;mip_level[1]<=0;state<=MIP_GRADIENT;
    end
    MIP_GRADIENT:begin
     derivative<=((gradient_abs[0]>gradient_abs[1]?gradient_abs[0]:gradient_abs[1])>
      (gradient_abs[2]>gradient_abs[3]?gradient_abs[2]:gradient_abs[3]))?
      (gradient_abs[0]>gradient_abs[1]?gradient_abs[0]:gradient_abs[1]):
      (gradient_abs[2]>gradient_abs[3]?gradient_abs[2]:gradient_abs[3]);state<=MIP_PRODUCTS;
    end
    MIP_PRODUCTS:state<=MIP_PRODUCTS_HIGH;
    MIP_PRODUCTS_HIGH:begin for(l=0;l<2;l=l+1)footprint_low[l]<=mip_product[l];state<=MIP_SUM;end
    MIP_SUM:begin for(l=0;l<2;l=l+1)footprint[l]<={20'b0,footprint_low[l]}+{4'b0,footprint_high[l],16'b0};state<=MIP_EXTENT;end
    MIP_EXTENT:begin for(l=0;l<2;l=l+1)begin
     padded_w[l]<=(mip_w[l]+12'd7)&12'hff8;padded_h[l]<=(mip_h[l]+12'd3)&12'hffc;
    end state<=MIP_AREA;end
    MIP_AREA:state<=MIP_BYTES;
    MIP_BYTES:begin for(l=0;l<2;l=l+1)level_bytes[l]<=({mip_area[l],2'b0}+26'd127)&26'h3ffff80;state<=MIP_STEP;end
    MIP_STEP:if(|mip_step)begin
     for(l=0;l<2;l=l+1)if(mip_step[l])begin
      mip_base[l]<=mip_base[l]+level_bytes[l];
      mip_w[l]<=mip_w[l]>1?mip_w[l]>>1:1;mip_h[l]<=mip_h[l]>1?mip_h[l]>>1:1;
      footprint[l]<=footprint[l]>>1;mip_level[l]<=mip_level[l]+1;
     end state<=MIP_EXTENT;
    end else state<=RASTER_START;
    RASTER_START:if(raster_ready)begin raster_finished<=0;state<=DRAW;end
    DRAW:if(raster_finished||raster_done)state<=DRAIN;
    DRAIN:if(!query_pending&&!early_valid&&shader_idle&&!shader_valid&&!store_busy)state<=desc_last?RESOLVE_WAIT:GET_DESC;
    RESOLVE_WAIT:if(resolve_ready)begin
     output_page<=page;resolve_tx<=tx;resolve_ty<=ty;resolve_start<=1;page<=!page;
     tiles<=tiles+1;state<=IDLE;
    end
    default:state<=IDLE;
   endcase
  end
 end
endmodule
