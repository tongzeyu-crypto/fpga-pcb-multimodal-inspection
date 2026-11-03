module g3_line_ram #(parameter AW=11)(input logic wclk,we,input logic [AW-1:0] wa,
 input logic [31:0] wd,input logic rclk,re,input logic [AW-1:0] ra,output logic [31:0] q);
 (* ram_style="block" *) logic [31:0] mem[0:(1<<AW)-1];
 always @(posedge wclk)if(we)mem[wa]<=wd;
 always @(posedge rclk)if(re)q<=mem[ra];
endmodule
