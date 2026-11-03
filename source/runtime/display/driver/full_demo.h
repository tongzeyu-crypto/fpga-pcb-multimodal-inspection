#ifndef PCB_FULL_DEMO_H
#define PCB_FULL_DEMO_H
// Consumes only the PS demo supervisor's atomic snapshot. No MMIO/serial access.
struct FullDemo {
 struct Point {double x=0,y=0;int ready=0;double power[33]={};};
 bool available=false;unsigned revision=0;int state=0,completed=0,ordinal=0,frames=0;
 double minimum=0,maximum=0;int max_index=0,hot_count=0;
 Point points[6];double temperatures[256]={},rgb[256]={},thermal[256]={};
 void refresh(const std::string &path){
  std::ifstream f(path);if(!f){available=false;return;}
  FullDemo next;std::string magic;
  if(!(f>>magic>>next.revision>>next.state>>next.completed>>next.ordinal>>next.frames)||magic!="PDPVIEW1"||next.state<0||next.state>9||next.completed<0||next.completed>6||next.ordinal<0||next.ordinal>5)return;
  for(auto &p:next.points){if(!(f>>p.x>>p.y>>p.ready))return;for(double &v:p.power)if(!(f>>v)||!std::isfinite(v)||v<0)return;}
  if(!(f>>next.minimum>>next.maximum>>next.max_index>>next.hot_count))return;
  for(auto values:{next.temperatures,next.rgb,next.thermal})for(int i=0;i<256;i++)if(!(f>>values[i])||!std::isfinite(values[i]))return;
  next.available=true;*this=next;
 }
 static const char *state_name(int n){static const char *names[]={"等待开始","生成路线","移动中","到点确认","停稳等待","三帧采样","采样关联","演示完成","演示失败","演示停止"};return names[std::max(0,std::min(9,n))];}
 template<class V>void draw(FullDraw &d,const V &v){
  d.rect(0,0,1280,720,0xff0d1722);d.rect(0,0,1280,54,0xff14242f);
  d.text("桌面PCB多模态检测系统",18,10,26);d.text("扫描演示",400,17,18);
  d.rect(0,54,160,666,0xff12212c);d.rect(1048,54,232,666,0xff12212c);
  d.text("离线回放 / 模拟运动",184,68,20);
  d.text("历史原始数据 / RTL 仿真结果",184,98,17);
  if(!v.raw_board){d.text("STM32 原始数据未就绪",240,280,24);d.text("请选择 DC-DC 模块运行扫描演示",240,322,20);return;}
  if(!available){d.text("请从主程序启动离线演示",240,280,24);return;}
  const int selected=std::max(0,std::min(5,v.demo_point));const auto &p=points[selected];
  d.text("扫描路线 / mm",184,146,20);
  for(int i=0;i<6;i++){
   double x=222+points[i].x*19,y=212+points[i].y*16;
   if(i<5)d.line(x,y,222+points[i+1].x*19,212+points[i+1].y*16,0xff36515f,3);
  }
  for(int i=0;i<6;i++){
   double x=222+points[i].x*19,y=212+points[i].y*16;
   d.rect(x-13,y-13,26,26,points[i].ready?0xff6cbfcb:0xff36515f);
   if(i==selected){d.line(x-18,y-18,x+18,y-18,0xffffed9b,2);d.line(x-18,y+18,x+18,y+18,0xffffed9b,2);}
   d.text(std::to_string(i+1),x-6,y-12,18);
  }
  d.text(std::string(state_name(state))+"  "+std::to_string(completed)+" / 6 点",184,335,22);
  d.text("当前点 "+std::to_string(ordinal+1)+" / 三帧功率平均",184,368,17);
  d.text("64 点频谱 / ADC codes squared",520,146,18);
  const double left=538,top=202,width=464,height=150;
  d.line(left,top+height,left+width,top+height,0xff36515f);d.line(left,top,left,top+height,0xff36515f);
  if(p.ready){double highest=1;for(double q:p.power)highest=std::max(highest,q);double ceiling=std::log10(1+highest);
   for(int i=0;i<32;i++)d.line(left+i*width/32,top+height-height*std::log10(1+p.power[i])/ceiling,left+(i+1)*width/32,top+height-height*std::log10(1+p.power[i+1])/ceiling,0xff82dce5,2);
  }else d.text("等待所选点采样关联",600,262,18);
  d.text("0",530,358,15);d.text("25 MHz",934,358,15);d.text("log(1 + power)",538,386,15);
  d.line(184,426,1022,426,0xff36515f);
  d.text("热像温度 / 16 x 16",184,444,18);
  d.text("RGB 灰度量化",490,444,18);d.text("热像共享量化",764,444,18);
  for(int i=0;i<256;i++){int x=i%16,y=i/16;
   d.rect(184+x*10,481+y*10,10,10,full_color((temperatures[i]-minimum)/std::max(1.,maximum-minimum)));
   for(int mode=0;mode<2;mode++){int q=std::max(0,std::min(255,int((mode?thermal:rgb)[i])+128));d.rect((mode?764:490)+x*10,481+y*10,10,10,0xff000000u|(q<<16)|(q<<8)|q);}
  }
  d.text(full_number(minimum/1000,2)+" ~ "+full_number(maximum/1000,2)+" C",184,648,16);
  d.text("热点 >= 40 C: "+std::to_string(hot_count),184,675,16);
  d.text("共享计算路径 / INT8",490,655,16);
  d.text("子采样功能演示",764,655,16);
  d.text("扫描调度",1060,64,21);
  auto button=[&](int y,const std::string &s){d.rect(1060,y,204,32,0xff233c4a);d.text(s,1069,y+2,17);};
  button(100,state>=1&&state<=6?"扫描进行中":"开始 / 重新演示");button(144,"停止并清空");
  button(200,"< 选择结果点 >");d.text("点 "+std::to_string(selected+1)+" / 6",1064,244,20);
  d.text(full_number(p.x,0)+", "+full_number(p.y,0)+" mm",1064,276,18);
  d.text(p.ready?"已关联 3 帧":"等待采样",1064,308,18);
  d.text("PS 路线调度",1064,374,18);d.text("到点状态确认",1064,406,18);d.text("停稳等待 0.7 s",1064,438,18);d.text("三帧采样关联",1064,470,18);
  d.text("PL 计算结果回放",1064,538,17);d.text("历史数据回放",1064,570,17);
 }
};
#endif
