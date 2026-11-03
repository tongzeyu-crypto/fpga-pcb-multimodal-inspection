// Canonical true dual-port template, separated from pixel arithmetic.
(* keep_hierarchy="yes" *)
module g3_ram_tdp #(parameter integer WIDTH=32,AW=10)(input logic clk,
 input logic ena,wea,input logic [AW-1:0] addra,input logic [WIDTH-1:0] dina,
 output logic [WIDTH-1:0] douta,
 input logic enb,web,input logic [AW-1:0] addrb,input logic [WIDTH-1:0] dinb,
 output logic [WIDTH-1:0] doutb);
 (* ram_style="block" *) logic [WIDTH-1:0] mem[0:(1<<AW)-1];
 always @(posedge clk)if(ena)begin
  if(wea)mem[addra]<=dina;
  douta<=mem[addra];
 end
 always @(posedge clk)if(enb)begin
  if(web)mem[addrb]<=dinb;
  doutb<=mem[addrb];
 end
endmodule
