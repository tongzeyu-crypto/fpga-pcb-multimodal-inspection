`timescale 1ns/1ps
module tb_shader_credit;
 import g3_pkg::*;
 logic clk=0;always #5 clk=~clk;
 logic rstn=0,invalidate=0,in_valid,in_ready,idle,out_valid,out_ready,out_sprite,error;
 logic [1:0] in_mask,out_mask;logic [9:0] in_index,out_index;
 logic [15:0] in_z[0:1],in_u[0:1],in_v[0:1],out_z[0:1];
 logic [63:0] in_old[0:1],out_old[0:1];logic [31:0] rgba,out_color[0:1];
 logic textured,thermal_on,sprite;logic [7:0] alpha;
 logic [31:0] rgb_base=32'h10000,thermal_base=32'h40000;
 logic [11:0] rgb_width=256,rgb_height=128,thermal_width=64,thermal_height=32;
 logic [63:0] misses,stall_cycles,diagnostic[0:4];
 rd_req_t rd[0:1];rd_rsp_t rsp[0:1];logic [1:0] rd_ready,rsp_ready;
 logic [278:0] data[0:511],q;logic [63:0] expected[0:511];logic [31:0] memory[0:34815];
 logic [1:0] pending[0:1];logic [31:0] bases[0:1][0:1];integer beats[0:1][0:1];
 integer send_count=0,receive_count=0,tick=0,start_tick=0,end_tick=0,selected[0:1],i,j,offset;
 integer hold_until=0,peak_inflight=0,stall_checks=0; logic long_hold_done=0;
 logic enable_stream=1,checking=1,held_valid=0;logic [236:0] held,payload;
 g3_shader dut(.*);
 function automatic [31:0] memword(input logic[31:0] a);
  begin if(a>=32'h10000&&a<32'h30000)memword=memory[(a-32'h10000)>>2];
   else if(a>=32'h40000&&a<32'h42000)memword=memory[32768+((a-32'h40000)>>2)];
   else begin memword=32'hxxxxxxxx;$fatal(1,"invalid texture address %h",a);end end
 endfunction
 assign payload={out_mask,out_index,out_sprite,out_z[1],out_z[0],out_old[1],out_old[0],out_color[1],out_color[0]};
 always @(negedge clk)begin
  tick=tick+1;
  if(!long_hold_done&&receive_count>=128&&out_valid)begin long_hold_done=1;hold_until=tick+96;end
  out_ready=(tick>=hold_until)&&(receive_count<128||(tick%7!=0&&tick%11!=0));
  in_valid=rstn&&enable_stream&&send_count<512;q=data[send_count%512];in_mask=q[1:0];in_index=q[11:2];offset=12;
  for(i=0;i<2;i=i+1)in_z[i]=q[offset+i*16+:16];offset=offset+32;
  for(i=0;i<2;i=i+1)in_u[i]=q[offset+i*16+:16];offset=offset+32;
  for(i=0;i<2;i=i+1)in_v[i]=q[offset+i*16+:16];offset=offset+32;
  for(i=0;i<2;i=i+1)in_old[i]=q[offset+i*64+:64];offset=offset+128;
  rgba=q[offset+:32];offset=offset+32;textured=q[offset];thermal_on=q[offset+1];sprite=q[offset+2];offset=offset+3;alpha=q[offset+:8];
  for(i=0;i<2;i=i+1)begin
   rd_ready[i]=tick%3!=0;rsp[i]='0;
   if(pending[i]!=0&&tick%4!=0)begin selected[i]=pending[i][1]?1:0;rsp[i].valid=1;rsp[i].token=selected[i];rsp[i].last=beats[i][selected[i]]==15;
    rsp[i].data={memword(bases[i][selected[i]]+beats[i][selected[i]]*8+4),memword(bases[i][selected[i]]+beats[i][selected[i]]*8)};end
  end
 end
 always @(posedge clk)begin
  if(!rstn)begin pending[0]<=0;pending[1]<=0;held_valid<=0;end
  else begin
   if(in_valid&&in_ready)send_count<=send_count+1;
   if(checking&&send_count-receive_count>peak_inflight)peak_inflight=send_count-receive_count;
   if(checking&&tick<hold_until&&out_valid&&!out_ready)stall_checks=stall_checks+1;
   for(integer c=0;c<2;c=c+1)begin
    if(rd[c].valid&&rd_ready[c])begin
     if(pending[c][rd[c].token])$fatal(1,"occupied response token");pending[c][rd[c].token]<=1;bases[c][rd[c].token]<=rd[c].addr;beats[c][rd[c].token]<=0;
    end
    if(rsp[c].valid&&rsp_ready[c])begin beats[c][rsp[c].token]<=beats[c][rsp[c].token]+1;if(rsp[c].last)pending[c][rsp[c].token]<=0;end
   end
   if(held_valid&&(!out_valid||payload!==held))begin
    $display("STALL_DETAIL recv=%0d valid=%b ready=%b held=%h payload=%h head=%b tail=%b count=%0d push=%b pop=%b",receive_count,out_valid,out_ready,held,payload,dut.math.head,dut.math.tail,dut.math.count,dut.math.push,dut.math.pop);
    $fatal(1,"backpressure changed payload");
   end
   held_valid<=out_valid&&!out_ready;held<=payload;
   if(error)$fatal(1,"shader cache error");
   if(out_valid&&out_ready&&checking)begin
    if(out_index!==receive_count[9:0]||out_mask!==data[receive_count][1:0]||out_sprite!==data[receive_count][270])$fatal(1,"metadata order");
    for(integer c=0;c<2;c=c+1)begin
     if(out_mask!=0&&out_color[c]!==expected[receive_count][c*32+:32])$fatal(1,"pixel %0d lane%0d got%h expected%h",receive_count,c,out_color[c],expected[receive_count][c*32+:32]);
     if(out_z[c]!==data[receive_count][12+c*16+:16]||out_old[c]!==data[receive_count][108+c*64+:64])$fatal(1,"metadata depth/old");
    end
    if(receive_count==16)start_tick=tick;
    if(receive_count==96)begin end_tick=tick;if(end_tick-start_tick>80)$fatal(1,"hit queue too slow %0d",end_tick-start_tick);end
    receive_count<=receive_count+1;
   end
  end
 end
 initial begin
  $readmemh("sim/stream-input.mem",data);$readmemh("sim/stream-expected.mem",expected);$readmemh("sim/stream-texture.mem",memory);
  if((^data[0])===1'bx||(^expected[511])===1'bx||(^memory[34815])===1'bx)$fatal(1,"missing fixture");
  repeat(5)@(negedge clk);rstn=1;
  wait(receive_count==512);@(negedge clk);if(!idle)$fatal(1,"pipeline not drained");
  if(stall_checks<80||peak_inflight<12)$fatal(1,"insufficient long backpressure coverage stalled=%0d peak=%0d",stall_checks,peak_inflight);
  $display("CREDIT_CHECK hold_cycles=%0d peak_inflight=%0d",stall_checks,peak_inflight);
  $display("STREAM_CHECK pairs=512 cycles=%0d hot_80_pair_cycles=%0d misses=%0d",tick,end_tick-start_tick,misses);
  // Inject work, force reset with requests/metadata in flight, then ensure no stale completion.
  checking=0;send_count=0;receive_count=0;held_valid=0;invalidate=1;
  @(negedge clk);invalidate=0;repeat(600)@(negedge clk);
  if(idle)$fatal(1,"reset trial did not fill pipeline");rstn=0;enable_stream=0;
  repeat(3)@(negedge clk);rstn=1;
  repeat(550)begin @(negedge clk);if(out_valid)$fatal(1,"reset leaked output");end
  if(!idle)$fatal(1,"reset drain failed");
  $display("TB_SHADER_CREDIT_PASS pairs=512 hot_pair_interval=1 reset=pass mixed_order=pass");$finish;
 end
 initial begin #10000000;$fatal(1,"watchdog");end
endmodule
