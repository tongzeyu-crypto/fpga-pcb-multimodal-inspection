// Compact source frames. Eight source-line slots cross the clock boundary;
// every source pixel is read once per output frame. Two separable /3 filters
// perform 3:2 bilinear enlargement. Native mode centers the source unchanged.
module g3_scanout #(
 parameter integer SW=1280,SH=720,W=1920,H=1080,HFP=88,HS=44,HBP=148,VFP=4,VS=5,VBP=36,
 parameter integer AW=$clog2(SW*2)
)(input logic clk,rstn,pclk,pixel_rstn,input logic [31:0] front_address,
 input logic [31:0] cursor_position,layer_address,input logic ui_quiet,
 output logic [31:0] active_layer,active_cursor,output logic ui_drained,
 input logic native_view,output logic present_window,adopted,fault,
 output logic [31:0] displayed_address,underflow_frames,output logic [63:0] read_bytes,
 output logic [23:0] video_rgb,output logic video_hsync,video_vsync,video_de,
 output logic [31:0] m_axi_araddr,output logic [7:0] m_axi_arlen,
 output logic [2:0] m_axi_arsize,output logic [1:0] m_axi_arburst,
 output logic m_axi_arvalid,input logic m_axi_arready,
 input logic [63:0] m_axi_rdata,input logic [1:0] m_axi_rresp,
 input logic m_axi_rlast,m_axi_rvalid,output logic m_axi_rready);
 localparam HT=W+HFP+HS+HBP,VT=H+VFP+VS+VBP;
 logic [11:0] x,y,sx,sy;logic [1:0] xp,yp;
 logic [3:0] wp,rp;
 (* dont_touch="yes" *) logic [3:0] wgray,rgray;
 (* ASYNC_REG="TRUE" *) logic [3:0] rg0,rg1,wg0,wg1;
 (* ASYNC_REG="TRUE" *) logic [2:0] vs_sync,uf_sync,mode_sync;
 logic [2:0] pixel_reset_sync;
 logic [10:0] source_line,word_in_line;
 logic [63:0] saved_rgb[0:15];logic overlay_pass;
 logic [31:0] burst_offset;logic [3:0] beat_index;
 logic [31:0] write_color[0:1];
 // AXI input -> operands -> products -> rounded destination -> saturated sum.
 // Publication of a source line follows its final RAM write, not AXI receipt.
 logic [3:0] blend_valid,blend_last;logic [AW-1:0] blend_addr[0:3];
 logic [3:0] blend_bank[0:3],blend_next[0:3];
 logic [31:0] blend_base[0:1],blend_layer[0:2][0:1],blend_result[0:1];
 (* use_dsp="yes" *) logic [15:0] blend_product[0:1][0:2];logic [7:0] blend_scaled[0:1][0:2];
 function automatic [7:0] round255(input logic [15:0] p);
  logic [15:0] t,q;begin t=p+16'd128;q=t+(t>>8);round255=q[15:8];end
 endfunction
 function automatic [7:0] sat_add8(input logic [7:0] a,b);
  logic [8:0] n;begin n={1'b0,a}+{1'b0,b};sat_add8=n[8]?8'd255:n[7:0];end
 endfunction
 logic cursor_toggle;
 (* ASYNC_REG="TRUE" *) logic [2:0] cursor_sync;
 logic cursor_seen;logic [31:0] pixel_cursor;
 logic [10:0] cursor_addr[0:3];logic [3:0] cursor_en;
 logic [31:0] cursor_q[0:3],composed[0:3];
 (* use_dsp="yes" *) logic [15:0] cursor_product[0:3][0:2];
 logic [7:0] cursor_scaled[0:3][0:2];logic [23:0] cursor_ink[0:1][0:3];
 logic [11:0] cursor_meta[0:1];
 logic c_valid,c_hs,c_vs,c_de,c_xpar,c_ypar,c_xlast,c_ylast;logic [1:0] c_fx,c_fy;
 logic [4:0] beats_left;logic [2:0] state;logic [5:0] blank_delay;
 logic reset_requested,mode_latched,underflow,underflow_toggle;
 logic [11:0] px,py,bottom,col1;logic in_view,available,re;
 logic [3:0] count,write_ptr;logic [2:0] row_for_bank[0:3];
 logic [AW-1:0] read_addr[0:3],write_addr;
 logic [31:0] bank_q[0:3];logic [3:0] wen;
 logic s1_valid,s1_hs,s1_vs,s1_de,s1_xpar,s1_ypar,s1_xlast,s1_ylast;
 logic [1:0] s1_fx,s1_fy,s2_fy;logic s2_valid,s2_hs,s2_vs,s2_de;
 logic [23:0] top_color,bottom_color;
 assign ui_drained=(ui_quiet || (active_layer==layer_address && active_cursor==cursor_position));
 function automatic [3:0] ungray(input logic [3:0] g);ungray={g[3],g[3]^g[2],g[3]^g[2]^g[1],g[3]^g[2]^g[1]^g[0]};endfunction
 function automatic [23:0] mix3(input logic [23:0] a,b,input logic [1:0] f);
  logic [9:0] n;integer c;begin
   for(c=0;c<3;c=c+1)begin
    n=a[c*8+:8]*(3-f)+b[c*8+:8]*f+1;
    mix3[c*8+:8]=n/3;
   end
  end
 endfunction
 // Register each Gray pointer at its source clock: no combinational XOR
 // or binary-carry glitches are allowed on the CDC launch path.
 assign write_ptr=ungray(wg1);assign count=write_ptr-rp;
 assign m_axi_arsize=3;assign m_axi_arburst=1;assign m_axi_arlen=15;
 assign m_axi_rready=state==2;
 always_comb begin
  in_view=x<W&&y<H;
  px=x;py=y;
  if(mode_sync[2])begin in_view=in_view&&x>=(W-SW)/2&&x<(W+SW)/2&&y>=(H-SH)/2&&y<(H+SH)/2;px=x-(W-SW)/2;py=y-(H-SH)/2;end
  available=count>=(sy==SH-1?1:2);
  re=in_view&&available&&!underflow;
  col1=sx==SW-1?sx:sx+1;
  bottom=sy==SH-1?rp[2:0]:(rp+1)&7;
  for(integer b=0;b<4;b=b+1)begin
   row_for_bank[b]=rp[0]==(b>>1)?rp[2:0]:bottom[2:0];
   read_addr[b]=(row_for_bank[b][2:1]*(SW/2))+((sx[0]==(b%2)?sx:col1)>>1);
  end
  write_addr=(wp[2:1]*(SW/2))+word_in_line;
  for(integer b=0;b<4;b=b+1)begin: cursor_lookup
   integer cx,cy;
   cx=(sx[0]==(b%2)?sx:col1)-pixel_cursor[10:0];
   cy=(rp[0]==(b>>1)?sy:(sy==SH-1?sy:sy+1))-pixel_cursor[25:16];
   cursor_en[b]=re&&pixel_cursor[31]&&cx>=0&&cx<32&&cy>=0&&cy<48;
   cursor_addr[b]=cy*32+cx;
  end
  for(integer c=0;c<2;c=c+1)write_color[c]=blend_result[c];
  wen=blend_valid[3]&&!fault?blend_bank[3]:4'b0000;
 end
 generate for(genvar b=0;b<4;b=b+1)begin: lines
  g3_line_ram #(.AW(AW)) ram(.wclk(clk),.we(wen[b]),.wa(blend_addr[3]),
   .wd(write_color[b%2]),.rclk(pclk),.re(re),.ra(read_addr[b]),.q(bank_q[b]));
  g3_cursor_rom cursor(.clk(pclk),.en(cursor_en[b]),.address(cursor_addr[b]),.q(cursor_q[b]));
 end endgenerate
 // Three pixel-clock stages retain exact premultiplied rounding. Sync and
 // sampling metadata receive the identical delay; source-line release is unchanged.
 always_ff @(posedge pclk)begin
  for(integer lane=0;lane<4;lane=lane+1)begin
   cursor_ink[0][lane]<=cursor_q[lane][23:0];cursor_ink[1][lane]<=cursor_ink[0][lane];
   composed[lane][31:24]<=8'hff;
   for(integer ch=0;ch<3;ch=ch+1)begin
    cursor_product[lane][ch]<=bank_q[lane][ch*8+:8]*(8'd255-cursor_q[lane][31:24]);
    cursor_scaled[lane][ch]<=round255(cursor_product[lane][ch]);
    composed[lane][ch*8+:8]<=sat_add8(cursor_scaled[lane][ch],cursor_ink[1][lane][ch*8+:8]);
   end
  end
 end
 always_ff @(posedge pclk)begin
  cursor_sync<={cursor_sync[1:0],cursor_toggle};
  pixel_reset_sync<={pixel_reset_sync[1:0],pixel_rstn};
  wg0<=wgray;wg1<=wg0;mode_sync<={mode_sync[1:0],mode_latched};
  if(!pixel_reset_sync[2])begin
   x<=0;y<=0;sx<=0;sy<=0;xp<=0;yp<=0;rp<=0;rgray<=0;underflow<=1;underflow_toggle<=0;
   s1_valid<=0;s1_hs<=0;s1_vs<=0;s1_de<=0;s2_valid<=0;s2_hs<=0;s2_vs<=0;s2_de<=0;
   video_rgb<=0;video_hsync<=0;video_vsync<=0;video_de<=0;
   pixel_cursor<=0;cursor_seen<=0;cursor_sync<=0;
   c_valid<=0;c_hs<=0;c_vs<=0;c_de<=0;cursor_meta[0]<=0;cursor_meta[1]<=0;
  end else begin
   // active_cursor is held for an entire frame; toggle crosses 3 flops during blanking.
   if(cursor_sync[2]!=cursor_seen)begin pixel_cursor<=active_cursor;cursor_seen<=cursor_sync[2];end
   cursor_meta[0]<={s1_valid,s1_xpar,s1_ypar,s1_xlast,s1_ylast,s1_fx,s1_fy,s1_hs,s1_vs,s1_de};
   cursor_meta[1]<=cursor_meta[0];
   {c_valid,c_xpar,c_ypar,c_xlast,c_ylast,c_fx,c_fy,c_hs,c_vs,c_de}<=cursor_meta[1];
   if(x==HT-1)begin x<=0;if(y==VT-1)y<=0;else y<=y+1;end else x<=x+1;
   if(x==0&&y==H+VFP)begin rp<=0;rgray<=0;sy<=0;yp<=0;end
   if(x==HT-1&&y==VT-1)begin
    sx<=0;sy<=0;xp<=0;yp<=0;underflow<=count<2;
    if(count<2)underflow_toggle<=~underflow_toggle;
   end else if(in_view&&!underflow&&!available)begin underflow<=1;underflow_toggle<=~underflow_toggle;end
   if(in_view)begin
    if(px==(mode_sync[2]?SW:W)-1)begin
     sx<=0;xp<=0;
     if(mode_sync[2]||yp!=0)begin sy<=sy+1;rp<=rp+1;rgray<=(rp+4'd1)^((rp+4'd1)>>1);end
     yp<=yp==2?0:yp+1;
    end else begin
     if(mode_sync[2]||xp!=0)sx<=sx+1;
     xp<=xp==2?0:xp+1;
    end
   end
   s1_valid<=re;s1_xpar<=sx[0];s1_ypar<=rp[0];s1_xlast<=sx==SW-1;s1_ylast<=sy==SH-1;
   s1_fx<=mode_sync[2]?0:xp==0?0:xp==1?2:1;s1_fy<=mode_sync[2]?0:yp==0?0:yp==1?2:1;
   s1_hs<=x>=W+HFP&&x<W+HFP+HS;s1_vs<=y>=H+VFP&&y<H+VFP+VS;s1_de<=x<W&&y<H;
   top_color<=mix3(composed[{c_ypar,c_xpar}][23:0],composed[{c_ypar,c_xpar^!c_xlast}][23:0],c_fx);
   bottom_color<=mix3(composed[{c_ypar^!c_ylast,c_xpar}][23:0],composed[{c_ypar^!c_ylast,c_xpar^!c_xlast}][23:0],c_fx);
   s2_valid<=c_valid;s2_fy<=c_fy;s2_hs<=c_hs;s2_vs<=c_vs;s2_de<=c_de;
   video_rgb<=s2_valid?mix3(top_color,bottom_color,s2_fy):0;
   video_hsync<=s2_hs;video_vsync<=s2_vs;video_de<=s2_de;
  end
 end
 always_ff @(posedge clk)begin
  if(!rstn)begin blend_valid<=0;blend_last<=0;end
  else begin
   blend_valid[0]<=state==2&&m_axi_rvalid&&m_axi_rready&&!fault&&m_axi_rresp==0&&m_axi_rlast==(beats_left==1)&&(active_layer==0||overlay_pass);
   blend_last[0]<=word_in_line==SW/2-1;
   blend_addr[0]<=write_addr;blend_bank[0]<=wp[0]?4'b1100:4'b0011;blend_next[0]<=wp+4'd1;
   for(integer p=1;p<4;p=p+1)begin
    blend_valid[p]<=blend_valid[p-1];blend_last[p]<=blend_last[p-1];
    blend_addr[p]<=blend_addr[p-1];blend_bank[p]<=blend_bank[p-1];blend_next[p]<=blend_next[p-1];
   end
   for(integer lane=0;lane<2;lane=lane+1)begin
    blend_base[lane]<=overlay_pass?saved_rgb[beat_index][lane*32+:32]:m_axi_rdata[lane*32+:32];
    blend_layer[0][lane]<=overlay_pass?m_axi_rdata[lane*32+:32]:32'b0;
    blend_layer[1][lane]<=blend_layer[0][lane];blend_layer[2][lane]<=blend_layer[1][lane];
    blend_result[lane][31:24]<=8'hff;
    for(integer c=0;c<3;c=c+1)begin
     blend_product[lane][c]<=blend_base[lane][c*8+:8]*(8'd255-blend_layer[0][lane][31:24]);
     blend_scaled[lane][c]<=round255(blend_product[lane][c]);
     blend_result[lane][c*8+:8]<=sat_add8(blend_scaled[lane][c],blend_layer[2][lane][c*8+:8]);
    end
   end
  end
 end
 always_ff @(posedge clk)begin
  if(!rstn)begin
   wp<=0;wgray<=0;rg0<=0;rg1<=0;vs_sync<=0;uf_sync<=0;underflow_frames<=0;read_bytes<=0;
   state<=0;source_line<=0;word_in_line<=0;blank_delay<=0;reset_requested<=0;
   m_axi_arvalid<=0;m_axi_araddr<=0;beats_left<=0;present_window<=0;adopted<=0;
   fault<=0;displayed_address<=0;mode_latched<=0;active_layer<=0;active_cursor<=0;cursor_toggle<=0;overlay_pass<=0;beat_index<=0;burst_offset<=0;
  end else begin
   rg0<=rgray;rg1<=rg0;vs_sync<={vs_sync[1:0],video_vsync};uf_sync<={uf_sync[1:0],underflow_toggle};adopted<=0;
   if(uf_sync[2]!=uf_sync[1])underflow_frames<=underflow_frames+1;
   if(blend_valid[3]&&blend_last[3]&&!fault)begin wp<=blend_next[3];wgray<=blend_next[3]^(blend_next[3]>>1);end
   if(vs_sync[1]&&!vs_sync[2])reset_requested<=1;
   case(state)
    0:if(reset_requested&&!fault)begin
     reset_requested<=0;present_window<=1;blank_delay<=0;state<=3;
    end else if(!fault&&displayed_address!=0&&source_line<SH&&wgray!=(rg1^4'b1100))begin
     m_axi_araddr<=displayed_address+(source_line*SW+word_in_line*2)*4;
     burst_offset<=(source_line*SW+word_in_line*2)*4;overlay_pass<=0;beat_index<=0;
     m_axi_arvalid<=1;beats_left<=16;state<=1;
    end
    1:if(m_axi_arready)begin m_axi_arvalid<=0;state<=2;end
    2:if(m_axi_rvalid)begin
     if(m_axi_rresp!=0||m_axi_rlast!=(beats_left==1))fault<=1;
     read_bytes<=read_bytes+8;beats_left<=beats_left-1;
     beat_index<=beat_index+1;
     if(active_layer!=0&&!overlay_pass) saved_rgb[beat_index]<=m_axi_rdata;
     else begin
      if(word_in_line==SW/2-1)begin word_in_line<=0;source_line<=source_line+1;end
      else word_in_line<=word_in_line+1;
     end
     if(beats_left==1)begin
      if(active_layer!=0&&!overlay_pass)begin
       overlay_pass<=1;beat_index<=0;m_axi_araddr<=active_layer+burst_offset;
       m_axi_arvalid<=1;beats_left<=16;state<=1;
      end else state<=4;
     end
    end
    4:if(blend_valid==0)state<=0; // drain before reuse, reset or next burst
    3:begin
     blank_delay<=blank_delay+1;
     if(blank_delay==8)begin present_window<=0;displayed_address<=front_address;mode_latched<=native_view;
      if(!ui_quiet)begin active_layer<=layer_address;active_cursor<=cursor_position;cursor_toggle<=~cursor_toggle;end
      adopted<=1;wp<=0;wgray<=0;source_line<=0;word_in_line<=0;end
     if(blank_delay==16)state<=0;
    end
   endcase
  end
 end
endmodule
