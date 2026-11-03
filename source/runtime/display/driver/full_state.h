#ifndef HDMI_FULL_STATE_H
#define HDMI_FULL_STATE_H
#include <string>
#include "full_layout.h"
#include <cmath>
#include <algorithm>
struct FullState {
 int demo_point=0,demo_command=0,demo_request=0;
 int mode=0,base=0,band=0,scenario=0,point=93,points=1,components=1,hud=1,autorotate=0,raw_board=0;
 int emi_alpha=153,cursor_x=640,cursor_y=360,cursor_visible=1,time=0;
 int aoi_selected=0,aoi_variant=0;double aoi_zoom=1.,aoi_pan_x=0.,aoi_pan_y=0.;std::string aoi_run,aoi_status;
 double relief=.6,slice=8.;int board_menu=0,raw_image=0;double raw_zoom[2]={1,1},raw_x[2]={0,0},raw_y[2]={0,0};
 unsigned selected_component=0;uint64_t cursor_revision=1,view_revision=1,scene_revision=1,menu_revision=1;
};
static const char *full_modes[]={"三维融合","二维融合","发光热点","EMI地形","EMI等值线","","频率立方体","扫描差异","密度频谱","频谱瀑布","","","焊接缺陷","RGB","热像","EMI","扫描演示"};
static const int full_view_modes[]={0,1,3,6,12};
static const char *full_bases[]={"高对比灰度","原始颜色","黑白线稿"};
static const char *full_bands[]={"0.2-25 MHz","0.2-3 MHz","3-10 MHz","10-25 MHz","0.45-0.55 MHz"};
static const double full_band_lo[]={.2,.2,3.,10.,.45},full_band_hi[]={25.,3.,10.,25.,.55};
struct FullRect {int x,y,w,h;bool contains(int a,int b)const{return a>=x&&b>=y&&a<x+w&&b<y+h;}};
template<class V> static void full_preset(V &v,int which){
 v.pose=GfxView();v.pose.zoom=v.raw_board?.62:.78;v.raw_zoom[0]=v.raw_zoom[1]=1;v.raw_x[0]=v.raw_x[1]=v.raw_y[0]=v.raw_y[1]=0;
 if(which==1){v.pose.yaw=0;v.pose.polar=.05;v.pose.zoom=.82;}
 if(which==2){v.pose.yaw=0;v.pose.polar=1.25;v.pose.zoom=.78;}
}
template<class V> static bool full_action(V &v,const std::string &key,double value,int point_count){
 if(!std::isfinite(value)||std::abs(value)>10000000)return false;
 if(key!="relief"&&key!="slice"&&key!="yaw"&&key!="polar"&&key!="zoom"&&key!="x"&&key!="y"&&key!="z"&&key!="aoi_zoom"&&key!="aoi_pan_x"&&key!="aoi_pan_y"&&value!=std::trunc(value))return false;
 int n=int(value);
 if(key=="mode"){if(n<0||n>16||n==2||n==4||n==5||n==7||n==8||n==9||n==10||n==11)return false;v.mode=n;full_preset(v,(n==1||n==4||n==7)?1:0);if(n==6)v.pose.zoom=.58;
  if(n==2||n==4||n==5||n==7||n==10||n==11)v.heat=0;else if((n==0||n==1||n==3||n==6)&&!v.heat)v.heat=179;
  if(n==10)v.base=1;
 }
 else if(key=="demo_point"){if(n<0||n>5)return false;v.demo_point=n;}
 else if(key=="demo_request"){if(n<1||n>2)return false;v.demo_request=n;v.demo_command++;}
 else if(key=="base"){if(n<0||n>2)return false;v.base=n;}
 else if(key=="raw_board"){if(n<0||n>1)return false;if(n!=v.raw_board)v.relief=n?2.:.6;v.raw_board=n;v.point=0;v.board_menu=0;v.aoi_selected=0;v.aoi_zoom=1.;v.aoi_pan_x=v.aoi_pan_y=0.;full_preset(v,v.mode==1?1:0);}
 else if(key=="heat"){if(n<0||n>255)return false;v.heat=n;}
 else if(key=="emi"){if(n<0||n>1)return false;v.emi=n;}
 else if(key=="emi_alpha"){if(n<0||n>255)return false;v.emi_alpha=n;}
 else if(key=="relief"){if(value<.1||value>2)return false;v.relief=value;}
 else if(key=="band"){if(n<0||n>4)return false;v.band=n;}
 else if(key=="scenario"){if(n!=0)return false;v.scenario=0;}
 else if(key=="point"){if(n<0||n>=point_count)return false;v.point=n;}
 else if(key=="slice"){if(value<.2||value>25)return false;v.slice=value;}
 else if(key=="time"){if(n<0||n>=160)return false;v.time=n;}
 else if(key=="aoi_variant"){if(n<0||n>1)return false;v.aoi_variant=n;}
 else if(key=="aoi_selected"){if(n<0||n>=64)return false;v.aoi_selected=n;}
 else if(key=="aoi_zoom"){if(value<1||value>4)return false;v.aoi_zoom=value;}
 else if(key=="aoi_pan_x"||key=="aoi_pan_y"){if(std::abs(value)>1100)return false;if(key=="aoi_pan_x")v.aoi_pan_x=value;else v.aoi_pan_y=value;}
 else if(key=="points"||key=="components"||key=="hud"||key=="autorotate"||key=="cursor_visible"||key=="native"){
  if(n<0||n>1)return false;
  if(key=="points")v.points=n;else if(key=="components")v.components=n;else if(key=="hud")v.hud=n;
  else if(key=="autorotate")v.autorotate=n;else if(key=="cursor_visible")v.cursor_visible=n;else v.native=n;
 }else if(key=="fit"){full_preset(v,0);}
 else if(key=="preset"){if(n<0||n>2)return false;if(v.mode==12){v.aoi_zoom=1.;v.aoi_pan_x=v.aoi_pan_y=0.;}else full_preset(v,n);}
 else if(key=="yaw"){if(std::abs(value)>10000)return false;v.pose.yaw=value;}
 else if(key=="polar"){if(value<.05||value>3.09)return false;v.pose.polar=value;}
 else if(key=="zoom"){if(value<.2||value>8.0)return false;v.pose.zoom=value;}
 else if(key=="x"||key=="y"||key=="z"){if(std::abs(value)>100)return false;v.pose.target[key=="x"?0:key=="y"?1:2]=value;}
 else return false;
 return true;
}
// One hit-test definition is shared by the HDMI GUI and USB/browser inputs.
template<class V> static bool full_click(V &v,int x,int y,int count,int aoi_count=0){
 if(v.board_menu){int board=y>=46&&y<82?0:y>=82&&y<118?1:-1;v.board_menu=0;if(x>=892&&x<1082&&board>=0)full_action(v,"raw_board",board,count);return true;}
 if(FullRect{892,10,190,34}.contains(x,y)){v.board_menu=1;return true;}
 if(FullRect{1112,12,152,32}.contains(x,y)){v.hud=!v.hud;return true;}
 if(!v.hud)return false;
 if(x>=12&&x<FULL_LEFT-12){
  if(y>=278&&y<314)return full_action(v,"mode",16,count);
  if(y>=96&&y<246)return full_action(v,"mode",full_view_modes[(y-96)/30],count);
  for(int i=0;i<3;i++)if(y>=462+i*40&&y<494+i*40)return full_action(v,"mode",13+i,count);
 }
 if(v.mode==16){
  if(FullRect{1060,100,204,32}.contains(x,y)&&v.raw_board)return full_action(v,"demo_request",1,count);
  if(FullRect{1060,144,204,32}.contains(x,y))return full_action(v,"demo_request",2,count);
  if(FullRect{1060,200,204,32}.contains(x,y))return full_action(v,"demo_point",(v.demo_point+(x<1160?5:1))%6,count);
  return true;
 }
 if(v.mode>=13){
  if(v.mode!=15&&FullRect{1060,182,204,32}.contains(x,y)){full_preset(v,0);return true;}
  if(v.mode==15&&x>=1060&&x<1264&&y>=300&&y<332){v.band=(v.band+1)%5;return true;}
  if(x>=1060&&x<1264&&y>=100&&y<132)return full_action(v,"raw_board",!v.raw_board,count);
  if(x>=1060&&x<1264&&y>=424&&y<456){int total=count;v.point=(v.point+(x<1160?total-1:1))%total;return true;}
  return x<FULL_LEFT||x>=FULL_RIGHT||y<54||y>=556;
 }
 if(v.mode==12&&x>=1060&&x<1264){
  if(y>=100&&y<132){v.aoi_variant=!v.aoi_variant;return true;}
  if(y>=144&&y<176){if(aoi_count>0)v.aoi_selected=(v.aoi_selected+(x<1160?aoi_count-1:1))%aoi_count;return true;}
  if(y>=182&&y<214){v.aoi_zoom=1.;v.aoi_pan_x=v.aoi_pan_y=0.;return true;}
  if(y>=244&&y<436){int index=(y-244)/32;if(index<aoi_count)v.aoi_selected=index;return true;}
  return true;
 }
 if(x>=1060&&x<1264){
  if(y>=98&&y<128){v.heat=v.heat?0:179;return true;}
  if(y>=138&&y<160){v.heat=std::max(0,std::min(255,(x-1068)*255/180));return true;}
  if(y>=178&&y<208){v.emi=!v.emi;return true;}
  if(y>=216&&y<240){v.emi_alpha=std::max(0,std::min(255,(x-1068)*255/180));return true;}
  if(y>=266&&y<286){v.relief=.1+std::max(0,std::min(180,x-1068))/180.*1.9;return true;}
  if(y>=300&&y<332){v.base=(v.base+1)%3;return true;}
  if(y>=342&&y<374){if(v.mode==6)v.slice=std::max(.2,std::min(25.,v.slice+(x<1160?-.5:.5)));else v.band=(v.band+1)%5;return true;}
  if(y>=382&&y<414){v.scenario=0;return true;}
  if(y>=424&&y<456){v.point=(v.point+(x<1160?count-1:1))%count;return true;}
  if(y>=466&&y<496){v.points=!v.points;return true;}
  if(y>=504&&y<536){full_preset(v,std::min(2,(x-1060)/68));return true;}
  if(y>=548&&y<580){v.autorotate=!v.autorotate;return true;}
  if(y>=588&&y<620){v.components=!v.components;return true;}
 }
 return x<FULL_LEFT||x>=FULL_RIGHT||y<54||y>=556;
}
struct FullDrag {bool left=false,right=false;int start_x=0,start_y=0,total=0,slider=0;};
#endif
