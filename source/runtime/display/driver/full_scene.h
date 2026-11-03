#ifndef HDMI_FULL_SCENE_H
#define HDMI_FULL_SCENE_H
#include <array>
#include <limits>
#include <set>
struct FullPoint {float x,y,wx,wz,temp;};
struct FullGlyph {uint32_t code;uint16_t x,y,w,h,advance,reserved;};
static_assert(sizeof(FullGlyph)==16,"glyph record");
template<class T> static std::vector<T> full_read(const std::string &path){
 std::ifstream f(path,std::ios::binary|std::ios::ate);
#ifndef _WIN32
 if(!f&&std::ifstream(path+".gz")){
  if(path.find('\'')!=std::string::npos)throw std::runtime_error("invalid asset path");
  std::string cmd="gzip -dc '"+path+".gz'";FILE *pipe=popen(cmd.c_str(),"r");if(!pipe)throw std::runtime_error("gzip stream");
  std::vector<T> result;result.reserve((24UL<<20)/sizeof(T));unsigned char chunk[65536];size_t n;
  while((n=fread(chunk,1,sizeof(chunk),pipe))){if(n%sizeof(T)){pclose(pipe);throw std::runtime_error("compressed alignment");}size_t old=result.size();result.resize(old+n/sizeof(T));memcpy(result.data()+old,chunk,n);}
  if(pclose(pipe))throw std::runtime_error("compressed asset failed");return result;
 }
#endif
 if(!f)throw std::runtime_error("missing full asset: "+path);
 size_t n=f.tellg();if(n%sizeof(T))throw std::runtime_error("invalid full asset size: "+path);
 std::vector<T> r(n/sizeof(T));f.seekg(0);f.read(reinterpret_cast<char*>(r.data()),n);if(!f)throw std::runtime_error("short full asset: "+path);return r;
}
static double full_db(double a){return 10*std::log10(std::max(1e-30,a));}
static uint32_t full_color(double q,int alpha=255){
 const int c[6][3]={{5,18,48},{13,86,164},{22,194,219},{112,232,210},{255,190,84},{255,243,199}};
 q=std::max(0.,std::min(1.,q))*5;int i=std::min(4,int(q));double a=q-i;
 int r=c[i][0]*(1-a)+c[i+1][0]*a,g=c[i][1]*(1-a)+c[i+1][1]*a,b=c[i][2]*(1-a)+c[i+1][2]*a;
 return (uint32_t(alpha)<<24)|(r<<16)|(g<<8)|b;
}
static uint32_t full_uv(double u,double v){return uint32_t(std::llround(std::max(0.,std::min(1.,u))*65535))|(uint32_t(std::llround(std::max(0.,std::min(1.,v))*65535))<<16);}
static int32_t full_q(double a){return int32_t(std::llround(a*65536));}
struct FullDraw {
 std::vector<gfx_command> commands;std::map<uint32_t,FullGlyph> *glyphs;
 FullDraw(std::map<uint32_t,FullGlyph> &g):glyphs(&g){commands.reserve(12000);}
 void tri(double x0,double y0,double x1,double y1,double x2,double y2,uint32_t color,uint16_t z=0,uint16_t id=65000){
  gfx_command c={};c.opcode_flags=GFX_SCREEN_TRIANGLE;c.argb=color;c.object_id=id;
  c.v[0]={full_q(x0),full_q(y0),z,0};c.v[1]={full_q(x1),full_q(y1),z,0};c.v[2]={full_q(x2),full_q(y2),z,0};commands.push_back(c);
 }
 void rect(double x,double y,double w,double h,uint32_t color,uint16_t z=0){tri(x,y,x+w,y,x+w,y+h,color,z);tri(x,y,x+w,y+h,x,y+h,color,z);}
 void image(double x,double y,double w,double h,int tx,int ty,int tw,int th,uint16_t id=65000){
  gfx_command c={};c.opcode_flags=GFX_SCREEN_TRIANGLE|GFX_TEXTURED|GFX_GROUND;c.object_id=id;c.argb=0xffffffff;
  double u0=double(tx)/2047,v0=double(ty)/2047,u1=double(tx+tw-1)/2047,v1=double(ty+th-1)/2047;
  c.v[0]={full_q(x),full_q(y),0,full_uv(u0,v0)};c.v[1]={full_q(x+w),full_q(y),0,full_uv(u1,v0)};c.v[2]={full_q(x+w),full_q(y+h),0,full_uv(u1,v1)};commands.push_back(c);
  c.v[1]=c.v[2];c.v[2]={full_q(x),full_q(y+h),0,full_uv(u0,v1)};commands.push_back(c);
 }
 void rgb_image(double x,double y,double w,double h,double u0,double v0,double u1,double v1){
  gfx_command c={};c.opcode_flags=GFX_SCREEN_TRIANGLE|GFX_TEXTURED;c.object_id=64998;c.argb=0xffffffff;
  c.v[0]={full_q(x),full_q(y),0,full_uv(u0,v0)};c.v[1]={full_q(x+w),full_q(y),0,full_uv(u1,v0)};c.v[2]={full_q(x+w),full_q(y+h),0,full_uv(u1,v1)};commands.push_back(c);
  c.v[1]=c.v[2];c.v[2]={full_q(x),full_q(y+h),0,full_uv(u0,v1)};commands.push_back(c);
 }
 void text(const std::string &s,double x,double y,double size=20){
  for(size_t i=0;i<s.size();){uint32_t c=static_cast<unsigned char>(s[i++]);
   if(c>=0xf0){c&=7;for(int k=0;k<3&&i<s.size();k++)c=(c<<6)|(s[i++]&63);}
   else if(c>=0xe0){c&=15;for(int k=0;k<2&&i<s.size();k++)c=(c<<6)|(s[i++]&63);}
   else if(c>=0xc0){c&=31;if(i<s.size())c=(c<<6)|(s[i++]&63);}
   auto f=glyphs->find(c);if(f==glyphs->end())f=glyphs->find('?');if(f==glyphs->end())continue;
   const auto &g=f->second;double scale=size/24.;image(x,y,32*scale,32*scale,g.x,g.y,g.w,g.h);x+=g.advance*scale;
  }
 }
 void line(double x0,double y0,double x1,double y1,uint32_t color,double width=1.2){
  double dx=x1-x0,dy=y1-y0,l=std::hypot(dx,dy);if(l<.01)return;double ax=-dy/l*width/2,ay=dx/l*width/2;
  tri(x0-ax,y0-ay,x1-ax,y1-ay,x1+ax,y1+ay,color);tri(x0-ax,y0-ay,x1+ax,y1+ay,x0+ax,y0+ay,color);
 }
 void world(std::array<double,3> a,std::array<double,3>b,std::array<double,3>c,uint32_t color,int id=30000){
  gfx_command v={};v.opcode_flags=GFX_TRIANGLE;v.argb=color;v.object_id=id;
  auto p={a,b,c};int i=0;for(auto &q:p)v.v[i++]={full_q(q[0]),full_q(q[1]),full_q(q[2]),0};commands.push_back(v);
 }
 void world_line(std::array<double,3>a,std::array<double,3>b,uint32_t color,double width=.065){
  double dx=b[0]-a[0],dz=b[2]-a[2],l=std::hypot(dx,dz);if(l<.0001)return;
  double x=-dz/l*width,z=dx/l*width;
  world({a[0]-x,a[1],a[2]-z},{b[0]-x,b[1],b[2]-z},{b[0]+x,b[1],b[2]+z},color);
  world({a[0]-x,a[1],a[2]-z},{b[0]+x,b[1],b[2]+z},{a[0]+x,a[1],a[2]+z},color);
 }
 void sprite(double x,double y,double z,double pixels,uint32_t color,uint16_t id){
  gfx_command c={};c.opcode_flags=GFX_SPRITE;c.argb=color;c.object_id=id;c.v[0]={full_q(x),full_q(y),full_q(z),0};c.v[1]={full_q(pixels),full_q(pixels),0,0};commands.push_back(c);
 }
};
#include "full_aoi.h"
static std::string full_number(double v,int digits=1){if(!std::isfinite(v))return "--";std::ostringstream o;o<<std::fixed<<std::setprecision(digits)<<v;return o.str();}
#include "full_demo.h"
struct FullScene {
 FullDemo demo;std::string demo_path;
 FullAoi aoi;
 unsigned available_modalities=0;std::string capture_identity;
 std::array<std::array<double,4>,5> raw_rects={};std::vector<float> raw_dc_frequency,raw_dc_psd;std::vector<double> raw_dc_x,raw_dc_y;std::vector<int> raw_dc_grid;
 std::vector<gfx_command> model,flat;std::vector<FullPoint> points;std::vector<float> psd,heights;
 std::map<uint32_t,FullGlyph> glyphs;uint32_t meta[12]={};
 std::vector<double> powers,power_before,power_after,difference,xs,ys,sequence_values;double lo=0,hi=1,delta_limit=1,spectrum_lo=-100,spectrum_hi=0;
 int field_band=-1,field_scenario=-1,time_point=-1,time_scenario=-1;const int columns=128,rows=48,times=160;
 double df=25000000./4096,frequency_max=25.;bool dcdc_fixture=false;
 bool background_fixture=false;double background_span=12,background_offset=2,background_delta=3;
 #include "full_capture_data.h"
 explicit FullScene(const std::string &root){
  demo_path=root+"/demo-view.txt";
  std::ifstream state(root+"/capture-state.txt");
  if(!(state>>available_modalities>>capture_identity))throw std::runtime_error("source-verified capture-state required");
  dcdc_fixture=bool(std::ifstream(root+"/dcdc.flag"));
  std::ifstream frequency(root+"/frequency.txt");if(frequency.good())frequency>>df>>frequency_max;
  auto h=full_read<uint32_t>(root+"/full.meta");if(h.size()!=12||h[0]!=0x48444631)throw std::runtime_error("full scene identity");std::copy(h.begin(),h.end(),meta);
  auto gs=full_read<FullGlyph>(root+"/glyphs.bin");for(const auto &g:gs)glyphs[g.code]=g;
  model=full_read<gfx_command>(root+"/model.bin");flat=full_read<gfx_command>(root+"/flat.bin");
  points=full_read<FullPoint>(root+"/points.f32");psd=full_read<float>(root+"/psd.f32");
  if(points.empty()||meta[4]<2||psd.size()!=2*points.size()*meta[4])throw std::runtime_error("verified scene shapes");
  std::ifstream layout(root+"/raw-layout.txt");for(auto &r:raw_rects)for(double &q:r)if(!(layout>>q))throw std::runtime_error("raw atlas layout");
  if(available_modalities&4){
   raw_dc_frequency=full_read<float>(root+"/raw-dcdc-frequency.f32");raw_dc_psd=full_read<float>(root+"/raw-dcdc-psd.f32");
   auto xy=full_read<float>(root+"/raw-dcdc-coordinates.f32");
   if(raw_dc_frequency.size()!=meta[4]||raw_dc_psd.size()!=points.size()*meta[4]||xy.size()!=points.size()*2)throw std::runtime_error("raw spectrum dimensions");
   for(size_t i=0;i<points.size();i++){raw_dc_x.push_back(xy[i*2]);raw_dc_y.push_back(xy[i*2+1]);}
   std::sort(raw_dc_x.begin(),raw_dc_x.end());raw_dc_x.erase(std::unique(raw_dc_x.begin(),raw_dc_x.end()),raw_dc_x.end());
   std::sort(raw_dc_y.begin(),raw_dc_y.end());raw_dc_y.erase(std::unique(raw_dc_y.begin(),raw_dc_y.end()),raw_dc_y.end());
   for(double y:raw_dc_y)for(double x:raw_dc_x){int found=-1;for(size_t i=0;i<points.size();i++)if(xy[i*2]==x&&xy[i*2+1]==y){if(found!=-1)throw std::runtime_error("duplicate coordinate");found=i;}if(found<0)throw std::runtime_error("missing coordinate");raw_dc_grid.push_back(found);}
  }
  for(const auto &point:points){xs.push_back(point.x);ys.push_back(point.y);}
  std::sort(xs.begin(),xs.end());xs.erase(std::unique(xs.begin(),xs.end()),xs.end());std::sort(ys.begin(),ys.end());ys.erase(std::unique(ys.begin(),ys.end()),ys.end());
  // wx/wz are explicit mechanical coordinates. No stretching to the RGB board.
  heights.resize(points.size(),.1);
  for(size_t i=0;i<points.size();i++)for(const auto &c:model)if(c.opcode_flags&GFX_TEXTURED){
   double x[3],z[3],y[3];for(int a=0;a<3;a++){x[a]=c.v[a].x/65536.;y[a]=c.v[a].y/65536.;z[a]=c.v[a].z/65536.;}
   double den=(z[1]-z[2])*(x[0]-x[2])+(x[2]-x[1])*(z[0]-z[2]);if(std::abs(den)<1e-8)continue;
   double a=((z[1]-z[2])*(points[i].wx-x[2])+(x[2]-x[1])*(points[i].wz-z[2]))/den;
   double b=((z[2]-z[0])*(points[i].wx-x[2])+(x[0]-x[2])*(points[i].wz-z[2]))/den;
   if(a>=0&&b>=0&&a+b<=1)heights[i]=std::max<double>(heights[i],a*y[0]+b*y[1]+(1-a-b)*y[2]+.35);
  }
  load_capture_data(root);
 }
 double base(int p,int k,int)const{if(!(available_modalities&4))throw std::runtime_error("ADC missing");return psd.at(size_t(p)*meta[4]+k);}
 template<class V>void refresh(const V &v){
  if(v.band==field_band&&v.scenario==field_scenario)return;field_band=v.band;field_scenario=v.scenario;
  powers.assign(points.size(),0);power_before.assign(points.size(),0);power_after.assign(points.size(),0);difference.assign(points.size(),0);lo=1e99;hi=-1e99;delta_limit=0;
  for(size_t p=0;p<points.size();p++){double measured=band_value(p,v.band);double before=measured*measured,after=before;
   powers[p]=v.scenario==1?before:v.scenario==2?after:(before+after)*.5;
   power_before[p]=before;power_after[p]=after;
   difference[p]=full_db(after)-full_db(before);delta_limit=std::max(delta_limit,std::abs(difference[p]));lo=std::min(lo,full_db(powers[p]));hi=std::max(hi,full_db(powers[p]));}
  if(hi-lo<.01)hi=lo+.01;delta_limit=std::max(.01,delta_limit);
  if(background_fixture){double mean=0;for(size_t i=0;i<points.size();i++)mean+=(power_before[i]+power_after[i])*.5;double center=full_db(mean/points.size());lo=center-background_offset;hi=center+background_span-background_offset;delta_limit=std::max(background_delta,delta_limit);}
 }
 double interp(const std::vector<double> &values,double u,double v)const{
  // Mechanical interpolation v2: the final Y step is 4mm, not 5mm. Locate
  // cells using recorded physical coordinates instead of uniform grid indices.
  double px=xs.front()+std::max(0.,std::min(1.,u))*(xs.back()-xs.front());
  double py=ys.front()+std::max(0.,std::min(1.,v))*(ys.back()-ys.front());
  int a=std::max(0,std::min(int(xs.size())-2,int(std::upper_bound(xs.begin(),xs.end(),px)-xs.begin())-1));
  int b=std::max(0,std::min(int(ys.size())-2,int(std::upper_bound(ys.begin(),ys.end(),py)-ys.begin())-1));
  double x=(px-xs[a])/(xs[a+1]-xs[a]),y=(py-ys[b])/(ys[b+1]-ys[b]);size_t i=b*xs.size()+a;
  return values[i]*(1-x)*(1-y)+values[i+1]*x*(1-y)+values[i+xs.size()]*(1-x)*y+values[i+xs.size()+1]*x*y;
 }
 std::array<double,3> location(double u,double v,double h)const{
  // Bilinear coordinates use the actual retained corner positions, not an RGB bounding box.
  size_t nx=xs.size(),ny=ys.size();auto a=points[0],b=points[nx-1],c=points[(ny-1)*nx],d=points.back();
  return {a.wx*(1-u)*(1-v)+b.wx*u*(1-v)+c.wx*(1-u)*v+d.wx*u*v,h,a.wz*(1-u)*(1-v)+b.wz*u*(1-v)+c.wz*(1-u)*v+d.wz*u*v};
 }
 template<class V>void field(FullDraw &d,const V &v,bool surface,bool contours,bool difference_view){
  const int nx=34,ny=22;std::vector<std::array<double,3>> p;std::vector<double> q;
  for(int j=0;j<=ny;j++)for(int i=0;i<=nx;i++){double u=i/double(nx),w=j/double(ny),f=full_db(interp(powers,u,w));double z=(f-lo)/(hi-lo);q.push_back(difference_view?full_db(interp(power_after,u,w))-full_db(interp(power_before,u,w)):f);p.push_back(location(u,w,surface?5.9+z*14*v.relief:.19));}
  // A rigid display offset seats the minimum just above the PCB plane.
  if(surface){double floor=p.front()[1];for(const auto &vertex:p)floor=std::min(floor,vertex[1]);for(auto &vertex:p)vertex[1]+=.06-floor;}
  for(int j=0;j<ny;j++)for(int i=0;i<nx;i++){int a=j*(nx+1)+i,b=a+1,c=a+nx+1,e=c+1;
   if(surface||v.mode==5||difference_view){double val=(q[a]+q[b]+q[c]+q[e])*.25;uint32_t color;
    if(difference_view){double z=std::min(1.,std::abs(val)/delta_limit);color=val>=0?(uint32_t(v.emi_alpha)<<24)|(255<<16)|(int(210*(1-z))<<8)|int(190*(1-z)):(uint32_t(v.emi_alpha)<<24)|(int(160*(1-z))<<16)|(int(220*(1-z))<<8)|255;}
    else color=full_color(std::max(0.,std::min(1.,(val-lo)/(hi-lo))),v.emi_alpha);
    if(difference_view&&background_fixture){double t=std::min(1.,std::abs(val)/delta_limit);int r=224+(val>=0?31:-159)*t,g=235+(val>=0?-143:-81)*t,b=240+(val>=0?-156:15)*t;color=(uint32_t(v.emi_alpha)<<24)|(r<<16)|(g<<8)|b;}
    d.world(p[a],p[c],p[b],color);d.world(p[b],p[c],p[e],color);
   }
   if(contours)for(int level=1;level<8;level++){
    double target=lo+(hi-lo)*level/8.;int edges[4][2]={{a,b},{b,e},{e,c},{c,a}};std::vector<std::array<double,3>> crossing;
    for(auto &edge:edges){int k=edge[0],l=edge[1];if((q[k]<target)!=(q[l]<target)){double t=(target-q[k])/(q[l]-q[k]);crossing.push_back({p[k][0]+(p[l][0]-p[k][0])*t,p[k][1]+(p[l][1]-p[k][1])*t+.035,p[k][2]+(p[l][2]-p[k][2])*t});}}
    if(crossing.size()==2)d.world_line(crossing[0],crossing[1],0xe8b0f7f0,.052);
   }
  }
 }
 template<class V>void cube(FullDraw &d,const V &v){
  for(int layer=1;layer<=16;layer++){double f=layer*frequency_max/16;int k=std::min(int(meta[4])-1,int(f*1e6/df));double a=1e99,b=-1e99;
   for(size_t p=0;p<points.size();p++){double x=full_db(base(p,k,v.scenario));a=std::min(a,x);b=std::max(b,x);}
   if(background_fixture){double center=(a+b)*.5;a=center-background_offset;b=center+background_span-background_offset;}
   for(size_t p=0;p<points.size();p++){double q=(full_db(base(p,k,v.scenario))-a)/std::max(.01,b-a);if(q<.38)continue;d.sprite(points[p].wx,6+f*1.2*v.relief,points[p].wz,5+q*8,full_color(double(layer)/16,int(v.emi_alpha*q)),p+1000);}
  }
  double y=6+v.slice*1.2*v.relief;std::vector<double> slice_power(points.size(),0);double low=1e99,high=-1e99;
  int first=std::max(0,int(std::ceil((v.slice-.2)*1e6/df))),last=std::min(int(meta[4])-1,int(std::floor((v.slice+.2)*1e6/df)));
  for(size_t p=0;p<points.size();p++){for(int k=first;k<=last;k++)slice_power[p]+=base(p,k,v.scenario)*df;low=std::min(low,full_db(slice_power[p]));high=std::max(high,full_db(slice_power[p]));}
  if(background_fixture){double center=(low+high)*.5;low=center-background_offset;high=center+background_span-background_offset;}
  for(size_t i=0;i<points.size();i++){double q=(full_db(slice_power[i])-low)/std::max(.01,high-low);d.sprite(points[i].wx,y,points[i].wz,9,full_color(q,v.emi_alpha),1000+i);}
  auto a=location(0,0,y),b=location(1,0,y),c=location(1,1,y),e=location(0,1,y);d.world_line(a,b,0xffb5e9f7);d.world_line(b,c,0xffb5e9f7);d.world_line(c,e,0xffb5e9f7);d.world_line(e,a,0xffb5e9f7);
 }
 void make_sequence(int,int){throw std::runtime_error("No real time sequence in capture; synthetic sequence disabled");}
 template<class V>void signal_chart(FullDraw &d,const V &v){
  make_sequence(v.point,v.scenario);double x=262,y=144,w=752,h=332;
  d.text(v.mode==8?"密度频谱 / 模拟时间统计":"频谱瀑布 / 模拟时间",254,74,24);
  std::vector<int> hits(columns*rows,0);int maxhit=1;
  if(v.mode==8)for(int t=0;t<times;t++)for(int c=0;c<columns;c++){int r=std::max(0,std::min(rows-1,int((sequence_values[t*columns+c]-spectrum_lo)/(spectrum_hi-spectrum_lo)*rows)));maxhit=std::max(maxhit,++hits[r*columns+c]);}
  for(int r=0;r<rows;r++)for(int c=0;c<columns;c++){
   double q;if(v.mode==8){int count=hits[r*columns+c];if(!count)continue;q=std::sqrt(double(count)/maxhit);}
   else {int t=r*(times-1)/(rows-1);q=(sequence_values[t*columns+c]-spectrum_lo)/(spectrum_hi-spectrum_lo);}
   d.rect(x+c*w/columns,y+(rows-1-r)*h/rows,w/columns+.02,h/rows+.02,full_color(q));
  }
  for(int i=0;i<=5;i++){double a=x+w*i/5;d.line(a,y+h,a,y+h+6,0xffa3bcc9);d.text(std::to_string(i*5),a-8,y+h+9,16);}
  d.text("频率 / MHz",x+w-110,y+h+34,18);d.text(v.mode==8?"PSD / dB":"模拟时间 / s",x,y-28,18);
  for(int i=0;i<=3;i++)d.text(full_number(v.mode==8?spectrum_lo+(spectrum_hi-spectrum_lo)*i/3:12.72*i/3,0),228,y+h-h*i/3-8,14);
  d.text(v.mode==8?full_number(spectrum_lo,0)+" - "+full_number(spectrum_hi,0)+" dB":"0 - 12.72 s",x,y+h+34,18);
 }
 template<class V>void spectrum(FullDraw &d,const V &v){
  const double x=FULL_LEFT+38,y=598,w=FULL_WIDTH-74,h=82;
  double a=1e99,b=-1e99;for(int k=0;k<int(meta[4]);k++){double q=full_db(base(v.point,k,v.scenario));a=std::min(a,q);b=std::max(b,q);}a=std::floor(a/10)*10;b=std::ceil(b/10)*10;if(b-a<10)b=a+10;
  d.text("完整频谱 P"+std::to_string(v.point+1)+"",FULL_LEFT+20,560,18);
  d.text("0 - 25 MHz   PSD / dB",760,560,17);
  for(int i=0;i<=4;i++)d.line(x,y+h*i/4,x+w,y+h*i/4,0xff29404f,.8);
  double px=x,py=y+h;const int segments=300;
  for(int c=0;c<segments;c++){int start=c*int(meta[4])/segments,end=(c+1)*int(meta[4])/segments;double maxdb=-1e99;
   for(int k=start;k<end;k++)maxdb=std::max(maxdb,full_db(base(v.point,k,v.scenario)));
   double xx=x+(c+.5)*w/segments,yy=y+h-(maxdb-a)/(b-a)*h;if(c)d.line(px,py,xx,yy,0xff8debf0,1.3);px=xx;py=yy;
  }
  d.text(full_number(b,0),FULL_LEFT+10,y-8,13);d.text(full_number(a,0),FULL_LEFT+10,y+h-12,13);
  for(int i=0;i<=5;i++)d.text(full_number(i*frequency_max/5,frequency_max<25?1:0),x+i*w/5-4,684,14);
 }
#include "full_raw.h"
 template<class V>void hud(FullDraw &d,const V &v,const std::string &mouse,double /*render_ms*/,bool floating=true){
  if(available_modalities&4)refresh(v);
  if(v.mode==12){aoi_hud(d,v,mouse);return;}
  d.rect(0,0,1280,54,0xff14242f);d.text("桌面PCB多模态检测系统",18,10,26);
  d.rect(1112,12,152,32,0xff264856);d.text(v.hud?"隐藏面板":"显示面板",1130,14,19);
  if(v.hud){
   d.rect(0,54,FULL_LEFT,666,0xff12212c);d.rect(1048,54,232,666,0xff12212c);d.rect(FULL_LEFT,554,FULL_WIDTH,166,0xff101e29);
   sidebar(d,v);
   d.text("图层设置",1062,64,21);
   checkbox(d,1064,100,v.heat>0,"热像着色");slider(d,1068,143,v.heat/255.);d.text(std::to_string(v.heat*100/255)+"%",1204,116,14);
   checkbox(d,1064,180,v.emi,"电磁干扰");slider(d,1068,222,v.emi_alpha/255.);d.text(std::to_string(v.emi_alpha*100/255)+"%",1204,195,14);
   d.text("地形起伏 "+full_number(v.relief,2),1064,241,17);slider(d,1068,273,(v.relief-.1)/1.9);
   button(d,1060,300,204,32,full_bases[v.base]);button(d,1060,342,204,32,v.mode==6?"< "+full_number(v.slice,1)+" MHz >":full_bands[v.band]);
   button(d,1060,382,204,32,dcdc_fixture?"本次扫描":v.scenario==0?"功率平均":v.scenario==1?(background_fixture?"模拟 A":"扫描之前"):(background_fixture?"模拟 B":"扫描之后"));
   button(d,1060,424,96,32,"< P"+std::to_string(v.point+1));button(d,1164,424,100,32,"选择 >");
   checkbox(d,1064,468,v.points,"测点标记");
   button(d,1060,504,64,32,"复位");button(d,1128,504,64,32,"俯视");button(d,1196,504,68,32,"正视");
   checkbox(d,1064,550,v.autorotate,"自动旋转");checkbox(d,1064,590,v.components,"立体元件");
   if(available_modalities&4){d.text("总功率 "+full_number(full_db(powers[v.point]),1)+" dB",1060,636,15);spectrum(d,v);}
   else d.text("ADC WAITING",1060,636,15);
   if(v.temperature_valid)d.text("原始温度 "+full_number(v.temperature_c,2)+" C",1060,665,15);
   else d.text("TEMP: RAW PAGE",1060,665,15);
  }
  if(floating&&v.mode==6)d.text("频率 / MHz",v.hud?FULL_LEFT+30:24,70,19);
  if(floating&&v.mode==7)d.text(background_fixture?"模拟差异 / dB":"扫描前后差异 / dB",v.hud?FULL_LEFT+30:24,70,19);
  board_control(d,v);
 if(v.cursor_visible)d.image(v.cursor_x,v.cursor_y,32,48,1984,1488,32,48,65530);
 }
 template<class V>void board_control(FullDraw &d,const V &v){
  d.text("板卡",848,17,18);button(d,892,10,190,34,v.raw_board?"DC-DC 模块 v":"STM32 核心板 v");
  if(v.board_menu){d.rect(892,46,190,72,0xff233c4a);d.text("STM32 核心板",902,50,18);d.text("DC-DC 模块",902,86,18);}
 }
 static void button(FullDraw &d,int x,int y,int w,int h,const std::string&s){d.rect(x,y,w,h,0xff233c4a);d.text(s,x+9,y+2,17);}
 static void checkbox(FullDraw &d,int x,int y,int enabled,const std::string&s){d.rect(x,y+4,18,18,enabled?0xff6cbfcb:0xff36515f);if(enabled){d.line(x+4,y+12,x+8,y+16,0xff102832,2.4);d.line(x+8,y+16,x+15,y+8,0xff102832,2.4);}d.text(s,x+28,y-2,18);}
 static void slider(FullDraw &d,int x,int y,double q){q=std::max(0.,std::min(1.,q));d.rect(x,y,180,4,0xff36515f);d.rect(x,y,180*q,4,0xff82dce5);d.rect(x+180*q-3,y-4,7,12,0xffc3f5f5);}
 template<class V>void aoi_hud(FullDraw &d,const V &v,const std::string &mouse){
  d.rect(0,0,1280,54,0xff14242f);d.text("桌面PCB多模态检测系统",18,10,26);d.text("焊接缺陷",350,17,17);
  d.rect(1112,12,152,32,0xff264856);d.text(v.hud?"隐藏面板":"显示面板",1130,14,19);
  if(v.hud){
   d.rect(0,54,FULL_LEFT,666,0xff12212c);d.rect(1048,54,232,666,0xff12212c);d.rect(FULL_LEFT,554,FULL_WIDTH,166,0xff101e29);
   sidebar(d,v);
   d.text("检测结果",1062,64,21);button(d,1060,100,204,32,v.aoi_variant?"原色 RGB":"灰度");
   button(d,1060,144,96,32,"上一项");button(d,1164,144,100,32,"下一项");button(d,1060,182,204,32,"复位视图");
   if(aoi.status=="BUSY")d.text("正在检测 / 上次结果",1064,220,15);
   else if(aoi.status=="FAILED")d.text("检测失败 / 上次结果",1064,220,15);
   else if(aoi.status=="OFFLINE")d.text("数据不可用",1064,220,15);
   else if(!aoi.available)d.text("等待照片",1064,220,15);
   else d.text("候选 "+std::to_string(aoi.regions.size())+" 项",1064,220,15);
   for(size_t i=0;i<aoi.regions.size()&&i<6;i++){int y=244+int(i)*32;if(int(i)==v.aoi_selected)d.rect(1060,y,204,30,0xff2a5a65);d.text(std::to_string(i+1)+" "+aoi.regions[i].kind,1064,y+1,14);}
   d.text("检测结果",FULL_LEFT+20,570,19);
   if(aoi.available&&!aoi.regions.empty()){int index=std::max(0,std::min(int(aoi.regions.size())-1,v.aoi_selected));const auto &r=aoi.regions[index];
    d.text(std::to_string(index+1)+" / "+std::to_string(aoi.regions.size())+"  "+r.kind+"  "+r.component,FULL_LEFT+20,608,20);d.text(std::string(r.board_valid?"板面位置 ":"原图位置 ")+full_number(r.board_valid?r.bx:r.x,0)+", "+full_number(r.board_valid?r.by:r.y,0)+" px",FULL_LEFT+20,643,16);
   }else if(aoi.available)d.text(aoi.state=="annotation_required"?"需要元件标注":aoi.state=="insufficient_coverage"?"图片质量不足":"未发现明显缺陷",FULL_LEFT+20,613,18);
   else d.text("等待照片",FULL_LEFT+20,613,18);
  }
  board_control(d,v);
 if(v.cursor_visible)d.image(v.cursor_x,v.cursor_y,32,48,1984,1488,32,48,65530);
 }
 template<class V>static std::string command_key(const V&v,const std::string&mouse,bool overlay){
  std::ostringstream k;k<<std::setprecision(17)<<v.board_menu<<','<<v.raw_zoom[0]<<','<<v.raw_zoom[1]<<','<<v.raw_x[0]<<','<<v.raw_y[0]<<','<<v.raw_x[1]<<','<<v.raw_y[1]<<','<<v.temperature_valid<<','<<v.temperature_x<<','<<v.temperature_y<<','<<v.scan_config_revision<<','<<v.data_revision<<','<<v.mode<<','<<v.raw_board<<','<<v.base<<','<<v.heat<<','<<v.emi<<','<<v.emi_alpha<<','<<v.relief<<','<<v.band<<','<<v.scenario<<','<<v.point<<','<<v.slice<<','<<v.time<<','<<v.points<<','<<v.components<<','<<v.hud<<','<<v.autorotate<<','<<mouse;
  if(v.mode==12)k<<','<<v.aoi_run<<','<<v.aoi_status<<','<<v.aoi_selected<<','<<v.aoi_variant<<','<<v.aoi_zoom<<','<<v.aoi_pan_x<<','<<v.aoi_pan_y;
  if(v.mode==16)k<<','<<v.demo_point<<','<<v.demo_command;
  if(!overlay)k<<','<<v.cursor_visible<<','<<v.cursor_x<<','<<v.cursor_y;return k.str();
 }
 template<class V>std::vector<gfx_command> build(const V &v,const std::string &mouse,double render_ms,bool include_hud=true){
  if(v.mode==16){demo.refresh(demo_path);FullDraw d(glyphs);demo.draw(d,v);sidebar(d,v);board_control(d,v);d.commands.push_back(gfx_command{});return d.commands;}
  unsigned needed=(v.mode==0||v.mode==1)?27:(v.mode==3||v.mode==6||v.mode==15)?4:v.mode==13?1:v.mode==14?2:0;
  if((available_modalities&needed)!=needed||((v.mode==3||v.mode==6)&&(xs.size()<2||ys.size()<2))||(v.mode==12&&!aoi.available)||v.mode==8||v.mode==9){
   FullDraw d(glyphs);d.rect(0,0,1280,720,0xff0d1722);d.rect(0,0,1280,54,0xff14242f);
   d.text("桌面PCB多模态检测系统",18,10,26);d.text("WAITING FOR ZYNQ RAW / REFERENCE",300,290,24);
   d.text("INPUT OR CALIBRATION MISSING",300,330,20);
   if(include_hud){sidebar(d,v);board_control(d,v);}d.commands.push_back(gfx_command{});return d.commands;
  }
  if(v.mode>=13){FullDraw d(glyphs);raw_view(d,v);d.commands.push_back(gfx_command{});return d.commands;}
  if(v.mode==12){FullDraw d(glyphs);aoi.picture(d,v);if(include_hud)aoi_hud(d,v,mouse);d.commands.push_back(gfx_command{});
   if(d.commands.size()>16385)throw std::runtime_error("AOI scene exceeds command capacity");return d.commands;}
  if(available_modalities&4)refresh(v);FullDraw d(glyphs);bool chart=v.mode==8||v.mode==9;
  if(!chart){
   if(dcdc_fixture)for(int i=-90;i<=90;i+=5){d.world_line({{double(i),-2.2,-90}},{{double(i),-2.2,90}},0xff1a303d,.045);d.world_line({{-90,-2.2,double(i)}},{{90,-2.2,double(i)}},0xff1a303d,.045);}
   bool planar=v.mode==1||v.mode==4||v.mode==5||v.mode==7||v.mode==10||v.mode==11||!v.components;
   const auto &base_commands=planar?flat:model;if(v.mode!=3&&v.mode!=6)d.commands.insert(d.commands.end(),base_commands.begin(),base_commands.end());
   if(v.mode==10||v.mode==11)for(auto &c:d.commands)c.opcode_flags&=~uint32_t(GFX_THERMAL);
   if(v.emi&&v.mode!=0&&v.mode!=1&&v.mode!=10&&v.mode!=11){
    if(v.mode==0||v.mode==2)for(size_t i=0;i<points.size();i++){double q=(full_db(powers[i])-lo)/(hi-lo);if(q<.2)continue;d.sprite(points[i].wx,heights[i]+.15,points[i].wz,7+q*18,full_color(q,int(v.emi_alpha*q)),1000+i);}
    if(v.mode==1||v.mode==4)field(d,v,false,true,false);
    if(v.mode==3)field(d,v,true,true,false);
    if(v.mode==5)field(d,v,false,false,false);
    if(v.mode==7)field(d,v,false,false,true);
    if(v.mode==6)cube(d,v);
   }
   if((available_modalities&4)&&v.mode!=0&&v.mode!=1&&v.mode!=10&&v.mode!=11)for(size_t i=0;i<points.size();i++)if(v.points||i==size_t(v.point)){
    double y=planar?.28:heights[i]+.2;d.sprite(points[i].wx,y,points[i].wz,i==size_t(v.point)?12:3.2,i==size_t(v.point)?0xffffed9b:0x88d5e9ec,1000+i);
   }
  }else signal_chart(d,v);
  if(include_hud)hud(d,v,mouse,render_ms);
  else {if(v.mode==6)d.text("频率 / MHz",v.hud?FULL_LEFT+30:24,70,19);if(v.mode==7)d.text(background_fixture?"模拟差异 / dB":"扫描前后差异 / dB",v.hud?FULL_LEFT+30:24,70,19);}
  d.commands.push_back(gfx_command{});
  size_t expanded=0;for(const auto &c:d.commands)expanded+=(c.opcode_flags&255)==GFX_SPRITE?2:((c.opcode_flags&255)!=0);
  if(expanded>16384||d.commands.size()>16385)throw std::runtime_error("full scene exceeds explicit triangle capacity");return d.commands;
 }
 // Hit testing uses the displayed pose and original model coordinates.
 template<class V>bool anchor(const V&v,int x,int y,double hit[3],unsigned *object=nullptr)const{
  if(v.mode==3||v.mode==6||((v.mode==0||v.mode==1)&&(available_modalities&27)!=27))return false;
  if(v.hud&&(x<FULL_LEFT||x>=FULL_RIGHT||y<54||y>=554))return false;
  int32_t m[12];gfx_view_matrix(v.pose,m);if(v.hud){m[3]-=full_q(FULL_PROJECTION_X);m[7]-=full_q(60);}double best=1e99;bool found=false;
  const auto &picking_geometry=(v.mode==1||!v.components)?flat:model;
  for(const auto&c:picking_geometry){if((c.opcode_flags&255)!=GFX_TRIANGLE)continue;double px[3],py[3],pz[3];
   for(int j=0;j<3;j++){const auto&p=c.v[j];px[j]=(double(m[0])*p.x+double(m[1])*p.y+double(m[2])*p.z)/4294967296.+m[3]/65536.;py[j]=(double(m[4])*p.x+double(m[5])*p.y+double(m[6])*p.z)/4294967296.+m[7]/65536.;pz[j]=(double(m[8])*p.x+double(m[9])*p.y+double(m[10])*p.z)/4294967296.+m[11]/65536.;}
   double d=(py[1]-py[2])*(px[0]-px[2])+(px[2]-px[1])*(py[0]-py[2]);if(std::abs(d)<1e-8)continue;
   double a=((py[1]-py[2])*(x-px[2])+(px[2]-px[1])*(y-py[2]))/d,b=((py[2]-py[0])*(x-px[2])+(px[0]-px[2])*(y-py[2]))/d,t=1-a-b;
   if(a<0||b<0||t<0)continue;double z=a*pz[0]+b*pz[1]+t*pz[2];if(z>=best)continue;best=z;found=true;
   hit[0]=(a*c.v[0].x+b*c.v[1].x+t*c.v[2].x)/65536.;hit[1]=(a*c.v[0].y+b*c.v[1].y+t*c.v[2].y)/65536.;hit[2]=(a*c.v[0].z+b*c.v[1].z+t*c.v[2].z)/65536.;if(object)*object=c.object_id;
  }return found;
 }
 template<class V>bool focus(V&v,unsigned id)const{
  if(!id)return false;double lo[3]={1e9,1e9,1e9},hi[3]={-1e9,-1e9,-1e9};bool found=false;
  for(const auto&c:model)if(c.object_id==id&&(c.opcode_flags&255)==GFX_TRIANGLE)for(const auto&p:c.v){double q[3]={p.x/65536.,p.y/65536.,p.z/65536.};for(int j=0;j<3;j++){lo[j]=std::min(lo[j],q[j]);hi[j]=std::max(hi[j],q[j]);}found=true;}
  if(!found)return false;for(int j=0;j<3;j++)v.pose.target[j]=(lo[j]+hi[j])*.5;
  v.pose.zoom=std::max(.2,std::min(8.,40./std::max(1.,std::max(hi[0]-lo[0],hi[2]-lo[2]))));return true;
 }
 template<class V>int pick(const V &v,int x,int y)const{
  if(v.hud&&(x<FULL_LEFT||x>=FULL_RIGHT||y<54||y>=554))return -1;if(v.mode==8||v.mode==9||v.mode>=13)return -1;
  int32_t matrix[12];gfx_view_matrix(v.pose,matrix);if(v.hud){matrix[3]-=full_q(FULL_PROJECTION_X);matrix[7]-=full_q(60);}
  double best=28*28;int index=-1;bool planar=v.mode==1||v.mode==4||v.mode==5||v.mode==7||v.mode==10||v.mode==11||!v.components;
  for(size_t i=0;i<points.size();i++){double yy=planar?.28:heights[i]+.2;double px=(matrix[0]*points[i].wx+matrix[1]*yy+matrix[2]*points[i].wz+matrix[3])/65536.,py=(matrix[4]*points[i].wx+matrix[5]*yy+matrix[6]*points[i].wz+matrix[7])/65536.;double q=(px-x)*(px-x)+(py-y)*(py-y);if(q<best){best=q;index=i;}}
  return index;
 }
};
#endif
