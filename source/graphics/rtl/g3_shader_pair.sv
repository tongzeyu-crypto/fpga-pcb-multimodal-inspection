module g3_shader_pair(input logic clk,rstn,
 input logic in_valid,output logic in_ready,input logic [1:0] in_mask,
 input logic [9:0] in_index,input logic [15:0] in_z[0:1],in_u[0:1],in_v[0:1],input logic [63:0] in_old[0:1],
 input logic [31:0] rgba,input logic textured,thermal_on,sprite,input logic [7:0] alpha,
 input logic [31:0] in_samples[0:1][0:7],input logic [7:0] in_fx[0:3],in_fy[0:3],
 output logic idle,output logic out_valid,input logic out_ready,output logic [1:0] out_mask,
 output logic [9:0] out_index,output logic [15:0] out_z[0:1],
 output logic [63:0] out_old[0:1],output logic [31:0] out_color[0:1],output logic out_sprite);


 // Two retirement slots break the tile-address hazard -> math DSP enable path.
 // Readiness depends only on registered occupancy. Neither valid data nor
 // metadata can be overwritten while the consumer is stalled.
 typedef struct packed {
  logic [1:0] mask; logic [9:0] index; logic [31:0] z;
  logic [127:0] old; logic [63:0] color; logic spr;
 } result_t;
 result_t retire0,retire1,current,pushed;
 logic head,tail;logic [1:0] count;logic core_idle,core_valid,core_ready;
 logic [1:0] core_mask;logic [9:0] core_index;
 logic [15:0] core_z[0:1];logic [63:0] core_old[0:1];
 logic [31:0] core_color[0:1];logic core_sprite;
 wire push=core_valid&&core_ready;wire pop=out_valid&&out_ready;
 assign core_ready=count<2;
 assign out_valid=count!=0;assign idle=core_idle&&count==0;
 assign current=head?retire1:retire0;
 assign pushed={core_mask,core_index,core_z[1],core_z[0],core_old[1],core_old[0],core_color[1],core_color[0],core_sprite};
 assign out_mask=current.mask;assign out_index=current.index;
 assign out_sprite=current.spr;
 generate for(genvar lane=0;lane<2;lane=lane+1)begin
  assign out_z[lane]=current.z[lane*16+:16];
  assign out_old[lane]=current.old[lane*64+:64];
  assign out_color[lane]=current.color[lane*32+:32];
 end endgenerate
 always_ff @(posedge clk)begin
  if(!rstn)begin count<=0;head<=0;tail<=0;end
  else begin
   case({push,pop})2'b10:count<=count+1;2'b01:count<=count-1;default:begin end endcase
   if(pop)head<=!head;
   if(push)begin
    tail<=!tail;
    if(tail)retire1<=pushed;else retire0<=pushed;
   end
  end
 end
 g3_shader_math #(.LANES(2)) core(.clk(clk),.rstn(rstn),.in_valid(in_valid),.in_ready(in_ready),
  .in_mask(in_mask),.in_index(in_index),.in_z(in_z),.in_u(in_u),.in_v(in_v),.in_old(in_old),
  .rgba(rgba),.textured(textured),.thermal_on(thermal_on),.sprite(sprite),.alpha(alpha),
  .in_samples(in_samples),.in_fx(in_fx),.in_fy(in_fy),.idle(core_idle),
  .out_valid(core_valid),.out_ready(core_ready),.out_mask(core_mask),.out_index(core_index),
  .out_z(core_z),.out_old(core_old),.out_color(core_color),.out_sprite(core_sprite));
endmodule
