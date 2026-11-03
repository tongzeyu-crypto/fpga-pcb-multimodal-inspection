// Shared serial arithmetic for PSD normalization, band RMS and image operators.
// op0: unsigned128 / unsigned96; op1: unsigned64 * unsigned32; op2: isqrt64.
module pcb_scalar(input wire clk,rstn,start,input wire [1:0] op,
 input wire [127:0] a,input wire [95:0] b,
 output reg busy=0,done=0,error=0,output reg [127:0] value=0);
 reg [1:0] operation;reg [7:0] left;
 reg [127:0] dividend,quotient;
 reg [95:0] divisor,product,multiplicand;reg [31:0] multiplier;
 reg [96:0] remainder;
 reg [63:0] root,radicand,sqrt_bit;
 wire [96:0] trial={remainder[95:0],dividend[127]};
 wire subtract=trial>={1'b0,divisor};
 always @(posedge clk)begin
  if(!rstn)begin busy<=0;done<=0;error<=0;value<=0;end
  else begin
   done<=0;
   if(start&&!busy)begin
    operation<=op;busy<=1;error<=0;
    case(op)
     0:begin dividend<=a;divisor<=b;remainder<=0;quotient<=0;left<=128;if(b==0)begin error<=1;busy<=0;done<=1;value<=0;end end
     1:begin product<=0;multiplicand<={32'b0,a[63:0]};multiplier<=b[31:0];left<=32;end
     2:begin root<=0;radicand<=a[63:0];sqrt_bit<=64'h4000000000000000;left<=32;end
     default:begin error<=1;busy<=0;done<=1;end
    endcase
   end else if(busy)begin
    left<=left-1;
    case(operation)
     0:begin
      dividend<=dividend<<1;remainder<=subtract?trial-{1'b0,divisor}:trial;quotient<={quotient[126:0],subtract};
      if(left==1)begin value<={quotient[126:0],subtract};done<=1;busy<=0;end
     end
     1:begin
      if(multiplier[0])product<=product+multiplicand;
      multiplier<=multiplier>>1;multiplicand<=multiplicand<<1;
      if(left==1)begin value<={32'b0,(multiplier[0]?product+multiplicand:product)};done<=1;busy<=0;end
     end
     2:begin
      if(radicand>=root+sqrt_bit)begin radicand<=radicand-root-sqrt_bit;root<=(root>>1)+sqrt_bit;end
      else root<=root>>1;
      sqrt_bit<=sqrt_bit>>2;
      if(left==1)begin value<={64'b0,(radicand>=root+sqrt_bit?(root>>1)+sqrt_bit:root>>1)};done<=1;busy<=0;end
     end
    endcase
   end
  end
 end
endmodule
