// Preserve one multiplier across consumers with different rounding widths.
// Without the boundary, Vivado can clone DSPs when merging downstream adds.
(* keep_hierarchy="yes" *)
module g3_mul(input logic clk,ce,input logic signed [16:0] a,b,output logic signed [33:0] p);
 // Register the product (DSP PREG) rather than only its operands. Latency
 // remains one cycle, while rounding/saturation no longer shares the DSP path.
 (* use_dsp="yes" *) wire signed [33:0] value=a*b;
 always_ff @(posedge clk)if(ce)p<=value;
endmodule
