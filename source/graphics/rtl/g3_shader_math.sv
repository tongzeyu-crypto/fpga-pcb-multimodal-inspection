// Filtering/compositing runs independently from the next texture request.
 module g3_shader_math #(parameter integer LANES=2)(input logic clk,rstn,
 input logic in_valid,output logic in_ready,input logic [1:0] in_mask,
 input logic [9:0] in_index,input logic [15:0] in_z[0:1],in_u[0:1],in_v[0:1],input logic [63:0] in_old[0:1],
 input logic [31:0] rgba,input logic textured,thermal_on,sprite,input logic [7:0] alpha,
 input logic [31:0] in_samples[0:1][0:7],input logic [7:0] in_fx[0:3],in_fy[0:3],
 output logic idle,output logic out_valid,input logic out_ready,output logic [1:0] out_mask,
 output logic [9:0] out_index,output logic [15:0] out_z[0:1],
 output logic [63:0] out_old[0:1],output logic [31:0] out_color[0:1],output logic out_sprite);
 import g3_pkg::*;
 // Thirteen globally stallable stages. Multiply inputs, products and rounding are
 // separate registers; the exact 8-bit interpolation rounding is preserved.
 logic [12:0] valid;wire advance=!valid[12]||out_ready;
 typedef struct packed {logic [1:0] mask;logic [9:0] index;logic [31:0] rgba;logic tex,heat,spr;logic [7:0] weight;logic [31:0] z;logic [127:0] old;} meta_t;
 meta_t meta[0:12];
 logic [31:0] samples0[0:1][0:7],horizontal3[0:3][0:1],filtered6[0:3];
 logic [7:0] fx0[0:3],fy[0:3][0:3];logic [15:0] u0[0:1],v0[0:1];
 logic signed [24:0] hd1[0:3][0:1][0:1],vd4[0:3][0:1];
 (* use_dsp="yes" *) logic signed [33:0] hp2[0:3][0:1][0:1],vp5[0:3][0:1];
 logic [15:0] ha1[0:3][0:1][0:1],ha2[0:3][0:1][0:1],va4[0:3][0:1],va5[0:3][0:1];
 logic hn1[0:3][0:1][0:1],hn2[0:3][0:1][0:1],vn4[0:3][0:1],vn5[0:3][0:1];
 logic [7:0] hf1[0:3],vf4[0:3];
 (* use_dsp="yes" *)logic [33:0] rx1[0:1],ry1[0:1];(* use_dsp="no" *) logic [34:0] rsum2[0:1];logic [7:0] radial[3:10][0:1];
 logic [31:0] base7[0:1],heat7[0:1],first10[0:1],second10[0:1],first11[0:1],result12[0:1];(* use_dsp="yes", keep="true" *) logic [31:0] tail_product11[0:1][0:1];logic [7:0] alpha8[0:1];logic [31:0] base8[0:1],heat8[0:1];(* use_dsp="no", keep="true" *) logic [15:0] alpha_product7[0:1];
 (* use_dsp="yes", keep="true" *) logic [31:0] scale_product9[0:1][0:1][0:1];logic [7:0] opacity9[0:1];
 function automatic [7:0] rounded255(input logic [15:0] p);
  (* use_dsp="no" *) logic [15:0] a,b;begin a=p+16'd128;b=a+(a>>8);rounded255=b[15:8];end
 endfunction
 function automatic signed [24:0] delta2(input logic [15:0] a,b);
  logic signed [8:0] d0,d1;begin d0=$signed({1'b0,b[7:0]})-$signed({1'b0,a[7:0]});d1=$signed({1'b0,b[15:8]})-$signed({1'b0,a[15:8]});delta2=($signed(d1)*25'sd65536)+$signed(d0);end
 endfunction
 function automatic [15:0] rounded2(input logic [15:0] a,input logic signed [33:0] p,input logic negative);
  logic [8:0] round_hi;begin
   // Low signed-product correction is a multiple of 256 and vanishes in
   // the final byte. The high lane receives the low-product borrow.
   round_hi={1'b0,p[23:16]}+negative+9'd128;
   rounded2[7:0]=a[7:0]+p[15:8]+p[7];rounded2[15:8]=a[15:8]+p[31:24]+round_hi[8];
  end
 endfunction
 function automatic [15:0] scale2(input logic [15:0] a,input logic [7:0] f);
  logic [23:0] packed_a;(* use_dsp="yes" *)logic [31:0] product;
  begin packed_a={a[15:8],8'b0,a[7:0]};product=packed_a*f;scale2={div255({2'b0,product[31:16]}),div255({2'b0,product[15:0]})};end
 endfunction
 function automatic [31:0] scale4(input logic [31:0] a,input logic [7:0] f);
  begin scale4={scale2(a[31:16],f),scale2(a[15:0],f)};end
 endfunction
 function automatic [31:0] scale4_lut(input logic [31:0] a,input logic [7:0] f);
  (* use_dsp="no" *)logic [15:0] product;integer k;begin for(k=0;k<4;k=k+1)begin product=a[k*8+:8]*f;scale4_lut[k*8+:8]=div255({2'b0,product});end end
 endfunction
 function automatic [7:0] radius_sum(input logic [34:0] sum);
  logic [42:0] mult;begin mult=({8'b0,sum}<<8)-sum;radius_sum=sum>=35'd1073741824 ? 0 : 255-(mult>>30);end
 endfunction
 assign in_ready=advance;assign idle=valid==0;assign out_valid=valid[12];assign out_mask=meta[12].mask;assign out_index=meta[12].index;assign out_sprite=meta[12].spr;
 generate for(genvar p=0;p<LANES;p=p+1)begin assign out_z[p]=meta[12].z[p*16+:16];assign out_old[p]=meta[12].old[p*64+:64];assign out_color[p]=result12[p];end
 for(genvar p=LANES;p<2;p=p+1)begin assign out_z[p]=0;assign out_old[p]=0;assign out_color[p]=0;end endgenerate
 integer i,t,l,j,k;logic [15:0] aa,bb;logic [31:0] b,h,tail;logic [7:0] factor;logic signed [16:0] x,y;
 always_ff @(posedge clk)begin
  if(!rstn)valid<=0;
  else if(advance)begin
   valid<={valid[11:0],in_valid};for(i=1;i<13;i=i+1)meta[i]<=meta[i-1];
   for(i=1;i<4;i=i+1)for(t=0;t<2*LANES;t=t+1)fy[i][t]<=fy[i-1][t];
   for(i=4;i<11;i=i+1)for(l=0;l<LANES;l=l+1)radial[i][l]<=radial[i-1][l];
   begin
    meta[0].mask<=in_mask;meta[0].index<=in_index;meta[0].rgba<=rgba;meta[0].tex<=textured;meta[0].heat<=thermal_on&&alpha!=0;meta[0].spr<=sprite;meta[0].weight<=alpha;
    for(l=0;l<LANES;l=l+1)begin meta[0].z[l*16+:16]<=in_z[l];meta[0].old[l*64+:64]<=in_old[l];u0[l]<=in_u[l];v0[l]<=in_v[l];end
    for(t=0;t<2;t=t+1)for(j=0;j<4*LANES;j=j+1)samples0[t][j]<=in_samples[t][j];
    for(t=0;t<2*LANES;t=t+1)begin fx0[t]<=in_fx[t];fy[0][t]<=in_fy[t];end
   end
   begin
    for(t=0;t<2*LANES;t=t+1)begin hf1[t]<=fx0[t];for(j=0;j<2;j=j+1)for(k=0;k<2;k=k+1)begin
     aa=samples0[t/LANES][(t%LANES)*4+j*2][k*16+:16];bb=samples0[t/LANES][(t%LANES)*4+j*2+1][k*16+:16];
     hd1[t][j][k]<=delta2(aa,bb);ha1[t][j][k]<=aa;hn1[t][j][k]<=bb[7:0]<aa[7:0]&&fx0[t]!=0;
    end end
    for(l=0;l<LANES;l=l+1)begin x=$signed({1'b0,u0[l]})-17'sd32768;y=$signed({1'b0,v0[l]})-17'sd32768;rx1[l]<=x*x;ry1[l]<=y*y;end
   end
   begin
    for(t=0;t<2*LANES;t=t+1)for(j=0;j<2;j=j+1)for(k=0;k<2;k=k+1)begin hp2[t][j][k]<=hd1[t][j][k]*$signed({1'b0,hf1[t]});ha2[t][j][k]<=ha1[t][j][k];hn2[t][j][k]<=hn1[t][j][k];end
    for(l=0;l<LANES;l=l+1)rsum2[l]<=rx1[l]+ry1[l];
   end
   begin
    for(t=0;t<2*LANES;t=t+1)for(j=0;j<2;j=j+1)for(k=0;k<2;k=k+1)horizontal3[t][j][k*16+:16]<=rounded2(ha2[t][j][k],hp2[t][j][k],hn2[t][j][k]);
    for(l=0;l<LANES;l=l+1)radial[3][l]<=radius_sum(rsum2[l]);
   end
   for(t=0;t<2*LANES;t=t+1)begin vf4[t]<=fy[3][t];for(k=0;k<2;k=k+1)begin
    aa=horizontal3[t][0][k*16+:16];bb=horizontal3[t][1][k*16+:16];vd4[t][k]<=delta2(aa,bb);va4[t][k]<=aa;vn4[t][k]<=bb[7:0]<aa[7:0]&&fy[3][t]!=0;
   end end
   for(t=0;t<2*LANES;t=t+1)for(k=0;k<2;k=k+1)begin vp5[t][k]<=vd4[t][k]*$signed({1'b0,vf4[t]});va5[t][k]<=va4[t][k];vn5[t][k]<=vn4[t][k];end
   for(t=0;t<2*LANES;t=t+1)for(k=0;k<2;k=k+1)filtered6[t][k*16+:16]<=rounded2(va5[t][k],vp5[t][k],vn5[t][k]);
   for(l=0;l<LANES;l=l+1)begin
    b=meta[6].tex&&!meta[6].spr?filtered6[l]:meta[6].rgba;h=meta[6].tex&&meta[6].heat&&!meta[6].spr?filtered6[l+LANES]:0;
    base7[l]<=b;heat7[l]<=h;alpha_product7[l]<=h[31:24]*meta[6].weight;
   end
   for(l=0;l<LANES;l=l+1)begin base8[l]<=base7[l];heat8[l]<=heat7[l];alpha8[l]<=rounded255(alpha_product7[l]);end
   for(l=0;l<LANES;l=l+1)begin
    factor=meta[8].tex&&!meta[8].spr?255-alpha8[l]:base8[l][31:24];opacity9[l]<=base8[l][31:24];
    for(j=0;j<2;j=j+1)begin
     scale_product9[l][0][j]<={base8[l][j*16+8+:8],8'b0,base8[l][j*16+:8]}*factor;
     scale_product9[l][1][j]<={heat8[l][j*16+8+:8],8'b0,heat8[l][j*16+:8]}*meta[8].weight;
    end
   end
   for(l=0;l<LANES;l=l+1)begin
    for(j=0;j<2;j=j+1)begin
     first10[l][j*16+:16]<={rounded255(scale_product9[l][0][j][31:16]),rounded255(scale_product9[l][0][j][15:0])};
     second10[l][j*16+:16]<={rounded255(scale_product9[l][1][j][31:16]),rounded255(scale_product9[l][1][j][15:0])};
    end
    first10[l][31:24]<=opacity9[l];
   end
   for(l=0;l<LANES;l=l+1)begin
    tail=meta[10].spr?first10[l]:second10[l];factor=meta[10].spr?radial[10][l]:first10[l][31:24];first11[l]<=first10[l];
    for(j=0;j<2;j=j+1)tail_product11[l][j]<={tail[j*16+8+:8],8'b0,tail[j*16+:8]}*factor;
   end
   for(l=0;l<LANES;l=l+1)begin
    for(j=0;j<2;j=j+1)tail[j*16+:16]={rounded255(tail_product11[l][j][31:16]),rounded255(tail_product11[l][j][15:0])};
    if(meta[11].spr)result12[l]<=tail;else begin result12[l][31:24]<=first11[l][31:24];for(j=0;j<3;j=j+1)result12[l][j*8+:8]<=first11[l][j*8+:8]+tail[j*8+:8];end
   end
  end
 end
endmodule
