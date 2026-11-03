// Included inside FullScene. Raw display reads preserved photos and linear PSD.
template<class V>void sidebar(FullDraw &d,const V &v){
 d.text("显示模式",18,64,21);
 for(int row=0;row<5;row++){int m=full_view_modes[row],y=96+row*30;if(m==v.mode)d.rect(12,y,FULL_LEFT-24,28,0xff2a5a65);d.text(full_modes[m],24,y-1,18);}
 if(v.mode==16)d.rect(12,278,FULL_LEFT-24,36,0xff2a5a65);d.text("扫描演示",24,280,19);
 d.text("原始数据",18,420,21);
 for(int i=0;i<3;i++){int y=462+i*40;if(v.mode==13+i)d.rect(12,y,FULL_LEFT-24,32,0xff2a5a65);d.text(full_modes[13+i],24,y+1,19);}
}
template<class V>void raw_image(FullDraw &d,const V &v,int image_index,int index,double x,double y,double width,double maxheight){
 const auto &r=raw_rects[index];if(r[2]<=0||r[3]<=0)return;
 double height=width*r[3]/r[2];if(height>maxheight){width*=maxheight/height;height=maxheight;}
 double zoom=v.raw_zoom[image_index],px=v.raw_x[image_index],py=v.raw_y[image_index];
 double u0=std::max(0.,.5-px-.5/zoom),v0=std::max(0.,.5-py-.5/zoom),u1=std::min(1.,.5-px+.5/zoom),v1=std::min(1.,.5-py+.5/zoom);
 if(u1>u0&&v1>v0)d.image(x,y,width,height,int(r[0]+u0*r[2]),int(r[1]+v0*r[3]),int((u1-u0)*r[2]),int((v1-v0)*r[3]));
}
template<class V>void raw_view(FullDraw &d,const V &v){
 d.rect(0,0,1280,720,0xff0d1722);d.rect(0,0,1280,54,0xff14242f);d.text("桌面PCB多模态检测系统",18,10,26);
 d.text(std::string("原始数据 / ")+(v.raw_board?"DC-DC":"STM32"),350,17,19);
 if(v.hud){d.rect(0,54,FULL_LEFT,666,0xff12212c);d.rect(1048,54,232,666,0xff12212c);sidebar(d,v);}
 d.rect(1112,12,152,32,0xff264856);d.text(v.hud?"隐藏面板":"显示面板",1130,14,19);
 if(v.hud){
  d.text("板卡",1062,64,21);button(d,1060,100,204,32,v.raw_board?"DC-DC":"STM32");
  d.text(full_modes[v.mode],1064,158,23);if(v.mode!=15)button(d,1060,182,204,32,"复位");
  if(v.mode==15){int p=std::min(v.point,int(points.size())-1);button(d,1060,424,96,32,"< P"+std::to_string(p+1));button(d,1164,424,100,32,"选择 >");
   d.text("实测 "+std::to_string(points.size())+" 点",1064,208,18);d.text("INA",1064,246,18);d.text("频段",1064,276,18);button(d,1060,300,204,32,(v.raw_board&&v.band==0)?"0.2-21.9 MHz":(v.raw_board&&v.band==3)?"10-21.9 MHz":full_bands[v.band]);}
 }
 if(v.mode==13){
  d.text("参考",FULL_LEFT+24,116,24);d.text("待测",620,116,24);
  raw_image(d,v,0,0,FULL_LEFT+20,163,414,370);raw_image(d,v,1,v.raw_board?2:1,616,163,414,370);
 }else if(v.mode==14){
  d.text("热像",FULL_LEFT+24,90,24);raw_image(d,v,0,v.raw_board?4:3,348,156,512,384);
  d.text("256 x 192",548,562,18);
 }else{
  const auto &xx=v.raw_board?raw_dc_x:xs;const auto &yy=v.raw_board?raw_dc_y:ys;
  const int nx=int(xx.size()),ny=int(yy.size()),selected=std::min(v.point,int(points.size())-1);
  const int bins=meta[4];
  const double left=FULL_LEFT+62,top=180,width=FULL_WIDTH-92,rowheight=26,cellwidth=width/nx;
  auto value=[&](int point,int k){return v.raw_board?double(raw_dc_psd[size_t(point)*bins+k]):base(point,k,v.scenario);};
  auto frequency=[&](int k){return v.raw_board?double(raw_dc_frequency[k]):k*df;};
  const double lowhz=full_band_lo[v.band]*1e6,highhz=std::min(full_band_hi[v.band],v.raw_board?21.9:25.)*1e6;
  int display_bins=bins;if(v.raw_board)while(display_bins>0&&raw_dc_frequency[display_bins-1]>=21.9e6)--display_bins;
  std::vector<double> rms(points.size(),0.);
  for(size_t point=0;point<rms.size();point++){double power=0;for(int k=0;k<bins;k++){double f=frequency(k);if(f>=lowhz&&(v.raw_board?f<highhz:f<=highhz))power+=value(int(point),k);}rms[point]=std::sqrt(power*(v.raw_board?raw_dc_frequency[1]-raw_dc_frequency[0]:df));}
  d.text("EMI 测点矩阵",FULL_LEFT+24,80,23);d.text("实测 / INA / RMS / ADC code",FULL_LEFT+24,116,16);
  d.text("X / mm",934,132,15);d.text("Y / mm",FULL_LEFT+12,146,15);
  for(int col=0;col<nx;col++){double x=left+col*cellwidth;d.text(full_number(xx[col],v.raw_board?0:1),x+3,154,13);}
  for(int row=0;row<ny;row++){
   d.text(full_number(yy[row],v.raw_board?0:1),FULL_LEFT+13,top+row*rowheight+4,14);
   for(int col=0;col<nx;col++){
    int point=v.raw_board?raw_dc_grid[row*nx+col]:row*nx+col;double x=left+col*cellwidth,y=top+row*rowheight;
    if(point==selected){d.line(x,y,x+cellwidth,y,0xffdce7ee);d.line(x+cellwidth,y,x+cellwidth,y+rowheight,0xffdce7ee);d.line(x+cellwidth,y+rowheight,x,y+rowheight,0xffdce7ee);d.line(x,y+rowheight,x,y,0xffdce7ee);}
    d.text(full_number(rms[point],2),x+3,y+4,14);
   }
  }
  d.text("P"+std::to_string(selected+1)+" / 频谱",FULL_LEFT+24,500,18);
  const double x=FULL_LEFT+62,y=540,w=FULL_WIDTH-100,h=112;double low=1e99,high=-1e99;
  for(int k=0;k<display_bins;k++){double q=full_db(value(selected,k));low=std::min(low,q);high=std::max(high,q);}low=std::floor(low/10)*10;high=std::ceil(high/10)*10;if(high<=low)high=low+10;
  for(int i=0;i<=2;i++){double py=y+h*i/2;d.line(x,py,x+w,py,0xff293b47,.8);d.text(full_number(high-(high-low)*i/2,0),x-36,py-7,13);}
  double px=x,py=y+h;
  for(int col=0;col<400;col++){int a=col*display_bins/400,b=(col+1)*display_bins/400;double q=-1e99;for(int k=a;k<b;k++)q=std::max(q,full_db(value(selected,k)));double qx=x+(col+.5)*w/400,qy=y+h-(q-low)/(high-low)*h;if(col)d.line(px,py,qx,qy,0xffcbd7df,1.1);px=qx;py=qy;}
  for(int i=0;i<=5;i++)d.text(v.raw_board?full_number(i*21.9/5,1):std::to_string(i*5),x+i*w/5-4,y+h+10,14);
  d.text("MHz",976,680,14);
 }
 board_control(d,v);if(v.cursor_visible)d.image(v.cursor_x,v.cursor_y,32,48,1984,1488,32,48,65530);
}

template<class V>int raw_matrix_pick(const V &v,int x,int y)const{
 if(v.mode!=15)return -1;const auto &xx=v.raw_board?raw_dc_x:xs;const auto &yy=v.raw_board?raw_dc_y:ys;
 if(xx.empty()||yy.empty()||x<FULL_LEFT+62||x>=1018||y<180||y>=180+int(yy.size())*26)return -1;
 int col=std::min(int(xx.size())-1,int((x-FULL_LEFT-62)*xx.size()/(FULL_WIDTH-92))),row=(y-180)/26;
 return v.raw_board?raw_dc_grid[row*xx.size()+col]:row*xx.size()+col;
}
