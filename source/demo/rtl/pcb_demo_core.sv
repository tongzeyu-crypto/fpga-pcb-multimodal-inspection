// PDP3: report-defined spectrum, ADC transport and shared image processor.
// Complex Q16 radix-2 DIF FFT / N, periodic Hann, one-sided power accumulation.
// Pixel operations share the FFT RAM. PS tiles arbitrary-sized images through it.
module pcb_demo_core(input wire clk,rstn,input wire host_we,host_re,
 input wire [15:0] host_addr,input wire [31:0] host_wdata,
 output reg [31:0] host_rdata,output wire irq);
 localparam IDLE=0,MEAN_RD=1,MEAN_SUM=2,WIN_RD=3,WIN_WAIT=4,WIN_SET=5,
 WIN_MUL=6,WIN_STORE=7,B_RD=8,B_WAIT=9,B_LOAD=10,B_SET=11,B_MUL=12,
 B_STORE_A=13,B_STORE_B=14,B_NEXT=15,P_RD=16,P_WAIT=17,P_SET=18,
 P_MUL=19,P_POWER=20,P_STORE=21,PIX_RD=22,PIX_WAIT=23,PIX_CALC=24,
 PIX_STORE=25,FINISH=26,PSD_BEGIN=27,PSD_DEN_WAIT=28,PSD_READ=29,
 PSD_WAIT=30,PSD_DIV=31,PSD_DIV_WAIT=32,PSD_WRITE=33,BAND_MUL=34,
 BAND_MUL_WAIT=35,BAND_SQRT=36,BAND_SQRT_WAIT=37,IMG_READ=38,
 IMG_WAIT=39,IMG_CALC=40,RESIZE_SET=41,RESIZE_MUL=42,RESIZE_H=43,
 RESIZE_VSET=44,RESIZE_VMUL=45,RESIZE_V=46,IMG_WRITE=47,
 GRAD_SET=48,GRAD_MUL=49,GRAD_SQRT=50,GRAD_WAIT=51,
 NORM_WAIT=52,COLOR_WAIT=53,COLOR_PREP=54,COLOR_DIV=55;
 reg [5:0] state=IDLE;
 reg busy=0,done=0,error=0;
 reg [31:0] op=1,count=4096,threshold_mc=40000,mode=1,base=4370,shift=2;
 reg [31:0] generation=0,offset=0,thermal_total=0,thermal_threshold=0;
 reg signed [31:0] min_mc=0,max_mc=0,pixel;
 reg [31:0] max_index=0,hot_count=0,frames=0,accum_n=0;
 reg thermal_valid=0,accum_valid=0,continuing=0,accum_hann=0;
 reg [31:0] sample_rate=50000000,band_count=5,output_count=0,normalizer=1;
 reg signed [31:0] color_low=0,color_high=100000;
 reg [12:0] band_lo[0:7],band_hi[0:7];
 reg [63:0] band_sum[0:7];reg [31:0] band_rms[0:7];reg [3:0] band_index=0;
 reg [95:0] psd_denominator;reg [63:0] psd_value;reg [127:0] rms_square;
 reg [31:0] adc_total=0,phase_count[0:3],last_error=0;
 reg [11:0] previous_heartbeat;reg adc_valid=0;
 reg [12:0] out_i=0;reg [4:0] gather=0,group_size=1;
 reg signed [63:0] image_sum=0,gradient_x=0,gradient_y=0;
 reg signed [31:0] px0,px1,px2,px3,horizontal0,horizontal1,extreme;
 reg [11:0] fraction_x,fraction_y;
 reg [32:0] color_delta,color_range;reg [63:0] color_numerator;
 reg scalar_start=0;reg [1:0] scalar_op=0;reg [127:0] scalar_a=0;reg [95:0] scalar_b=0;
 wire scalar_done,scalar_busy,scalar_error;wire [127:0] scalar_value;
 pcb_scalar scalar(.clk(clk),.rstn(rstn&&!(host_we&&host_addr==0&&host_wdata==2)),
  .start(scalar_start),.op(scalar_op),.a(scalar_a),.b(scalar_b),
  .busy(scalar_busy),.done(scalar_done),.error(scalar_error),.value(scalar_value));
 reg [12:0] i=0,bin=0,half=0,span=0,group_base=0,j=0,phase_step=0;
 reg [3:0] logn=12;
 reg [11:0] phase=0;
 wire signed [15:0] coeff_r,coeff_i;
 pcb_demo_coeff coefficients(.clk(clk),.phase(phase),.c(coeff_r),.s(coeff_i));
 (* ram_style="block" *) reg [63:0] work[0:4095];
 (* ram_style="block" *) reg [63:0] accumulation[0:2047];
 reg [63:0] nyquist=0;
 reg [63:0] qa,qb,acc_ram_q,nyquist_q;
 reg acc_is_nyquist=0;
 wire [63:0] accq=acc_is_nyquist?nyquist_q:acc_ram_q;
 reg host_pending=0,host_high=0;
 wire input_select=host_addr>=16'h1000&&host_addr<16'h5000;
 wire [11:0] input_address=(host_addr-16'h1000)>>2;
 wire output_select=host_addr[15];
 wire [11:0] output_address=host_addr[14:3];
 reg [11:0] ra,rb,wa;
 reg ren_a,ren_b,wen;
 reg [63:0] wdata;
 reg signed [39:0] mean_sum=0;
 reg signed [31:0] mean_q16=0,ar,ai,br,bi,sr,si,dr,di;
 reg [63:0] window_energy=0,power=0;
 reg signed [31:0] mx0,mx1,mx2,mx3;
 reg signed [17:0] my0,my1,my2,my3;
 (* use_dsp="yes" *) reg signed [49:0] p0,p1,p2,p3;
 always @(posedge clk)begin
  p0<=mx0*my0;p1<=mx1*my1;p2<=mx2*my2;p3<=mx3*my3;
 end
 wire signed [63:0] wide0={{14{p0[49]}},p0},wide1={{14{p1[49]}},p1};
 wire signed [63:0] wide2={{14{p2[49]}},p2},wide3={{14{p3[49]}},p3};
 wire signed [63:0] squared=wide0+(wide1<<<17)+wide2+(wide3<<<17);
 wire signed [31:0] butterfly_r=(wide0-wide1)>>>14;
 wire signed [31:0] butterfly_i=(wide2+wide3)>>>14;
 wire signed [31:0] raw=$signed(qa[31:0]);
 wire signed [63:0] centered=($signed({{32{raw[31]}},raw})<<<16)-mean_q16;
 wire signed [17:0] window_value=mode[0]?((18'sd16384-$signed(coeff_r))>>>1):18'sd16384;
 (* use_dsp="no" *) wire [22:0] raw125=({7'b0,qa[15:0]}<<7)-({7'b0,qa[15:0]}<<1)-{7'b0,qa[15:0]};
 wire signed [31:0] temp_mc=$signed({10'b0,raw125[22:1]})-32'sd273150;
 (* use_dsp="no" *) wire [15:0] gray_sum=qa[23:16]*16'd77+qa[15:8]*16'd150+qa[7:0]*16'd29;
 wire signed [31:0] delta=$signed({16'b0,qa[15:0]})-$signed(base);
 wire signed [31:0] scaled=delta>>>shift[3:0];
 wire signed [31:0] tq=scaled<0?-32'sd128:scaled>255?32'sd127:scaled-32'sd128;
 wire [1:0] adc_phase=qa[16:15];
 wire signed [15:0] adc_sample={{2{qa[13]}},qa[13:0]};
 wire [31:0] adc_decoded=adc_phase==1||adc_phase==3?{14'b0,(adc_phase==3),1'b1,adc_sample}:32'b0;
 wire signed [63:0] image_raw={{32{raw[31]}},raw};
 wire signed [63:0] blur_term=(gather==4)?image_raw<<<2:
   (gather==1||gather==3||gather==5||gather==7)?image_raw<<<1:image_raw;
 wire signed [63:0] gx_term=(gather==0||gather==6)?-image_raw:
   gather==3?-(image_raw<<<1):(gather==2||gather==8)?image_raw:gather==5?image_raw<<<1:64'sd0;
 wire signed [63:0] gy_term=(gather==0||gather==2)?-image_raw:
   gather==1?-(image_raw<<<1):(gather==6||gather==8)?image_raw:gather==7?image_raw<<<1:64'sd0;
 wire signed [31:0] next_extreme=gather==0?raw:mode[0]?(raw>extreme?raw:extreme):(raw<extreme?raw:extreme);
 wire signed [63:0] diff=$signed({{32{px0[31]}},px0})-$signed({{32{px1[31]}},px1});
 function [31:0] jet(input [7:0] v);
  integer x,r,g,b;begin x=v*4;r=x-765;g=x-510;b=x-255;
   r=383-(r<0?-r:r);g=383-(g<0?-g:g);b=383-(b<0?-b:b);
   r=r<0?0:r>255?255:r;g=g<0?0:g>255?255:g;b=b<0?0:b>255?255:b;
   jet={8'hff,8'(r),8'(g),8'(b)};end
 endfunction
 function [11:0] reverse_index(input [12:0] value,input [3:0] bits);
  integer k;begin reverse_index=0;for(k=0;k<12;k=k+1)if(k<bits)reverse_index[bits-1-k]=value[k];end
 endfunction
 function [3:0] length_log(input [31:0] n);
  begin case(n)64:length_log=6;128:length_log=7;256:length_log=8;512:length_log=9;
   1024:length_log=10;2048:length_log=11;4096:length_log=12;default:length_log=0;endcase end
 endfunction
 assign irq=done;
 always @*begin
  ra=i[11:0];rb=0;wa=i[11:0];ren_a=0;ren_b=0;wen=0;wdata=0;
  case(state)
   MEAN_RD,WIN_RD,PIX_RD,IMG_READ:ren_a=1;
   WIN_STORE:begin wen=1;wdata={32'b0,32'(wide0>>>14)};end
   B_RD:begin ren_a=1;ren_b=1;ra=group_base+j;rb=group_base+j+half;end
   B_STORE_A:begin wen=1;wa=group_base+j;wdata={si,sr};end
   B_STORE_B:begin wen=1;wa=group_base+j+half;wdata={butterfly_i,butterfly_r};end
   P_RD:begin ren_a=1;ra=reverse_index(bin,logn);end
   PIX_STORE:begin wen=1;wdata={{32{pixel[31]}},pixel};end
   IMG_WRITE:begin wen=1;wa=out_i[11:0];wdata={{32{pixel[31]}},pixel};end
  endcase
 end
 wire host_input_write=!busy&&rstn&&host_we&&input_select;
 wire port_a_write=host_input_write||(rstn&&wen);
 wire [11:0] port_a_address=host_input_write?input_address:wen?wa:ra;
 wire [63:0] port_a_data=host_input_write?{32'b0,host_wdata}:wdata;
 wire [11:0] acc_address=busy?bin[11:0]:output_address;
 // Explicit two-port template: one address per port, no third RAM read path.
 always @(posedge clk)begin
  if(ren_a||port_a_write)begin
   if(port_a_write)work[port_a_address]<=port_a_data;
   qa<=work[port_a_address];
  end
  if(ren_b||(host_re&&output_select&&!busy&&op!=1&&op!=5))qb<=work[busy?rb:output_address];
  if(state==P_RD||state==PSD_READ||(host_re&&output_select&&!busy&&(op==1||op==5)))begin
   acc_ram_q<=accumulation[acc_address[10:0]];nyquist_q<=nyquist;acc_is_nyquist<=acc_address==2048;
  end
  if(rstn&&(state==P_STORE||state==PSD_WRITE))begin
   if(bin==2048)nyquist<=state==PSD_WRITE?psd_value:(continuing?accq:64'b0)+power;
   else accumulation[bin[10:0]]<=state==PSD_WRITE?psd_value:(continuing?accq:64'b0)+power;
  end
  host_pending<=host_re&&output_select;
  if(host_re)host_high<=host_addr[2];
  if(host_pending)host_rdata<=(op==1||op==5)?(host_high?accq[63:32]:accq[31:0]):(host_high?qb[63:32]:qb[31:0]);
  else if(host_re&&host_addr>=16'h100&&host_addr<16'h140)host_rdata<=host_addr[2]?band_hi[host_addr[5:3]]:band_lo[host_addr[5:3]];
  else if(host_re&&host_addr>=16'h180&&host_addr<16'h1a0)host_rdata<=band_rms[host_addr[4:2]];
  else if(host_re)case(host_addr)
   4:host_rdata<={29'b0,error,done,busy};8:host_rdata<=32'h50445033;
   12:host_rdata<=op;16:host_rdata<=count;20:host_rdata<=threshold_mc;
   24:host_rdata<=mode;28:host_rdata<=base;32:host_rdata<=shift;
   36:host_rdata<=min_mc;40:host_rdata<=max_mc;44:host_rdata<=max_index;
   48:host_rdata<=hot_count;52:host_rdata<=generation;56:host_rdata<=4096;
   60:host_rdata<=frames;64:host_rdata<=window_energy[31:0];68:host_rdata<=window_energy[63:32];
   72:host_rdata<=offset;76:host_rdata<=thermal_total;80:host_rdata<=32'h20261104;
   84:host_rdata<=sample_rate;88:host_rdata<=band_count;92:host_rdata<=output_count;
   96:host_rdata<=normalizer;100:host_rdata<=color_low;104:host_rdata<=color_high;
   108:host_rdata<=adc_total;112:host_rdata<=phase_count[0];116:host_rdata<=phase_count[1];
   120:host_rdata<=phase_count[2];124:host_rdata<=phase_count[3];128:host_rdata<=last_error;
   default:host_rdata<=0;
  endcase
 end
 always @(posedge clk)begin
  scalar_start<=0;
  if(!rstn)begin
   state<=IDLE;busy<=0;done<=0;error<=0;generation<=0;op<=1;count<=4096;
   threshold_mc<=40000;mode<=1;base<=4370;shift<=2;offset<=0;
   accum_valid<=0;thermal_valid<=0;frames<=0;thermal_total<=0;
   min_mc<=0;max_mc<=0;max_index<=0;hot_count<=0;window_energy<=0;
   sample_rate<=50000000;band_count<=5;output_count<=0;normalizer<=1;color_low<=0;color_high<=100000;
   adc_total<=0;adc_valid<=0;last_error<=0;
   for(integer k=0;k<4;k=k+1)phase_count[k]<=0;
   for(integer k=0;k<8;k=k+1)begin band_sum[k]<=0;band_rms[k]<=0;band_lo[k]<=0;band_hi[k]<=0;end
  end else if(host_we&&host_addr==0&&host_wdata==2)begin
   state<=IDLE;busy<=0;done<=0;error<=0;accum_valid<=0;thermal_valid<=0;frames<=0;
   adc_valid<=0;last_error<=0;
  end else begin
   if(host_we)begin
    if(busy)error<=1;
    else if(host_addr>=16'h100&&host_addr<16'h140)begin
     if(host_addr[2])band_hi[host_addr[5:3]]<=host_wdata[12:0];else band_lo[host_addr[5:3]]<=host_wdata[12:0];
    end else if(host_addr<16'h1000)case(host_addr)
     0:begin
      if(host_wdata!=1||op<1||op>10||count==0||count>4096||
       (op==1&&(length_log(count)==0||mode>3||(mode[1]&&(!accum_valid||accum_n!=count||accum_hann!=mode[0]||frames>=3))))||
       (op==2&&(mode>2||mode[0]||(!mode[1]&&offset!=0)||(mode[1]&&(!thermal_valid||offset!=thermal_total||threshold_mc!=thermal_threshold))))||
       (op==3&&(mode>2||shift>15))||
       (op==4&&(mode>2||mode[0]||(!mode[1]&&offset!=0)||(mode[1]&&(!adc_valid||offset!=adc_total||adc_total+count>16384))))||
       (op==5&&(!accum_valid||count!=accum_n||sample_rate==0||sample_rate>200000000||band_count==0||band_count>8))||
       (op==7&&mode>5)||(op==8&&normalizer==0)||(op==10&&color_high<color_low))begin error<=1;done<=0;last_error<=6;end
      else begin
       busy<=1;done<=0;error<=0;last_error<=0;i<=0;out_i<=0;gather<=0;bin<=0;phase<=0;mean_sum<=0;output_count<=0;
       continuing<=mode[1];if(op==1)begin logn<=length_log(count);window_energy<=0;end
       if(op==1)begin
        state<=MEAN_RD;frames<=mode[1]?frames:0;accum_n<=count;accum_hann<=mode[0];
        half<=count>>1;span<=count;group_base<=0;j<=0;phase_step<=4096>>length_log(count);
       end else if(op==5)begin state<=PSD_BEGIN;for(integer k=0;k<8;k=k+1)begin band_sum[k]<=0;band_rms[k]<=0;end end
       else if(op>=6)begin
        state<=IMG_READ;image_sum<=0;gradient_x<=0;gradient_y<=0;
        group_size<=op==6?5:op==7?(mode>=4?25:9):op==9?3:1;
       end else begin
        state<=PIX_RD;
        if(op==2&&!mode[1])begin min_mc<=0;max_mc<=0;max_index<=0;hot_count<=0;thermal_total<=0;thermal_threshold<=threshold_mc;end
        if(op==4&&!mode[1])begin adc_total<=0;adc_valid<=1;for(integer k=0;k<4;k=k+1)phase_count[k]<=0;end
       end
      end
     end
     12:op<=host_wdata;16:count<=host_wdata;20:threshold_mc<=host_wdata;
     24:mode<=host_wdata;28:base<=host_wdata;32:shift<=host_wdata;72:offset<=host_wdata;
     84:sample_rate<=host_wdata;88:band_count<=host_wdata;96:normalizer<=host_wdata;
     100:color_low<=host_wdata;104:color_high<=host_wdata;
     default:error<=1;
    endcase
   end
   case(state)
    MEAN_RD:state<=MEAN_SUM;
    MEAN_SUM:begin
     mean_sum<=mean_sum+{{8{raw[31]}},raw};
     if(i+1==count)begin mean_q16<=($signed({{24{mean_sum[39]}},mean_sum}+{{32{raw[31]}},raw})<<<16)>>>logn;i<=0;state<=WIN_RD;end
     else begin i<=i+1;state<=MEAN_RD;end
    end
    WIN_RD:state<=WIN_WAIT;
    WIN_WAIT:state<=WIN_SET;
    WIN_SET:begin mx0<=centered;my0<=window_value;mx1<=window_value;my1<=window_value;state<=WIN_MUL;end
    WIN_MUL:state<=WIN_STORE;
    WIN_STORE:begin
     window_energy<=window_energy+wide1;
     if(i+1==count)begin phase<=0;state<=B_RD;end else begin i<=i+1;phase<=phase+phase_step;state<=WIN_RD;end
    end
    B_RD:state<=B_WAIT;
    B_WAIT:state<=B_LOAD;
    B_LOAD:begin ar<=qa[31:0];ai<=qa[63:32];br<=qb[31:0];bi<=qb[63:32];state<=B_SET;end
    B_SET:begin
     sr<=($signed({ar[31],ar})+$signed({br[31],br}))>>>1;
     si<=($signed({ai[31],ai})+$signed({bi[31],bi}))>>>1;
     dr<=($signed({ar[31],ar})-$signed({br[31],br}))>>>1;
     di<=($signed({ai[31],ai})-$signed({bi[31],bi}))>>>1;
     state<=B_MUL;
    end
    B_MUL:begin mx0<=dr;my0<=coeff_r;mx1<=di;my1<=coeff_i;mx2<=dr;my2<=coeff_i;mx3<=di;my3<=coeff_r;state<=B_STORE_A;end
    B_STORE_A:state<=B_STORE_B;
    B_STORE_B:state<=B_NEXT;
    B_NEXT:begin
     if(j+1<half)begin j<=j+1;phase<=phase+phase_step;state<=B_RD;end
     else if(group_base+span<count)begin group_base<=group_base+span;j<=0;phase<=0;state<=B_RD;end
     else if(half>1)begin half<=half>>1;span<=span>>1;phase_step<=phase_step<<1;group_base<=0;j<=0;phase<=0;state<=B_RD;end
     else begin bin<=0;state<=P_RD;end
    end
    P_RD:state<=P_WAIT;
    P_WAIT:state<=P_SET;
    P_SET:begin
     mx0<=qa[31:0];my0<={1'b0,qa[16:0]};mx1<=qa[31:0];my1<={{3{qa[31]}},qa[31:17]};
     mx2<=qa[63:32];my2<={1'b0,qa[48:32]};mx3<=qa[63:32];my3<={{3{qa[63]}},qa[63:49]};state<=P_MUL;
    end
    P_MUL:state<=P_POWER;
    P_POWER:begin power<=bin!=0&&bin!=(count>>1)?squared<<1:squared;state<=P_STORE;end
    P_STORE:begin if(bin==(count>>1))begin frames<=frames+1;accum_valid<=1;output_count<=(count>>1)+1;state<=FINISH;end else begin bin<=bin+1;state<=P_RD;end end
    PIX_RD:state<=PIX_WAIT;
    PIX_WAIT:state<=PIX_CALC;
    PIX_CALC:begin
     pixel<=op==2?temp_mc:op==4?adc_decoded:mode==1?tq:mode==2?$signed({24'b0,gray_sum[15:8]}):$signed({24'b0,gray_sum[15:8]})-32'sd128;state<=PIX_STORE;
     if(op==4)begin
      previous_heartbeat<=qa[31:20];
      if(!qa[19])begin error<=1;last_error<=1;state<=FINISH;end
      else if((continuing||i!=0)&&qa[31:20]!=(previous_heartbeat+12'd1))begin error<=1;last_error<=2;state<=FINISH;end
      else if((adc_phase==1||adc_phase==3)&&(qa[14]||qa[18:17]!=0))begin error<=1;last_error<=3;state<=FINISH;end
      else if((adc_phase==1||adc_phase==3)&&(qa[13:0]==14'h2000||qa[13:0]==14'h1fff))begin error<=1;last_error<=4;state<=FINISH;end
     end
    end
    PIX_STORE:begin
     if(op==2)begin
      if((i==0&&!continuing)||pixel<min_mc)min_mc<=pixel;
      if((i==0&&!continuing)||pixel>max_mc)begin max_mc<=pixel;max_index<=offset+i;end
      if(pixel>=$signed(threshold_mc))hot_count<=hot_count+1;
     end
     if(op==4)begin
      adc_total<=adc_total+1;phase_count[adc_phase]<=phase_count[adc_phase]+1;
      if(adc_total==16383)for(integer k=0;k<4;k=k+1)if(phase_count[k]+(adc_phase==k?1:0)!=4096)begin error<=1;last_error<=5;end
     end
     if(i+1==count)begin output_count<=count;if(op==2)begin thermal_valid<=1;thermal_total<=offset+count;end state<=FINISH;end
     else begin i<=i+1;state<=PIX_RD;end
    end
    PSD_BEGIN:begin scalar_op<=1;scalar_a<={64'b0,window_energy};scalar_b<={64'b0,sample_rate};scalar_start<=1;state<=PSD_DEN_WAIT;end
    PSD_DEN_WAIT:if(scalar_done)begin
     psd_denominator<=frames==3?scalar_value[95:0]+(scalar_value[95:0]<<1):frames==2?scalar_value[95:0]<<1:scalar_value[95:0];bin<=0;state<=PSD_READ;
    end
    PSD_READ:state<=PSD_WAIT;
    PSD_WAIT:state<=PSD_DIV;
    PSD_DIV:begin scalar_op<=0;scalar_a<={64'b0,accq}<<(2*logn+36);scalar_b<=psd_denominator;scalar_start<=1;state<=PSD_DIV_WAIT;end
    PSD_DIV_WAIT:if(scalar_done)begin
     if(scalar_error||scalar_value[127:64]!=0)begin error<=1;last_error<=7;state<=FINISH;end
     else begin psd_value<=scalar_value[63:0];state<=PSD_WRITE;end
    end
    PSD_WRITE:begin
     for(integer k=0;k<8;k=k+1)if(k<band_count&&bin>=band_lo[k]&&bin<band_hi[k])band_sum[k]<=band_sum[k]+psd_value;
     if(bin==(accum_n>>1))begin band_index<=0;output_count<=(accum_n>>1)+1;state<=BAND_MUL;end
     else begin bin<=bin+1;state<=PSD_READ;end
    end
    BAND_MUL:begin scalar_op<=1;scalar_a<={64'b0,band_sum[band_index]};scalar_b<={64'b0,sample_rate};scalar_start<=1;state<=BAND_MUL_WAIT;end
    BAND_MUL_WAIT:if(scalar_done)begin rms_square<=scalar_value>>(logn+8);state<=BAND_SQRT;end
    BAND_SQRT:begin scalar_op<=2;scalar_a<=rms_square;scalar_b<=0;scalar_start<=1;state<=BAND_SQRT_WAIT;end
    BAND_SQRT_WAIT:if(scalar_done)begin
     band_rms[band_index]<=scalar_value[31:0];
     if(band_index+1==band_count)begin accum_valid<=0;state<=FINISH;end
     else begin band_index<=band_index+1;state<=BAND_MUL;end
    end
    IMG_READ:state<=IMG_WAIT;
    IMG_WAIT:state<=IMG_CALC;
    IMG_CALC:begin
     // Host gathers addresses and halos; all pixel arithmetic stays in PL.
     if(op==6)begin
      case(gather)0:px0<=raw;1:px1<=raw;2:px2<=raw;3:px3<=raw;4:begin fraction_x<=qa[11:0];fraction_y<=qa[27:16];end endcase
     end else if(op==7)begin
      image_sum<=image_sum+blur_term;gradient_x<=gradient_x+gx_term;gradient_y<=gradient_y+gy_term;extreme<=next_extreme;
     end else if(op==9)begin if(gather==0)px0<=raw;if(gather==1)px1<=raw;end
     if(gather+1==group_size)begin
      if(op==6)state<=RESIZE_SET;
      else if(op==7)begin
       if(mode==0)begin pixel<=(image_sum+blur_term+64'sd8)>>>4;state<=IMG_WRITE;end
       else if(mode==1)begin gradient_x<=gradient_x+gx_term;gradient_y<=gradient_y+gy_term;state<=GRAD_SET;end
       else begin pixel<=next_extreme;state<=IMG_WRITE;end
      end else if(op==8)begin
       if(raw<0)begin error<=1;last_error<=8;state<=FINISH;end
       else if(qa[31:0]>=normalizer)begin pixel<=127;state<=IMG_WRITE;end
       else begin scalar_op<=0;scalar_a<=({96'b0,qa[31:0]}<<7)+(normalizer>>1);scalar_b<={64'b0,normalizer};scalar_start<=1;state<=NORM_WAIT;end
      end else if(op==9)begin pixel<=raw!=0&&(diff<0?-diff:diff)>$signed({32'b0,threshold_mc})?255:0;state<=IMG_WRITE;end
      else if(op==10)begin
       if(raw<=color_low||color_high==color_low)begin pixel<=jet(0);state<=IMG_WRITE;end
       else if(raw>=color_high)begin pixel<=jet(255);state<=IMG_WRITE;end
       else begin color_delta<=$signed({raw[31],raw})-$signed({color_low[31],color_low});color_range<=$signed({color_high[31],color_high})-$signed({color_low[31],color_low});state<=COLOR_PREP;end
      end
     end else if(i+1==count)begin error<=1;last_error<=9;state<=FINISH;end
     else begin i<=i+1;gather<=gather+1;state<=IMG_READ;end
    end
    RESIZE_SET:begin
     mx0<=px0;my0<=18'd4096-{6'b0,fraction_x};mx1<=px1;my1<={6'b0,fraction_x};
     mx2<=px2;my2<=18'd4096-{6'b0,fraction_x};mx3<=px3;my3<={6'b0,fraction_x};state<=RESIZE_MUL;
    end
    RESIZE_MUL:state<=RESIZE_H;
    RESIZE_H:begin horizontal0<=(wide0+wide1+64'sd2048)>>>12;horizontal1<=(wide2+wide3+64'sd2048)>>>12;state<=RESIZE_VSET;end
    RESIZE_VSET:begin mx0<=horizontal0;my0<=18'd4096-{6'b0,fraction_y};mx1<=horizontal1;my1<={6'b0,fraction_y};state<=RESIZE_VMUL;end
    RESIZE_VMUL:state<=RESIZE_V;
    RESIZE_V:begin pixel<=(wide0+wide1+64'sd2048)>>>12;state<=IMG_WRITE;end
    GRAD_SET:begin
     mx0<=gradient_x[31:0];my0<={1'b0,gradient_x[16:0]};mx1<=gradient_x[31:0];my1<={{3{gradient_x[31]}},gradient_x[31:17]};
     mx2<=gradient_y[31:0];my2<={1'b0,gradient_y[16:0]};mx3<=gradient_y[31:0];my3<={{3{gradient_y[31]}},gradient_y[31:17]};state<=GRAD_MUL;
    end
    GRAD_MUL:state<=GRAD_SQRT;
    GRAD_SQRT:begin scalar_op<=2;scalar_a<={64'b0,squared};scalar_b<=0;scalar_start<=1;state<=GRAD_WAIT;end
    GRAD_WAIT:if(scalar_done)begin pixel<=scalar_value[31:0];state<=IMG_WRITE;end
    NORM_WAIT:if(scalar_done)begin pixel<=scalar_value>127?127:scalar_value[31:0];state<=IMG_WRITE;end
    COLOR_PREP:begin color_numerator<=({31'b0,color_delta}<<8)-{31'b0,color_delta}+(color_range>>1);state<=COLOR_DIV;end
    COLOR_DIV:begin scalar_op<=0;scalar_a<={64'b0,color_numerator};scalar_b<={63'b0,color_range};scalar_start<=1;state<=COLOR_WAIT;end
    COLOR_WAIT:if(scalar_done)begin pixel<=jet(scalar_value[7:0]);state<=IMG_WRITE;end
    IMG_WRITE:begin
     if(i+1==count)begin output_count<=out_i+1;state<=FINISH;end
     else begin i<=i+1;out_i<=out_i+1;gather<=0;image_sum<=0;gradient_x<=0;gradient_y<=0;state<=IMG_READ;end
    end
    FINISH:begin busy<=0;done<=1;generation<=generation+1;state<=IDLE;end
    default:begin end
   endcase
  end
 end
endmodule
