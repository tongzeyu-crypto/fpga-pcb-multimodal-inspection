`timescale 1ns/1ps
module tb_device_generation;
 logic [31:0] scan_active_layer=0,scan_active_cursor=0,cursor_position,layer_address;logic scan_ui_drained=1,ui_quiet;
 logic clk=0;always #5 clk=~clk;logic rstn=0,vsync=0,irq,scan_adopted=0,native_view;
 logic [63:0] scan_read_bytes=0;logic [31:0] scan_underflows=0;
 logic [8:0] s_axi_awaddr=0,s_axi_araddr=0;logic s_axi_awvalid=0,s_axi_awready;
 logic [31:0] s_axi_wdata=0,s_axi_rdata;logic [3:0] s_axi_wstrb=15;
 logic s_axi_wvalid=0,s_axi_wready,s_axi_bvalid,s_axi_bready=1,s_axi_arvalid=0,s_axi_arready,s_axi_rvalid,s_axi_rready=1;
 logic [1:0] s_axi_bresp,s_axi_rresp;
 logic [2:0] m_axi_arid,m_axi_rid,m_axi_arsize,m_axi_awsize;
 logic [31:0] m_axi_araddr,m_axi_awaddr;logic [7:0] m_axi_arlen,m_axi_awlen,m_axi_wstrb;
 logic [1:0] m_axi_arburst,m_axi_awburst,m_axi_awid,m_axi_bid,m_axi_bresp=0,m_axi_rresp=0;
 logic m_axi_arvalid,m_axi_arready,m_axi_awvalid,m_axi_awready,m_axi_rvalid=0,m_axi_rready,m_axi_rlast;
 logic [63:0] m_axi_rdata,m_axi_wdata;logic m_axi_wlast,m_axi_wvalid,m_axi_wready,m_axi_bvalid=0,m_axi_bready;
 logic [31:0] front_address,presented_id,rendered_id,front_wh;
 g3_device dut(.*);
 logic [63:0] mem[0:32767];logic [31:0] expected[0:4095];logic [15:0] expected_id[0:4095],expected_depth[0:4095];logic [4095:0] depth_seen=0;
 logic [31:0] fixture_matrix[0:11];
 logic [7:0] active=0;logic [31:0] ra[0:7];logic [8:0] remain[0:7];
 logic [1:0] waid[0:3];logic [31:0] wa[0:3];logic [8:0] wn[0:3];
 integer wh=0,wt=0,wcount=0,cycle=0,choose,i,k,n,errors=0,fd;
 logic [3:0] responses=0;integer bchoose;logic accepted_aw,accepted_w;
 logic fault_seen=0;integer invalidate_count=0,before_invalidates,frame_index;
 always @(posedge clk)if(rstn&&dut.source_changed)invalidate_count=invalidate_count+1;
 logic read_accepted=0;
 always @(negedge clk)begin
  cycle=cycle+1;
  m_axi_arready=cycle%5!=0;m_axi_awready=wcount<4&&cycle%4!=0;m_axi_wready=wcount>0&&cycle%3!=0;
  if(!m_axi_rvalid||read_accepted)begin
   choose=-1;for(integer ri=0;ri<8;ri=ri+1)if(active[(cycle+ri)%8]&&choose<0)choose=(cycle+ri)%8;
   m_axi_rvalid=choose>=0&&cycle%7!=0;
   if(m_axi_rvalid)begin m_axi_rid=choose;m_axi_rdata=mem[ra[choose]>>3];m_axi_rlast=remain[choose]==1;end
  end
  if(!m_axi_bvalid||m_axi_bready)begin
   bchoose=-1;for(integer bi=0;bi<4;bi=bi+1)if(responses[bi]&&bchoose<0)bchoose=bi;
   m_axi_bvalid=bchoose>=0;if(m_axi_bvalid)m_axi_bid=bchoose;
  end
 end
 always @(posedge clk)if(rstn)begin
  read_accepted<=m_axi_rvalid&&m_axi_rready;
  if((dut.bus_fault||(|dut.engine_error))&&!fault_seen)begin
   fault_seen<=1;
   $display("FAULT cycle=%0d bus=%b engines=%b prep=%d geom=%d refs=%d",cycle,dut.bus_fault,dut.engine_error,dut.binner.state,dut.geometry_count,dut.reference_count);
   $display("ENGINE0 state=%d reader=%d index=%d reader_err=%b shader_err=%b resolver_err=%b",dut.engines[0].active_engine.engine.state,dut.engines[0].active_engine.engine.reader.state,dut.engines[0].active_engine.engine.reader.index,dut.engines[0].active_engine.engine.reader_error,dut.engines[0].active_engine.engine.shader_error,dut.engines[0].active_engine.engine.resolve_error);
  end
  if(m_axi_arvalid&&m_axi_arready)begin
   if(active[m_axi_arid])$fatal(1,"read ID reused");
   if(m_axi_araddr[2:0]||m_axi_araddr[11:0]+(m_axi_arlen+1)*8>4096)$fatal(1,"read burst boundary");
   active[m_axi_arid]<=1;ra[m_axi_arid]<=m_axi_araddr;remain[m_axi_arid]<=m_axi_arlen+1;
  end
  if(m_axi_rvalid&&m_axi_rready)begin
   ra[m_axi_rid]<=ra[m_axi_rid]+8;remain[m_axi_rid]<=remain[m_axi_rid]-1;
   if(m_axi_rlast)active[m_axi_rid]<=0;
  end
  accepted_aw=m_axi_awvalid&&m_axi_awready;accepted_w=m_axi_wvalid&&m_axi_wready;
  if(accepted_aw)begin
   wa[wt]<=m_axi_awaddr;waid[wt]<=m_axi_awid;wn[wt]<=m_axi_awlen+1;wt<=(wt+1)%4;
   if(m_axi_awaddr[2:0]||m_axi_awaddr[11:0]+(m_axi_awlen+1)*8>4096)$fatal(1,"write burst boundary");
  end
  if(accepted_w)begin
   for(k=0;k<8;k=k+1)if(m_axi_wstrb[k])mem[wa[wh]>>3][k*8+:8]<=m_axi_wdata[k*8+:8];
   wa[wh]<=wa[wh]+8;wn[wh]<=wn[wh]-1;
   if(m_axi_wlast!=(wn[wh]==1))$fatal(1,"W ordering/last");
   if(m_axi_wlast)begin responses[waid[wh]]<=1;wh<=(wh+1)%4;end
  end
  case({accepted_aw,(accepted_w&&m_axi_wlast)})2'b10:wcount<=wcount+1;2'b01:wcount<=wcount-1;default:begin end endcase
  if(m_axi_bvalid&&m_axi_bready)responses[m_axi_bid]<=0;
 end
 // Inspect each completed tile's depth before it is discarded; depth is not
 // exported to DDR in production. Resolve WAIT_PIXEL is the synchronous BRAM result.
 generate for(genvar e=0;e<1;e=e+1)begin: depth_check
  integer position;
  always @(posedge clk)if(rstn&&dut.engines[e].active_engine.engine.resolve.state==2)begin
   position=(dut.engines[e].active_engine.engine.resolve.ty*32+dut.engines[e].active_engine.engine.resolve.row)*64+
     dut.engines[e].active_engine.engine.resolve.tx*32+dut.engines[e].active_engine.engine.resolve.pair*2;
   if(dut.engines[e].active_engine.engine.resolved[0][47:32]!==expected_depth[position]||
      dut.engines[e].active_engine.engine.resolved[1][47:32]!==expected_depth[position+1])$fatal(1,"resolved depth mismatch %0d",position);
   depth_seen[position]<=1;depth_seen[position+1]<=1;
  end
 end endgenerate
 task write_reg(input integer addr,input logic [31:0] value);
  begin
   @(negedge clk);s_axi_awaddr=addr;s_axi_wdata=value;s_axi_awvalid=1;s_axi_wvalid=1;
   do @(posedge clk);while(!s_axi_awready||!s_axi_wready);
   @(negedge clk);s_axi_awvalid=0;s_axi_wvalid=0;
   while(!s_axi_bvalid)@(negedge clk);
   if(s_axi_bresp)$fatal(1,"AXI Lite rejected %h",addr);
   @(negedge clk);
  end
 endtask
 initial begin
  $readmemh("FIXTURE_ROOT/memory.mem",mem);$readmemh("FIXTURE_ROOT/expected.mem",expected);
  $readmemh("FIXTURE_ROOT/expected-id.mem",expected_id);$readmemh("FIXTURE_ROOT/expected-depth.mem",expected_depth);
  $readmemh("FIXTURE_ROOT/matrix.mem",fixture_matrix);
  repeat(5)@(negedge clk);rstn=1;
  write_reg(8,32'h1000);write_reg(12,7);write_reg(16,32'h2000);write_reg(20,32'h10000);
  write_reg(24,1024);write_reg(28,32'h20000);write_reg(32,32'h24000);write_reg(36,32'h28000);
  write_reg(40,{16'd64,16'd64});write_reg(44,256);
  write_reg(48,32'h30000);write_reg(52,{16'd16,16'd16});
  write_reg(56,32'h32000);write_reg(60,{16'd16,16'd16});
  write_reg(64,32'h34000);write_reg(68,{16'd8,16'd8});
  write_reg(72,179);write_reg(76,32'hff0d1722);write_reg(80,1);write_reg(84,2);write_reg(88,32'h455);write_reg(92,1);
  for(i=0;i<12;i=i+1)write_reg(96+i*4,fixture_matrix[i]);
  write_reg(0,1);n=0;
  while(!irq&&n<500000)begin @(negedge clk);n=n+1;end
  if(!irq||dut.frame_error)begin
   $display("STALLED e0=%d sh=%d cache0=%d cache1=%d rused=%b wused=%b",dut.engines[0].active_engine.engine.state,dut.engines[0].active_engine.engine.shader.count,dut.engines[0].active_engine.engine.shader.caches[0].cache.state,dut.engines[0].active_engine.engine.shader.caches[1].cache.state,dut.memory.rused,dut.memory.wused);
   $display("CACHE0 addr=%h miss=%h candidate=%h valid=%b tags=%h expected=%h misses=%d",dut.engines[0].active_engine.engine.shader.caches[0].cache.addr[0],dut.engines[0].active_engine.engine.shader.caches[0].cache.miss_addr,dut.engines[0].active_engine.engine.shader.caches[0].cache.candidate_miss_addr,dut.engines[0].active_engine.engine.shader.caches[0].cache.hit,dut.engines[0].active_engine.engine.shader.caches[0].cache.tags[0],dut.engines[0].active_engine.engine.shader.caches[0].cache.addr[0][31:16],dut.engines[0].active_engine.engine.cache_misses);
   $fatal(1,"render incomplete error=%d state=%d",dut.frame_error,dut.state);
  end
  if(rendered_id!=1||active||wcount||responses)$fatal(1,"completion before DDR drained");
  fd=$fopen("FIXTURE_ROOT/actual.mem","w");
  for(i=0;i<4096;i=i+1)begin
   if(mem[(32'h20000>>3)+(i>>1)][(i%2)*32+:32]!==expected[i])begin
    if(errors<8)$display("PIXEL %0d got=%h expected=%h",i,mem[(32'h20000>>3)+(i>>1)][(i%2)*32+:32],expected[i]);errors=errors+1;end
   if(mem[(32'h24000>>3)+(i>>2)][(i%4)*16+:16]!==expected_id[i])begin
    if(errors<8)$display("OBJECT %0d",i);errors=errors+1;end
   $fdisplay(fd,"%08h",mem[(32'h20000>>3)+(i>>1)][(i%2)*32+:32]);
  end
  $fclose(fd);if(!(&depth_seen))$fatal(1,"incomplete depth coverage");if(errors)$fatal(1,"pixel/ID errors %d",errors);
  if(front_address!=0||presented_id!=0)$fatal(1,"render falsely marked presented");
  $display("RENDER_PASS_COUNTERS ticks=%0d geometry=%0d bin=%0d raster=%0d misses=%0d cache_wait=%0d mix_wait=%0d",dut.perf[0],dut.perf[1],dut.perf[2],dut.perf[3],dut.perf[4],dut.perf[5],dut.perf[8]);
  write_reg(380,32'h800a0014);if(cursor_position!=32'h800a0014)$fatal(1,"cursor did not update without render");
  write_reg(384,32'h38000);if(layer_address!=0)$fatal(1,"staged UI changed early");
  write_reg(152,32'h20000);write_reg(148,1);
  repeat(4)@(negedge clk);vsync=1;repeat(4)@(negedge clk);vsync=0;
  if(layer_address!=32'h38000)$fatal(1,"UI did not commit with frame");
  if(front_address!=32'h20000||presented_id!=0)$fatal(1,"adoption marked before scanout latched address");
  scan_adopted=1;@(negedge clk);scan_adopted=0;@(negedge clk);
  if(presented_id!=1)$fatal(1,"present fence");
  // Alternate retained textures, a new generation, then individual relocated
  // RGB / ground / thermal allocations. Content stays identical, so the same
  // independent full color/depth/object oracle applies to every frame.
  for(i=0;i<1024;i=i+1)mem[(32'h36000>>3)+i]=mem[(32'h30000>>3)+i];
  for(i=0;i<512;i=i+1)mem[(32'h38000>>3)+i]=mem[(32'h34000>>3)+i];
  for(i=0;i<1024;i=i+1)mem[(32'h3a000>>3)+i]=mem[(32'h32000>>3)+i];
  for(frame_index=2;frame_index<=7;frame_index=frame_index+1)begin
   write_reg(0,2);write_reg(80,frame_index);
   if(frame_index==3)write_reg(92,2);
   if(frame_index==4)write_reg(48,32'h36000);
   if(frame_index==5)write_reg(56,32'h3a000);
   if(frame_index==6)write_reg(64,32'h38000);
   before_invalidates=invalidate_count;depth_seen=0;
   write_reg(0,1);n=0;
   while(!irq&&n<500000)begin @(negedge clk);n=n+1;end
   if(!irq||dut.frame_error||rendered_id!=frame_index||active||wcount||responses)$fatal(1,"repeat frame not complete %0d",frame_index);
   if(invalidate_count-before_invalidates!=((frame_index>=3&&frame_index<=6)?1:0))$fatal(1,"wrong invalidation count frame=%0d count=%0d",frame_index,invalidate_count-before_invalidates);
   if(!(&depth_seen))$fatal(1,"repeat depth coverage");
   for(i=0;i<4096;i=i+1)begin
    if(mem[(32'h20000>>3)+(i>>1)][(i%2)*32+:32]!==expected[i])$fatal(1,"repeat pixel %0d frame %0d",i,frame_index);
    if(mem[(32'h24000>>3)+(i>>2)][(i%4)*16+:16]!==expected_id[i])$fatal(1,"repeat ID %0d",i);
   end
   $display("TEXTURE_GENERATION_FRAME frame=%0d invalidates=%0d pixels=4096 exact=1",frame_index,invalidate_count-before_invalidates);
  end
  $display("TB_DEVICE_GENERATION_PASS frames=7 pixels_each=4096 unchanged_generation=pass replaced_generation=pass rgb_ground_heat_relocation=pass");$finish;
 end
 initial begin #10000000;$fatal(1,"watchdog");end
endmodule
