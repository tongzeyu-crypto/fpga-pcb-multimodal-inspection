// Restoring signed 64/32 divider: setup only, never in the pixel critical path.
module gfx_div(input logic clk,rstn,start,input logic signed [63:0] numerator,
 input logic [31:0] denominator,output logic busy,done,zero,output logic signed [63:0] quotient);
 logic [63:0] dividend,q;logic [32:0] remn;logic [31:0] divisor;logic negative;logic [6:0] count;
 logic [32:0] shifted;always_comb shifted={remn[31:0],dividend[63]};
 always_ff @(posedge clk) begin
  if(!rstn)begin busy<=0;done<=0;zero<=0;quotient<=0;end else begin
   done<=0;
   if(start&&!busy)begin
    zero<=denominator==0;
    if(denominator==0)begin quotient<=0;done<=1;end
    else begin negative<=numerator<0;dividend<=numerator<0?-numerator:numerator;divisor<=denominator;remn<=0;q<=0;count<=64;busy<=1;end
   end else if(busy)begin
    dividend<={dividend[62:0],1'b0};
    if(shifted>={1'b0,divisor})begin remn<=shifted-{1'b0,divisor};q<={q[62:0],1'b1};end
    else begin remn<=shifted;q<={q[62:0],1'b0};end
    count<=count-1;
    if(count==1)begin busy<=0;done<=1;quotient<=negative?-$signed({q[62:0],shifted>={1'b0,divisor}}):$signed({q[62:0],shifted>={1'b0,divisor}});end
   end
  end
 end
endmodule
