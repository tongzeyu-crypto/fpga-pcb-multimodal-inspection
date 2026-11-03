`timescale 1ns/1ps
module tb_shader_pair;
 logic clk=0;always #5 clk=~clk;logic rstn=0,in_valid=0,in_ready,idle,out_valid,out_ready=0,out_sprite;
 logic [1:0] in_mask,out_mask;logic [9:0] in_index,out_index;logic [15:0] in_z[0:1],in_u[0:1],in_v[0:1],out_z[0:1];
 logic [63:0] in_old[0:1],out_old[0:1];logic [31:0] rgba,out_color[0:1];logic textured,thermal_on,sprite;logic [7:0] alpha;
 logic [31:0] in_samples[0:1][0:7];logic [7:0] in_fx[0:3],in_fy[0:3];logic [854:0] data[0:1023];logic [63:0] expected[0:1023];
 logic enable_stream=1,checking=1;integer send_count=0,receive_count=0,tick=0,stalls=0,offset,p,l;logic [854:0] q;logic [63:0] held;logic held_valid=0;
 g3_shader_pair dut(.*);
 always @(negedge clk)begin
  tick=tick+1;out_ready=tick%7!=0&&tick%11!=0;
  in_valid=rstn&&enable_stream&&send_count<1024;q=data[send_count%1024];in_mask=q[1:0];in_index=q[11:2];offset=12;
  for(p=0;p<2;p=p+1)in_z[p]=q[offset+p*16+:16];offset=offset+32;
  for(p=0;p<2;p=p+1)in_u[p]=q[offset+p*16+:16];offset=offset+32;
  for(p=0;p<2;p=p+1)in_v[p]=q[offset+p*16+:16];offset=offset+32;
  for(p=0;p<2;p=p+1)in_old[p]=q[offset+p*64+:64];offset=offset+128;
  rgba=q[offset+:32];offset=offset+32;textured=q[offset];thermal_on=q[offset+1];sprite=q[offset+2];offset=offset+3;alpha=q[offset+:8];offset=offset+8;
  for(p=0;p<4;p=p+1)in_fx[p]=q[offset+p*8+:8];offset=offset+32;for(p=0;p<4;p=p+1)in_fy[p]=q[offset+p*8+:8];offset=offset+32;
  for(p=0;p<2;p=p+1)for(l=0;l<8;l=l+1)in_samples[p][l]=q[offset+(p*8+l)*32+:32];
 end
 always @(posedge clk)if(rstn)begin
  if(in_valid&&in_ready)send_count<=send_count+1;
  if(held_valid&&(!out_valid||{out_color[1],out_color[0]}!==held))$fatal(1,"output changed during backpressure");
  held_valid<=out_valid&&!out_ready;held<={out_color[1],out_color[0]};
  if(!in_ready)stalls<=stalls+1;
  if(out_valid&&out_ready&&checking)begin
   if(out_index!==receive_count[9:0]||out_mask!==data[receive_count][1:0])$fatal(1,"order/metadata");
   for(integer c=0;c<2;c=c+1)begin
    if(out_color[c]!==expected[receive_count][c*32+:32])$fatal(1,"pixel %0d lane %0d got %h expected %h",receive_count,c,out_color[c],expected[receive_count][c*32+:32]);
    if(out_z[c]!==data[receive_count][12+c*16+:16]||out_old[c]!==data[receive_count][108+c*64+:64])$fatal(1,"depth/old metadata");
   end
   receive_count<=receive_count+1;
  end
 end
 initial begin $readmemh("sim/math-input.mem",data);$readmemh("sim/math-expected.mem",expected);if((^data[0])===1'bx||(^expected[1023])===1'bx)$fatal(1,"fixture missing or unknown");repeat(4)@(negedge clk);rstn=1;
  wait(receive_count==1024);@(negedge clk);if(!idle)$fatal(1,"not drained");
  // Inject a new stream, reset with valid work still inside the six-stage pipe.
  checking=0;send_count=0;receive_count=0;held_valid=0;
  repeat(3)@(negedge clk);if(idle)$fatal(1,"reset test did not fill pipeline");
  rstn=0;enable_stream=0;repeat(2)@(negedge clk);rstn=1;held_valid=0;
  repeat(9)begin @(negedge clk);if(out_valid)$fatal(1,"reset leaked in-flight output");end
  if(!idle)$fatal(1,"reset did not drain valid bits");
  $display("TB_SHADER_PAIR_PASS pairs=1024 cycles=%0d stalls=%0d throughput_hit_pair_per_cycle=1",tick,stalls);$finish;
 end
 initial begin #1000000;$fatal(1,"watchdog");end
endmodule
