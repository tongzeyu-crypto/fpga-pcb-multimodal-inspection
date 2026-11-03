#ifndef HDMI_FULL_AOI_H
#define HDMI_FULL_AOI_H
#include "full_layout.h"
// AOI display snapshots contain only data produced by the separate AOI service.
// No measurement is inferred from a rendered pixel or from the RGB/thermal model.
struct FullAoiRegion {double x=0,y=0,w=0,h=0;std::string kind,component;};
struct FullAoi {
 std::string root,run,status="OFFLINE",state;int width=0,height=0,texture_height=0;
 double crop_x=0,crop_y=0,crop_width=0,crop_height=0;
 std::vector<FullAoiRegion> regions;bool available=false;
 static bool valid_id(const std::string &s){
  if(s.size()!=22||s[8]!='-'||s[15]!='-')return false;
  for(size_t i=0;i<s.size();i++){if(i==8||i==15)continue;char c=s[i];if(i<15){if(c<'0'||c>'9')return false;}else if(!((c>='0'&&c<='9')||(c>='a'&&c<='f')))return false;}
  return true;
 }
 bool refresh(const std::string &directory){
  std::string next_status="OFFLINE",next_run;std::ifstream status_file(directory+"/status.txt");status_file>>next_status;
  if(next_status!="READY"&&next_status!="BUSY"&&next_status!="FAILED"&&next_status!="EMPTY")next_status="OFFLINE";
  std::ifstream current(directory+"/current.txt");current>>next_run;
  bool changed=next_status!=status;status=next_status;root=directory;
  // A published run whose metadata or texture vanished is not a valid result.
  // Never display the previous image as if it belonged to that new run.
  auto invalid=[&](){bool updated=status!="OFFLINE"||available||!run.empty()||!regions.empty();
   status="OFFLINE";available=false;run.clear();regions.clear();return changed||updated;};
  if(!valid_id(next_run)){if(available||next_status=="READY")return invalid();return changed;}
  if(next_run==run&&available)return changed;
  std::ifstream meta(directory+"/"+next_run+"/display.txt");std::string magic,header;
  if(!std::getline(meta,magic)||magic!="AOI1_8X4"||!std::getline(meta,header))return invalid();
  std::istringstream first(header);std::string id,next_state;int w,h,th,count;
  if(!(first>>id>>w>>h>>th>>count>>next_state)||id!=next_run||w<=0||h<=0||w>10000||h>10000||th<=0||th>1024||count<0||count>64)return invalid();
  std::vector<FullAoiRegion> next;std::string line;
  for(int i=0;i<count;i++){
   if(!std::getline(meta,line))return invalid();size_t a=line.find('\t'),b=a==std::string::npos?a:line.find('\t',a+1);
   if(a==std::string::npos||b==std::string::npos)return invalid();
   FullAoiRegion item;std::istringstream numbers(line.substr(0,a));
   if(!(numbers>>item.x>>item.y>>item.w>>item.h)||!std::isfinite(item.x)||!std::isfinite(item.y)||!std::isfinite(item.w)||!std::isfinite(item.h)||
      item.x<0||item.y<0||item.w<=0||item.h<=0||item.x+item.w>w+2||item.y+item.h>h+2)return invalid();
   item.kind=line.substr(a+1,b-a-1);item.component=line.substr(b+1);
   if(item.kind.empty()||item.kind.size()>256||item.component.size()>256)return invalid();
   next.push_back(item);
  }
  std::ifstream gray(directory+"/"+id+"/gray.bin",std::ios::binary|std::ios::ate),rgb(directory+"/"+id+"/rgb.bin",std::ios::binary|std::ios::ate);
  const size_t expected=5592704; // 1024x1024 BGRA, 11 tiled mip levels.
  if(!gray||!rgb||size_t(gray.tellg())!=expected||size_t(rgb.tellg())!=expected)return invalid();
  run=id;width=w;height=h;texture_height=th;state=next_state;regions.swap(next);available=true;
  crop_x=0;crop_y=0;crop_width=w;crop_height=h;
  std::ifstream crop(directory+"/display-crop.txt");std::string crop_magic;int source_w,source_h;double cx,cy,cw,ch;
  if(crop>>crop_magic>>source_w>>source_h>>cx>>cy>>cw>>ch){
   bool valid=crop_magic=="AOICROP1"&&source_w==w&&source_h==h&&std::isfinite(cx)&&std::isfinite(cy)&&std::isfinite(cw)&&std::isfinite(ch)&&cx>=0&&cy>=0&&cw>0&&ch>0&&cx+cw<=w&&cy+ch<=h;
   for(const auto &r:regions)valid=valid&&r.x>=cx&&r.y>=cy&&r.x+r.w<=cx+cw&&r.y+r.h<=cy+ch;
   if(valid){crop_x=cx;crop_y=cy;crop_width=cw;crop_height=ch;}
  }
  return true;
 }
 std::string texture_path(int variant)const{return root+"/"+run+(variant?"/rgb.bin":"/gray.bin");}
 static double image_y(){return 92.;}
 double image_width()const{return crop_height?std::min(double(FULL_WIDTH-34.),(554.-image_y()-10.)*crop_width/crop_height):FULL_WIDTH-34.;}
 double image_x()const{return FULL_LEFT+(FULL_WIDTH-image_width())*.5;}
 double image_height()const{return crop_width?image_width()*crop_height/crop_width:0.;}
 template<class V>double left(const V &v)const{return image_x()+image_width()*.5*(1-v.aoi_zoom)+v.aoi_pan_x;}
 template<class V>double top(const V &v)const{return image_y()+image_height()*.5*(1-v.aoi_zoom)+v.aoi_pan_y;}
 template<class V>int pick(const V &v,int x,int y)const{
  if(!available||x<FULL_LEFT||x>=FULL_RIGHT||y<54||y>=554)return -1;
  double w=image_width()*v.aoi_zoom,h=image_height()*v.aoi_zoom;
  double bx=crop_x+(x-left(v))*crop_width/w,by=crop_y+(y-top(v))*crop_height/h;
  if(bx<crop_x||by<crop_y||bx>=crop_x+crop_width||by>=crop_y+crop_height)return -1;
  int selected=-1;double smallest=1e100;
  for(size_t i=0;i<regions.size();i++){const auto &r=regions[i];double pad=12.;
   if(bx>=r.x-pad&&by>=r.y-pad&&bx<=r.x+r.w+pad&&by<=r.y+r.h+pad&&r.w*r.h<smallest){smallest=r.w*r.h;selected=int(i);}}
  return selected;
 }
 template<class V>void zoom_at(V &v,int x,int y,double wheel)const{
  double old=v.aoi_zoom,next=std::max(1.,std::min(4.,old*std::exp(wheel*.12)));
  if(available){double cx=image_x()+image_width()*.5,cy=image_y()+image_height()*.5;
   v.aoi_pan_x=(x-cx)-(x-cx-v.aoi_pan_x)*next/old;
   v.aoi_pan_y=(y-cy)-(y-cy-v.aoi_pan_y)*next/old;
   v.aoi_pan_x=std::max(-1100.,std::min(1100.,v.aoi_pan_x));v.aoi_pan_y=std::max(-800.,std::min(800.,v.aoi_pan_y));
  }
  v.aoi_zoom=next;
 }
 template<class V>void picture(FullDraw &d,const V &v)const{
  if(!available){d.rect(FULL_LEFT+14,92,FULL_WIDTH-34,450,0xff182b35);d.text("等待照片",390,280,24);return;}
  double x=left(v),y=top(v),w=image_width()*v.aoi_zoom,h=image_height()*v.aoi_zoom;
  double x0=std::max(double(FULL_LEFT),x),y0=std::max(54.,y),x1=std::min(1048.,x+w),y1=std::min(554.,y+h);
  double texture_v=double(texture_height-1)/1023.;
  if(x1>x0&&y1>y0)d.rgb_image(x0,y0,x1-x0,y1-y0,(crop_x+(x0-x)/w*crop_width)/width,(crop_y+(y0-y)/h*crop_height)/height*texture_v,(crop_x+(x1-x)/w*crop_width)/width,(crop_y+(y1-y)/h*crop_height)/height*texture_v);
  int selected=regions.empty()?-1:std::max(0,std::min(int(regions.size())-1,v.aoi_selected));
  for(size_t i=0;i<regions.size();i++){
   const auto &r=regions[i];double a=x+(r.x-crop_x)*w/crop_width,b=y+(r.y-crop_y)*h/crop_height,c=r.w*w/crop_width,e=r.h*h/crop_height;
   if(a+c<FULL_LEFT||a>1048||b+e<54||b>554)continue;
   uint32_t color=int(i)==selected?0xffffca6b:0xff6be0da;double t=int(i)==selected?2.8:1.5;
   double l=std::max(double(FULL_LEFT),a),rgt=std::min(1048.,a+c),top=std::max(54.,b),bottom=std::min(554.,b+e);
   if(b>=54&&b<=554)d.line(l,b,rgt,b,color,t);if(a+c>=FULL_LEFT&&a+c<=1048)d.line(a+c,top,a+c,bottom,color,t);
   if(b+e>=54&&b+e<=554)d.line(l,b+e,rgt,b+e,color,t);if(a>=FULL_LEFT&&a<=1048)d.line(a,top,a,bottom,color,t);
   double lx=std::max(double(FULL_LEFT),std::min(1026.,a)),ly=std::max(54.,std::min(536.,b-19));
   d.rect(lx,ly,22,18,int(i)==selected?0xff985b23:0xff245a63);d.text(std::to_string(i+1),lx+3,ly-1,13);
  }
 }
};
#endif
