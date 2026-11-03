// World and matrix coefficients Q16.16. Screen outputs Q12.4; Z is UNORM16.
// A shared MAC bounds DSP usage. PS uploads one orthographic matrix per view.
module gfx_vertex(input logic clk,rstn,input logic in_valid,output logic in_ready,
 input logic signed [31:0] x,y,z,input logic signed [31:0] matrix [0:11],
 output logic out_valid,input logic out_ready,output logic signed [15:0] sx,sy,
 output logic [15:0] depth,output logic overflow);
 logic busy;logic [1:0] row,col,phase;logic signed [31:0] v[0:3];logic signed [63:0] acc,prod;
 logic signed [31:0] operand_a,operand_b;
 always_comb in_ready=!busy&&!out_valid;
 function automatic signed [15:0] screen(input logic signed [63:0] n);
  logic signed [63:0] t;begin t=n>>>28;screen=t>32767?16'sh7fff:t< -32768?16'sh8000:t[15:0];end
 endfunction
 always_ff @(posedge clk)begin
  if(!rstn)begin busy<=0;out_valid<=0;overflow<=0;row<=0;col<=0;phase<=0;acc<=0;sx<=0;sy<=0;depth<=0;end else begin
   if(out_valid&&out_ready)out_valid<=0;
   if(in_valid&&in_ready)begin v[0]<=x;v[1]<=y;v[2]<=z;v[3]<=32'sh10000;busy<=1;row<=0;col<=0;phase<=0;acc<=0;overflow<=0;end
   else if(busy)begin
    if(phase==0)begin operand_a<=v[col];operand_b<=matrix[{row,col}];phase<=1;end
    else if(phase==1)begin prod<=$signed(operand_a)*$signed(operand_b);phase<=2;end
    else if(phase==2)begin acc<=acc+prod;if(col==3)phase<=3;else begin col<=col+1;phase<=0;end end
    else begin
     if(row==0)begin sx<=screen(acc);if((acc>>>28)>32767||(acc>>>28)< -32768)overflow<=1;end
     if(row==1)begin sy<=screen(acc);if((acc>>>28)>32767||(acc>>>28)< -32768)overflow<=1;end
     if(row==2)begin depth<=(acc>>>16)<0?0:(acc>>>16)>65535?16'hffff:acc[31:16];busy<=0;out_valid<=1;end
     row<=row+1;col<=0;acc<=0;phase<=0;
    end
   end
  end
 end
endmodule
