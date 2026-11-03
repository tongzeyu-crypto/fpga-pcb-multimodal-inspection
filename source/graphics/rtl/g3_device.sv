// Independent ABI3 shell. Read and write AXI ports bind HP2 and HP0.
module g3_device(input logic clk,rstn,vsync,scan_adopted,input logic [63:0] scan_read_bytes,
 input logic [31:0] scan_underflows,scan_active_layer,scan_active_cursor,input logic scan_ui_drained,
 output logic [31:0] cursor_position,layer_address,output logic ui_quiet,output logic irq,
 input logic [8:0] s_axi_awaddr,input logic s_axi_awvalid,output logic s_axi_awready,
 input logic [31:0] s_axi_wdata,input logic [3:0] s_axi_wstrb,input logic s_axi_wvalid,output logic s_axi_wready,
 output logic [1:0] s_axi_bresp,output logic s_axi_bvalid,input logic s_axi_bready,
 input logic [8:0] s_axi_araddr,input logic s_axi_arvalid,output logic s_axi_arready,
 output logic [31:0] s_axi_rdata,output logic [1:0] s_axi_rresp,output logic s_axi_rvalid,input logic s_axi_rready,
 output logic [2:0] m_axi_arid,output logic [31:0] m_axi_araddr,
 output logic [7:0] m_axi_arlen,output logic [2:0] m_axi_arsize,
 output logic [1:0] m_axi_arburst,output logic m_axi_arvalid,input logic m_axi_arready,
 input logic [2:0] m_axi_rid,input logic [63:0] m_axi_rdata,input logic [1:0] m_axi_rresp,
 input logic m_axi_rlast,m_axi_rvalid,output logic m_axi_rready,
 output logic [1:0] m_axi_awid,output logic [31:0] m_axi_awaddr,
 output logic [7:0] m_axi_awlen,output logic [2:0] m_axi_awsize,
 output logic [1:0] m_axi_awburst,output logic m_axi_awvalid,input logic m_axi_awready,
 output logic [63:0] m_axi_wdata,output logic [7:0] m_axi_wstrb,
 output logic m_axi_wlast,m_axi_wvalid,input logic m_axi_wready,
 input logic [1:0] m_axi_bid,m_axi_bresp,input logic m_axi_bvalid,output logic m_axi_bready,
 output logic [31:0] front_address,presented_id,rendered_id,
 output logic [31:0] front_wh,output logic native_view);
 import g3_pkg::*;
 typedef enum logic [2:0]{IDLE,PREP_START,PREP_WAIT,RENDER,DRAIN,FINISH,FAILED} state_t;
 state_t state;
 logic [31:0] cfg[0:35];logic signed [31:0] matrix[0:11];
 logic [31:0] depth_base;
 logic start,quiet,fatal,aw_pending,w_pending;logic [8:0] awaddr;
 logic [31:0] wdata;logic [3:0] wstrb;
 logic [3:0] frame_error,binner_error;logic binner_busy,binner_done;
 logic [31:0] geometry_count,reference_count;
 logic [63:0] prep_cycles,bin_cycles;
 rd_req_t read_req[0:6];rd_rsp_t read_rsp[0:6];
 wr_req_t write_req[0:2];wr_data_t write_data[0:2];
 logic [6:0] read_ready,response_ready;logic [2:0] write_ready,data_ready,write_done,write_error;
 logic bus_fault,bus_idle;logic [63:0] read_bytes,write_bytes,ddr_wait;
 logic [1:0] engine_ready,engine_idle,engine_error,offer;
 logic [63:0] pixels[0:1],tiles[0:1],misses[0:1],cache_wait[0:1];
 logic [63:0] bases[0:7],perf[0:14],ticks,raster_ticks,commit_wait,mix_wait[0:1];
 logic [63:0] diagnostic[0:1][0:5],diagnostic_sum[0:5],diagnostic_base[0:5],diagnostic_frame[0:5];
 logic [63:0] sum_misses,sum_cache_wait,sum_pixels,sum_tiles,sum_mix_wait;
 logic [63:0] display_start,display_bytes,display_underflows;logic [31:0] underflow_start;
 logic [9:0] next_tile,total_tiles;logic [5:0] nx,tx,ty;logic round_robin;
 logic source_changed,source_dirty;logic [31:0] last_generation,last_rgb,last_ground,last_heat;
 logic [31:0] pending_address,pending_id,pending_wh,staged_front;
 logic [31:0] staged_layer,pending_layer;
 logic pending_valid,vsold,adopting,pending_native;logic [31:0] adopting_id;integer i,k;
 assign ui_quiet=quiet;
 // Configuration is committed while IDLE. Precompute the comparison before
 // PREP_START so the pixel-ready chain sees only a registered dirty bit.
 // The frame starts on the following cycle; no additional frame latency.
 always_ff @(posedge clk)begin
  if(!rstn)source_dirty<=1;
  else if(state==IDLE)source_dirty<=cfg[23]!=last_generation||cfg[12]!=last_rgb||cfg[14]!=last_ground||cfg[16]!=last_heat;
 end
 assign source_changed=state==PREP_START&&source_dirty;
 assign s_axi_awready=!aw_pending&&!s_axi_bvalid;
 assign s_axi_wready=!w_pending&&!s_axi_bvalid;
 assign s_axi_arready=!s_axi_rvalid;assign s_axi_rresp=0;
 generate for(genvar m=0;m<12;m=m+1)assign matrix[m]=$signed(cfg[24+m]);endgenerate
 always_comb begin
  offer=0;
  if(state==RENDER&&next_tile<total_tiles)begin
   if(engine_ready[round_robin])offer[round_robin]=1;
   else if(engine_ready[!round_robin])offer[!round_robin]=1;
  end
 end
 // Separate the engine sums, per-frame subtraction and AXI read mux. The
 // snapshot is immutable until the next completed (or rejected) frame.
 always_ff @(posedge clk)begin
  for(integer di=0;di<6;di=di+1)diagnostic_sum[di]<=diagnostic[0][di]+diagnostic[1][di];
  sum_misses<=misses[0]+misses[1];sum_cache_wait<=cache_wait[0]+cache_wait[1];
  sum_pixels<=pixels[0]+pixels[1];sum_tiles<=tiles[0]+tiles[1];sum_mix_wait<=mix_wait[0]+mix_wait[1];
 end
 function automatic [31:0] read_register(input logic [8:0] a);
  begin
   if(a==4)read_register={28'b0,(quiet&&state==IDLE&&bus_idle&&scan_ui_drained),irq,fatal,(state!=IDLE)};
   else if(a>=8&&a<=140)read_register=cfg[a>>2];
   else if(a>=256&&a<376)read_register=a[2]?perf[(a-256)>>3][63:32]:perf[(a-256)>>3][31:0];
   else if(a>=400&&a<448)read_register=a[2]?diagnostic_frame[(a-400)>>3][63:32]:diagnostic_frame[(a-400)>>3][31:0];
   else case(a)
    448:read_register=depth_base;144:read_register=rendered_id;148:read_register=presented_id;152:read_register=front_address;
    156:read_register={28'b0,frame_error};504:read_register=/*G3_SOURCE_TAG*/32'h00000000;
    380:read_register=cursor_position;384:read_register=layer_address;
    388:read_register=scan_active_layer;392:read_register=scan_active_cursor;
    496:read_register=32'h00001f00;508:read_register=32'h47584633;default:read_register=0;
   endcase
  end
 endfunction
 g3_binner binner(.clk(clk),.rstn(rstn),.cull_enable(1'b1),.rejected_references(),.start(state==PREP_START),
  .command_base(cfg[2]),.command_count(cfg[3]),.geometry_base(cfg[4]),.bin_base(cfg[5]),.refs_capacity(cfg[6]),
  .width(cfg[10][11:0]),.height(cfg[10][27:16]),.matrix(matrix),
  .busy(binner_busy),.done(binner_done),.error(binner_error),.geometry_count(geometry_count),.reference_count(reference_count),
  .rd(read_req[0]),.rd_ready(read_ready[0]),.response(read_rsp[0]),.response_ready(response_ready[0]),
  .wr(write_req[0]),.wr_ready(write_ready[0]),.wd(write_data[0]),.wd_ready(data_ready[0]),
  .wr_done(write_done[0]),.wr_error(write_error[0]),.setup_cycles(prep_cycles),.bin_cycles(bin_cycles));
 generate for(genvar e=0;e<2;e=e+1)begin: engines
  g3_engine engine(.clk(clk),.rstn(rstn),.invalidate(source_changed),.begin_frame(state==PREP_START),.tile_valid(offer[e]),.tile_ready(engine_ready[e]),
   .tile_id(next_tile),.tile_x(tx),.tile_y(ty),.width(cfg[10][11:0]),.height(cfg[10][27:16]),
   .bin_base(cfg[5]),.geometry_base(cfg[4]),.geometry_count(geometry_count),
   .frame_base(cfg[7]),.object_base(cfg[8]),.thumbnail_base(cfg[9]),.depth_base(depth_base),.make_depth(cfg[21][4]),
   .rgb_base(cfg[12]),.ground_base(cfg[14]),.thermal_base(cfg[16]),
   .rgb_width(cfg[13][11:0]),.rgb_height(cfg[13][27:16]),.ground_width(cfg[15][11:0]),.ground_height(cfg[15][27:16]),
   .thermal_width(cfg[17][11:0]),.thermal_height(cfg[17][27:16]),
   .rgb_levels(cfg[22][3:0]),.ground_levels(cfg[22][7:4]),.thermal_levels(cfg[22][11:8]),
   .alpha(cfg[18][7:0]),.background(cfg[19]),.make_thumbnail(cfg[21][1]),
   .idle(engine_idle[e]),.error(engine_error[e]),.pixels(pixels[e]),.tiles(tiles[e]),
   .cache_misses(misses[e]),.cache_stalls(cache_wait[e]),.mix_wait_cycles(mix_wait[e]),.diagnostic(diagnostic[e]),
   .rd(read_req[1+3*e:3+3*e]),.rd_ready(read_ready[3+3*e:1+3*e]),
   .rsp(read_rsp[1+3*e:3+3*e]),.rsp_ready(response_ready[3+3*e:1+3*e]),
   .wr(write_req[1+e]),.wr_ready(write_ready[1+e]),.wd(write_data[1+e]),.wd_ready(data_ready[1+e]),
   .wr_done(write_done[1+e]),.wr_error(write_error[1+e]));
 end endgenerate
 g3_axi_fabric #(.NR(7),.NW(3)) memory(.clk(clk),.rstn(rstn),
  .rd(read_req),.rd_ready(read_ready),.rsp(read_rsp),.rsp_ready(response_ready),
  .wr(write_req),.wr_ready(write_ready),.wd(write_data),.wd_ready(data_ready),.wr_done(write_done),.wr_error(write_error),
  .fault(bus_fault),.quiescent(bus_idle),.read_bytes(read_bytes),.write_bytes(write_bytes),.wait_cycles(ddr_wait),.*);
 always_ff @(posedge clk)begin
  if(!rstn)begin
   cursor_position<=0;layer_address<=0;staged_layer<=0;pending_layer<=0;state<=IDLE;start<=0;quiet<=0;fatal<=0;irq<=0;frame_error<=0;
   aw_pending<=0;w_pending<=0;s_axi_bvalid<=0;s_axi_rvalid<=0;s_axi_bresp<=0;
   front_address<=0;presented_id<=0;rendered_id<=0;front_wh<=0;
   pending_valid<=0;staged_front<=0;vsold<=0;adopting<=0;native_view<=0;
   last_generation<=32'hffffffff;last_rgb<=0;last_ground<=0;last_heat<=0;
   ticks<=0;raster_ticks<=0;commit_wait<=0;
   depth_base<=0;for(i=0;i<36;i=i+1)cfg[i]<=0;
   for(i=0;i<8;i=i+1)bases[i]<=0;display_bytes<=0;display_underflows<=0;
   for(i=0;i<15;i=i+1)perf[i]<=0;for(i=0;i<6;i=i+1)begin diagnostic_base[i]<=0;diagnostic_frame[i]<=0;end
  end else begin
   start<=0;vsold<=vsync;
   if(vsync&&!vsold&&pending_valid)begin
    front_address<=pending_address;layer_address<=pending_layer;front_wh<=pending_wh;native_view<=pending_native;
    adopting_id<=pending_id;adopting<=1;pending_valid<=0;
   end
   if(scan_adopted&&adopting)begin presented_id<=adopting_id;adopting<=0;end
   if(s_axi_bvalid&&s_axi_bready)s_axi_bvalid<=0;
   if(s_axi_awvalid&&s_axi_awready)begin awaddr<=s_axi_awaddr;aw_pending<=1;end
   if(s_axi_wvalid&&s_axi_wready)begin wdata<=s_axi_wdata;wstrb<=s_axi_wstrb;w_pending<=1;end
   if(aw_pending&&w_pending&&!s_axi_bvalid)begin
    aw_pending<=0;w_pending<=0;s_axi_bvalid<=1;s_axi_bresp<=0;
    if(awaddr==0)begin
     if(wstrb[0])begin
      if(wdata[1])irq<=0;quiet<=wdata[2];
      if(wdata[0])begin if(state!=IDLE||quiet||fatal)s_axi_bresp<=2;else start<=1;end
     end
    end else if(awaddr==152)begin if(wstrb==15)staged_front<=wdata;else s_axi_bresp<=2;end
    else if(awaddr==148)begin
     if(wstrb!=15||pending_valid)s_axi_bresp<=2;
     else begin pending_address<=staged_front;pending_layer<=staged_layer;pending_id<=wdata;pending_wh<=cfg[10];pending_native<=cfg[21][2];pending_valid<=1;end
    end else if(awaddr==380||awaddr==384||awaddr==396)begin
     if(quiet||wstrb!=15)s_axi_bresp<=2;
     else if(awaddr==380)cursor_position<=wdata;else if(awaddr==384)staged_layer<=wdata;else layer_address<=staged_layer;
    end else if(state!=IDLE)s_axi_bresp<=2;
    else if(awaddr==448)begin if(state==IDLE&&wstrb==15)depth_base<=wdata;else s_axi_bresp<=2;end
    else if(awaddr>=8&&awaddr<=140)begin
     for(k=0;k<4;k=k+1)if(wstrb[k])cfg[awaddr>>2][k*8+:8]<=wdata[k*8+:8];
    end else s_axi_bresp<=2;
   end
   if(s_axi_rvalid&&s_axi_rready)s_axi_rvalid<=0;
   if(s_axi_arvalid&&s_axi_arready)begin s_axi_rdata<=read_register(s_axi_araddr);s_axi_rvalid<=1;end
   if(state!=IDLE)ticks<=ticks+1;
   if(state==RENDER||state==DRAIN)raster_ticks<=raster_ticks+1;
   if(state==FINISH||(state==FAILED&&(fatal||bus_idle)))begin
    for(i=0;i<6;i=i+1)diagnostic_frame[i]<=diagnostic_sum[i]-diagnostic_base[i];
    perf[0]<=ticks+1;perf[1]<=prep_cycles;perf[2]<=bin_cycles;perf[3]<=raster_ticks;
    perf[4]<=sum_misses-bases[0];perf[5]<=sum_cache_wait-bases[1];perf[6]<=0;
    perf[7]<=ddr_wait-bases[2];perf[8]<=sum_mix_wait-bases[7];
    perf[9]<=read_bytes-bases[3];perf[10]<=write_bytes-bases[4];
    perf[11]<=sum_pixels-bases[5];perf[12]<=sum_tiles-bases[6];
    perf[13]<=scan_read_bytes-display_start;perf[14]<=scan_underflows-underflow_start;
   end
   if((bus_fault||(|engine_error))&&state!=FAILED&&state!=IDLE)begin fatal<=1;frame_error<=2;state<=FAILED;end
   else case(state)
    IDLE:if(start)begin
     ticks<=0;raster_ticks<=0;commit_wait<=0;frame_error<=0;round_robin<=0;
     for(i=0;i<6;i=i+1)diagnostic_base[i]<=diagnostic_sum[i];
     bases[0]<=sum_misses;bases[1]<=sum_cache_wait;bases[2]<=ddr_wait;
     bases[3]<=read_bytes;bases[4]<=write_bytes;bases[5]<=sum_pixels;bases[6]<=sum_tiles;
     bases[7]<=sum_mix_wait;display_start<=scan_read_bytes;underflow_start<=scan_underflows;
     nx<=cfg[10][11:5];total_tiles<=(cfg[10][11:0]>>5)*((cfg[10][27:16]+31)>>5);
     next_tile<=0;tx<=0;ty<=0;
     if(!cfg[10][11:0]||cfg[10][11:0]>1280||cfg[10][4:0]!=0||!cfg[10][27:16]||
      cfg[10][27:16]>720||cfg[10][16]||cfg[11]!=(cfg[10][11:0]<<2))begin frame_error<=1;state<=FAILED;end
     else state<=PREP_START;
    end
    PREP_START:begin last_generation<=cfg[23];last_rgb<=cfg[12];last_ground<=cfg[14];last_heat<=cfg[16];state<=PREP_WAIT;end
    PREP_WAIT:if(binner_done)begin if(binner_error!=0)begin frame_error<=binner_error;state<=FAILED;end else state<=RENDER;end
    RENDER:begin
     if(|offer)begin
      next_tile<=next_tile+1;round_robin<=offer[0];
      if(tx+1==nx)begin tx<=0;ty<=ty+1;end else tx<=tx+1;
     end
     if(next_tile==total_tiles)state<=DRAIN;
    end
    DRAIN:if(&engine_idle&&bus_idle)state<=FINISH;
    FINISH:begin rendered_id<=cfg[20];irq<=1;state<=IDLE;
     display_bytes<=scan_read_bytes-display_start;display_underflows<=scan_underflows-underflow_start;end
    FAILED:if(fatal||bus_idle)begin rendered_id<=cfg[20];irq<=1;state<=IDLE;end
    default:state<=IDLE;
   endcase
  end
 end
endmodule
