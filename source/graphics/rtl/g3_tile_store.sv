// Two tile pages, parity banks, ordered depth/blend pipeline with forwarding.
module g3_tile_store(input logic clk,rstn,
 input logic clear,input logic clear_page,input logic [8:0] clear_index,input logic [31:0] background,
 input logic query,input logic query_page,input logic [9:0] query_index,output logic query_ready,
 output logic [63:0] queried[0:1],
 input logic commit,input logic commit_page,input logic [9:0] commit_index,output logic commit_ready,busy,
 input logic [1:0] commit_mask,input logic [15:0] commit_z[0:1],input logic [63:0] old_pixel[0:1],
 input logic [15:0] object_id,input logic [31:0] color[0:1],input logic sprite,
 input logic resolve,input logic resolve_page,input logic [8:0] resolve_index,output logic [63:0] resolved[0:1]);
 import g3_pkg::*;
 logic [63:0] read0[0:1],read1[0:1],selected[0:1],merged[0:1],last_word[0:1],forwarded[0:1];
 logic last_valid,last_page,qpage,rpage,qforward;logic [9:0] last_index;
 logic [8:0] read_index0,read_index1;logic read_enable0,read_enable1;
 logic a_valid,a_page,a_sprite,b_valid,b_page,b_sprite;
 logic [9:0] a_index,b_index;logic [1:0] a_mask,b_mask;
 logic [15:0] a_z[0:1],b_z[0:1],a_object,b_object;
 logic [31:0] a_color[0:1],b_color[0:1];logic [63:0] a_base[0:1],b_base[0:1];
 logic [15:0] product[0:1][0:2];logic [9:0] channel_sum;
 // Two independent unsigned byte products in one 24x8 DSP multiply.
 // The 16-bit spacing prevents cross-lane carry; no precision is lost.
 (* use_dsp="yes", keep="true" *) logic [31:0] product_rb[0:1];
 (* use_dsp="yes", keep="true" *) logic [15:0] product_g[0:1];
 generate for(genvar lp=0;lp<2;lp=lp+1)begin: packed_blend
  assign product[lp][0]=product_rb[lp][15:0];
  assign product[lp][1]=product_g[lp];
  assign product[lp][2]=product_rb[lp][31:16];
 end endgenerate
 integer i,c;
 // Exact rounded division for byte products (0..65025). This form avoids
 // two wide carry chains in the blend -> forwarding -> DSP input path.
 function automatic [7:0] blend_div255(input logic [15:0] p);
  logic [9:0] s;begin
   s={2'b0,p[7:0]}+{2'b0,p[15:8]}+10'd128+{9'b0,p[7]};
   blend_div255=p[15:8]+s[9:8];
  end
 endfunction
 assign busy=a_valid||b_valid;
 // Only the first stage is unresolved. The last stage can be forwarded.
 assign query_ready=!clear&&!(a_valid&&a_page==query_page&&a_index==query_index)&&
  !(commit&&commit_ready&&commit_page==query_page&&commit_index==query_index);
 assign commit_ready=!clear&&!(a_valid&&a_page==commit_page&&a_index==commit_index);
 generate for(genvar p=0;p<2;p=p+1)begin: pages
  for(genvar lane=0;lane<2;lane=lane+1)begin: banks
   wire writing=(clear&&clear_page==p)||(b_valid&&b_page==p&&b_mask[lane]);
   wire clearing=clear&&clear_page==p;
   wire [8:0] wa=clearing?clear_index:b_index[9:1];
   wire [63:0] wd=clearing?{16'b0,16'hffff,background}:merged[lane];
   wire [63:0] read_q;
   g3_ram_sdp #(.WIDTH(64),.AW(9)) ram(.clk(clk),.we(writing),.wa(wa),.wd(wd),
    .re(p==0?read_enable0:read_enable1),.ra(p==0?read_index0:read_index1),.q(read_q));
   if(p==0)assign read0[lane]=read_q;else assign read1[lane]=read_q;
  end
 end endgenerate
 always_comb begin
  read_enable0=(query&&!query_page)||(resolve&&!resolve_page);
  read_enable1=(query&&query_page)||(resolve&&resolve_page);
  read_index0=query&&!query_page?query_index[9:1]:resolve_index;
  read_index1=query&&query_page?query_index[9:1]:resolve_index;
  for(integer lane=0;lane<2;lane=lane+1)begin
   queried[lane]=qforward?forwarded[lane]:(qpage?read1[lane]:read0[lane]);
   resolved[lane]=rpage?read1[lane]:read0[lane];
   merged[lane]=b_base[lane];
   if(b_mask[lane])begin
    merged[lane][31:24]=255;
    for(integer ch=0;ch<3;ch=ch+1)begin
     channel_sum=b_color[lane][ch*8+:8]+(b_sprite?b_base[lane][ch*8+:8]:blend_div255(product[lane][ch]));
     merged[lane][ch*8+:8]=channel_sum>255?255:channel_sum[7:0];
    end
    if(!b_sprite)merged[lane][63:32]={b_object,b_z[lane]};
   end
   selected[lane]=old_pixel[lane];
   if(last_valid&&last_page==commit_page&&last_index==commit_index)selected[lane]=last_word[lane];
   if(b_valid&&b_page==commit_page&&b_index==commit_index)selected[lane]=merged[lane];
  end
 end
 always_ff @(posedge clk)begin
  if(!rstn)begin a_valid<=0;b_valid<=0;last_valid<=0;qforward<=0;qpage<=0;rpage<=0;end
  else begin
   a_valid<=commit&&commit_ready;b_valid<=a_valid;last_valid<=b_valid;
   if(commit&&commit_ready)begin
    a_page<=commit_page;a_index<=commit_index;a_mask<=commit_mask;a_sprite<=sprite;a_object<=object_id;
    for(i=0;i<2;i=i+1)begin a_base[i]<=selected[i];a_z[i]<=commit_z[i];a_color[i]<=color[i];end
   end
   if(a_valid)begin
    b_page<=a_page;b_index<=a_index;b_sprite<=a_sprite;b_object<=a_object;
    for(i=0;i<2;i=i+1)begin
     b_base[i]<=a_base[i];b_z[i]<=a_z[i];b_color[i]<=a_color[i];
     b_mask[i]<=a_mask[i]&&a_color[i][31:24]!=0&&a_z[i]<=a_base[i][47:32];
     product_rb[i]<={a_base[i][23:16],8'b0,a_base[i][7:0]}*(8'd255-a_color[i][31:24]);
     product_g[i]<=a_base[i][15:8]*(8'd255-a_color[i][31:24]);
    end
   end
   if(b_valid)begin last_page<=b_page;last_index<=b_index;last_word[0]<=merged[0];last_word[1]<=merged[1];end
   if(query&&query_ready)begin
    qpage<=query_page;qforward<=0;
    if(last_valid&&last_page==query_page&&last_index==query_index)begin qforward<=1;forwarded[0]<=last_word[0];forwarded[1]<=last_word[1];end
    if(b_valid&&b_page==query_page&&b_index==query_index)begin qforward<=1;forwarded[0]<=merged[0];forwarded[1]<=merged[1];end
   end
   if(resolve)rpage<=resolve_page;
  end
 end
endmodule
