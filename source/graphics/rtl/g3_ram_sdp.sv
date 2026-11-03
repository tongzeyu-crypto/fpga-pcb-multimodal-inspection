// 64-bit tile words use the 72-bit simple-dual-port BRAM mode.
// A true-dual-port template would waste two 36-bit blocks per bank.
(* keep_hierarchy="yes" *)
module g3_ram_sdp #(parameter integer WIDTH=64,AW=9)(input logic clk,we,re,
 input logic [AW-1:0] wa,ra,input logic [WIDTH-1:0] wd,output logic [WIDTH-1:0] q);
 (* ram_style="block" *) logic [WIDTH-1:0] mem[0:(1<<AW)-1];
 always @(posedge clk)if(we)mem[wa]<=wd;
 always @(posedge clk)if(re)q<=mem[ra];
endmodule
