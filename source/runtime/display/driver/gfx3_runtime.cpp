// Native ABI3 runtime. Geometry and textures are uploaded once; PL draws pixels.
#include "../include/gfx3_protocol.h"
#include "gfx3_view_matrix.h"
#include "../third_party/turbojpeg.h"
#include <sys/mman.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <fcntl.h>
#include <unistd.h>
#include <dlfcn.h>
#include <signal.h>
#include <linux/input.h>
#include <linux/hidraw.h>
#include <glob.h>
#include <atomic>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <memory>
#include <fstream>
#include <sstream>
#include <iostream>
#include <vector>
#include <deque>
#include <map>
#include <iomanip>
#include <stdexcept>
#include <system_error>
#include <cstring>
#include <cerrno>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <limits.h>
static std::atomic<bool> alive(true);
static uint64_t now_ns(){timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return uint64_t(t.tv_sec)*1000000000+t.tv_nsec;}
static void fail(const char *s){throw std::system_error(errno,std::generic_category(),s);}
static void stop(int){alive=false;}
// A displayed layer is owned by scanout until the next frame is adopted.
// GFX3_FREE returns EBUSY during that interval; retain the handle and retry
// after presentation instead of silently leaking the driver's allocation.
struct DeferredFree {
 struct Item{int fd;gfx3_bo bo;};
 std::mutex lock;Item pending[64];size_t count=0;uint64_t errors=0;
 void release(int fd,gfx3_bo bo){
  if(ioctl(fd,GFX3_FREE,&bo)==0)return;int e=errno;
  if(e==EBUSY){std::lock_guard<std::mutex>g(lock);if(count<64)pending[count++]={fd,bo};else errors++;}
  else if(e!=ENOENT&&e!=EBADF){std::lock_guard<std::mutex>g(lock);errors++;}
 }
 void drain(int fd){std::lock_guard<std::mutex>g(lock);
  for(size_t i=0;i<count;){if(pending[i].fd!=fd){i++;continue;}
   if(ioctl(fd,GFX3_FREE,&pending[i].bo)==0||errno==ENOENT){pending[i]=pending[--count];continue;}
   if(errno!=EBUSY)errors++;i++;
  }}
 void stats(size_t &n,uint64_t &e){std::lock_guard<std::mutex>g(lock);n=count;e=errors;}
};
static DeferredFree deferred_free;
static std::map<std::string,uint64_t> memory_info(){
 std::ifstream f("/proc/meminfo");std::map<std::string,uint64_t> r;std::string line,key,unit;uint64_t value;
 while(std::getline(f,line)){std::istringstream s(line);if(s>>key>>value){s>>unit;r[key.substr(0,key.size()-1)]=value*(unit=="kB"?1024:1);}}return r;
}
static bool read_number(const std::string &path,double &value){std::ifstream f(path);return bool(f>>value)&&std::isfinite(value);}
static double die_temperature_mC(){
 double value;if(read_number("/sys/class/thermal/thermal_zone0/temp",value))return value;
 for(int n=0;n<8;n++){std::string p="/sys/bus/iio/devices/iio:device"+std::to_string(n)+"/in_temp0_";double raw,offset,scale;
  if(read_number(p+"raw",raw)&&read_number(p+"offset",offset)&&read_number(p+"scale",scale))return (raw+offset)*scale;}
 return NAN;
}
// Live percentiles use a bounded window. The report recomputes ALL saved frames.
static double percentile(const std::vector<double> &values,double q){if(values.empty())return 0;
 std::vector<double> v(values.end()-std::min(size_t(256),values.size()),values.end());size_t n=std::min(v.size()-1,size_t(q*(v.size()-1)));
 std::nth_element(v.begin(),v.begin()+n,v.end());return v[n];}
struct Buffer{
 int fd;gfx3_bo u={};void *map=MAP_FAILED;std::atomic<int> jpeg_users{0};
 Buffer(int f,uint32_t kind,size_t bytes):fd(f){u.kind=kind;u.bytes=bytes;
  if(ioctl(fd,GFX3_ALLOC,&u))throw std::system_error(errno,std::generic_category(),
    "allocate BO kind="+std::to_string(kind)+" bytes="+std::to_string(bytes));
  map=mmap(nullptr,u.bytes,PROT_READ|PROT_WRITE,MAP_SHARED,fd,off_t(u.handle)*4096);
  if(map==MAP_FAILED){ioctl(fd,GFX3_FREE,&u);fail("map BO");}}
 ~Buffer(){if(map!=MAP_FAILED)munmap(map,u.bytes);deferred_free.release(fd,u);}
};
using BO=std::shared_ptr<Buffer>;
struct AssetCache{
 size_t limit=128UL<<20,bytes=0;std::map<std::string,std::shared_ptr<std::vector<unsigned char>>> entries;
 std::deque<std::string> lru;
 void trim(size_t target){while(bytes>target&&!lru.empty()){auto name=lru.front();lru.pop_front();auto it=entries.find(name);if(it!=entries.end()){bytes-=it->second->size();entries.erase(it);}}}
 void rebalance(){auto m=memory_info();
  limit=m["MemAvailable"]>=(512UL<<20)&&m["LowFree"]>=(128UL<<20)?256UL<<20:128UL<<20;
  size_t target=limit;if(m["MemAvailable"]<(192UL<<20)||m["LowFree"]<(64UL<<20))target=0;trim(target);
 }
 std::shared_ptr<std::vector<unsigned char>> get(const std::string &path){
  auto it=entries.find(path);if(it!=entries.end()){lru.erase(std::remove(lru.begin(),lru.end(),path),lru.end());lru.push_back(path);return it->second;}
  std::ifstream f(path,std::ios::binary|std::ios::ate);if(!f)throw std::runtime_error("asset missing: "+path);
  size_t n=size_t(f.tellg());if(n>limit)throw std::runtime_error("asset exceeds reclaimable cache budget");
  while(bytes+n>limit&&!lru.empty()){auto old=lru.front();lru.pop_front();bytes-=entries[old]->size();entries.erase(old);}
  auto data=std::make_shared<std::vector<unsigned char>>(n);f.seekg(0);f.read(reinterpret_cast<char*>(data->data()),n);
  if(!f)throw std::runtime_error("incomplete asset: "+path);entries[path]=data;lru.push_back(path);bytes+=n;return data;
 }
};
#include "full_state.h"
#include "async_log.h"
struct View:FullState{GfxView pose;uint64_t sequence=1,received=now_ns();int heat=179,emi=1,native=0;View(){pose.zoom=.78;}};
#include "full_scene.h"
#include "full_reference.h"
#include "full_ai_frame.h"
#include "full_cursor.h"
static FullScene *full_scene=nullptr,*full_scenes[2]={nullptr,nullptr};
static FullScene *full_for(int board){if(!full_scenes[board?1:0])throw std::runtime_error("selected board has no scene");return full_scenes[board?1:0];}

#include "preview_copy.h"
struct ImageJob:PreviewCopy<Buffer>{
 gfx3_result frame={};uint32_t w=0,h=0,heat=0,emi=0;bool full=false;std::shared_ptr<std::vector<uint32_t>> ui;int cursor_x=0,cursor_y=0,cursor_visible=0;uint64_t cursor_revision=0;
 ImageJob(const BO &b,size_t bytes):PreviewCopy<Buffer>(b,bytes){}
};
struct Jpeg{
 std::mutex lock;std::condition_variable changed;std::shared_ptr<ImageJob> pending;
 std::shared_ptr<const std::vector<unsigned char>> bytes;std::string headers,meta="null",error;
 uint64_t serial=0,encoded=0;double last_ms=0;bool finish=false,paused=false,busy=false,unavailable=false;
 const uint64_t session=now_ns();AsyncLog timing;
 std::thread worker;
 Jpeg(const std::string &prefix):timing(prefix+"-jpeg.jsonl"){worker=std::thread([this]{run();});}
 void run(){
  void *lib=dlopen("libturbojpeg.so.0",RTLD_NOW|RTLD_LOCAL);
  if(!lib){std::lock_guard<std::mutex> g(lock);error="libturbojpeg unavailable";unavailable=true;pending.reset();return;}
  auto init=reinterpret_cast<decltype(&tjInitCompress)>(dlsym(lib,"tjInitCompress"));
  auto compress=reinterpret_cast<decltype(&tjCompress2)>(dlsym(lib,"tjCompress2"));
  auto release=reinterpret_cast<decltype(&tjFree)>(dlsym(lib,"tjFree"));
  auto destroy=reinterpret_cast<decltype(&tjDestroy)>(dlsym(lib,"tjDestroy"));
  if(!init||!compress||!release||!destroy){std::lock_guard<std::mutex> g(lock);error="TurboJPEG ABI incomplete";unavailable=true;pending.reset();dlclose(lib);return;}
  tjhandle compressor=init();
  if(!compressor){std::lock_guard<std::mutex> g(lock);error="TurboJPEG allocation failed";unavailable=true;pending.reset();dlclose(lib);return;}
  while(true){
   std::shared_ptr<ImageJob> job;
   {std::unique_lock<std::mutex> g(lock);changed.wait(g,[this]{return finish||pending;});if(finish)break;job.swap(pending);busy=true;}
   auto copy_start=now_ns();
   try{job->materialize();}catch(const std::exception &e){std::lock_guard<std::mutex> g(lock);busy=false;error=std::string("preview copy failed: ")+e.what();continue;}
   auto start=now_ns();double copy_ms=(start-copy_start)*1e-6;
   // The source pin is now released; composition/JPEG use only the private copy.
   if(job->ui){uint32_t *dst=reinterpret_cast<uint32_t*>(job->pixels.data());
    auto blend=[](uint32_t d,uint32_t s){unsigned a=s>>24;if(!a)return d;if(a==255)return s;uint32_t r=0xff000000;for(int c=0;c<3;c++)r|=std::min(255U,((s>>(8*c))&255)+((((d>>(8*c))&255)*(255-a)+127)/255))<<(8*c);return r;};
    for(unsigned y=0;y<job->h;y++)for(unsigned x=0;x<job->w;x++){
     unsigned sx=x*1280/job->w,sy=y*720/job->h;uint32_t color=blend(dst[y*job->w+x],(*job->ui)[sy*1280+sx]);
     if(job->cursor_visible){int dx=int(sx)-job->cursor_x,dy=int(sy)-job->cursor_y;
      if(dx>=0&&dx<32&&dy>=0&&dy<48)color=blend(color,full_cursor_pixels[dy*32+dx]);}
     dst[y*job->w+x]=color;
    }
   }
   unsigned char *jpeg=nullptr;unsigned long size=0;
   int rc=compress(compressor,job->pixels.data(),job->w,job->w*4,job->h,
    TJPF_BGRA,&jpeg,&size,job->full?TJSAMP_444:TJSAMP_420,job->full?94:84,TJFLAG_FASTDCT);
   uint64_t done=now_ns();std::shared_ptr<const std::vector<unsigned char>> packed;
   try{if(!rc)packed=std::make_shared<const std::vector<unsigned char>>(jpeg,jpeg+size);}catch(const std::exception &){rc=-1;}
   if(jpeg)release(jpeg);
   std::lock_guard<std::mutex> g(lock);busy=false;if(rc){error="JPEG encode/copy failed";continue;}
   bytes=std::move(packed);serial++;encoded++;last_ms=(done-start)*1e-6;
   timing<<"{\"frame\":"<<job->frame.sequence<<",\"input\":"<<job->frame.input_sequence<<",\"copy_start_ns\":"<<copy_start<<",\"copy_ms\":"<<copy_ms<<",\"encode_start_ns\":"<<start<<",\"encode_done_ns\":"<<done<<",\"render_done_ns\":"<<job->frame.render_done_ns<<",\"width\":"<<job->w<<",\"height\":"<<job->h<<",\"bytes\":"<<size<<"}\n";timing.flush();
   std::ostringstream s;s<<"{\"frame_id\":"<<job->frame.sequence<<",\"input_sequence\":"<<job->frame.input_sequence
    <<",\"source_generation\":"<<job->frame.source_generation<<",\"render_done_ns\":"<<job->frame.render_done_ns
    <<",\"encoded_ns\":"<<done<<",\"width\":"<<job->w<<",\"height\":"<<job->h<<",\"full\":"<<job->full
    <<",\"thermal_alpha\":"<<job->heat<<",\"emi_enabled\":"<<job->emi<<",\"cursor_revision\":"<<job->cursor_revision<<",\"copy_ms\":"<<copy_ms<<",\"jpeg_ms\":"<<last_ms<<"}";meta=s.str();
   std::ostringstream h;h<<"X-Session-Ns: "<<session<<"\r\nX-Frame-Id: "<<job->frame.sequence<<"\r\nX-Input-Sequence: "<<job->frame.input_sequence
    <<"\r\nX-Jpeg-Serial: "<<serial<<"\r\nX-Render-Done-Ns: "<<job->frame.render_done_ns
    <<"\r\nX-Encoded-Ns: "<<done<<"\r\nX-Width: "<<job->w<<"\r\nX-Height: "<<job->h<<"\r\n";headers=h.str();error.clear();
  }
  destroy(compressor);dlclose(lib);
 }
 void submit(std::shared_ptr<ImageJob> job){std::lock_guard<std::mutex> g(lock);if(paused||finish||unavailable)return;pending=job;changed.notify_one();}
 void pause(bool enable){std::lock_guard<std::mutex> g(lock);paused=enable;if(enable)pending.reset();}
 bool idle(){std::lock_guard<std::mutex> g(lock);return !busy&&!pending;}
 ~Jpeg(){{std::lock_guard<std::mutex> g(lock);finish=true;pending.reset();changed.notify_one();}worker.join();}
};
struct Shared{
 std::mutex lock;View target,displayed;bool have_displayed=false,cursor_overlay=false;std::string metrics="{}",render_error;bool quiet_request=false,quiet_active=false,benchmark=false;
 FullDrag drag;std::string mouse_device,mouse_backend;uint64_t mouse_events=0,browser_events=0;
};
static void full_input_locked(Shared &s,int kind,int x,int y,int button,double wheel=0){
 if(s.target.mode==16){std::ifstream f(full_for(s.target.raw_board)->demo_path);std::string magic;unsigned revision;int state,done,point,frames,total,live;double w,h,sx,sy,feed;if(f>>magic>>revision>>state>>done>>point>>frames>>total>>live>>w>>h>>sx>>sy>>feed&&magic=="PDPVIEW3"&&total>0&&total<=1024){s.target.demo_total=total;s.target.demo_active=state>=1&&state<=6;if(!s.target.scan_config_revision){s.target.scan_width=w;s.target.scan_height=h;s.target.scan_step_x=sx;s.target.scan_step_y=sy;s.target.scan_feed=feed;}}}
 auto &v=s.target;int dx=x-v.cursor_x,dy=y-v.cursor_y;v.cursor_x=std::max(0,std::min(1279,x));v.cursor_y=std::max(0,std::min(719,y));
 bool redraw=false,view_change=false;const auto &shown=s.have_displayed?s.displayed:v;
 if(kind==1){s.drag.start_x=x;s.drag.start_y=y;s.drag.total=0;
  s.drag.slider=button==0&&v.mode<12&&v.hud&&x>=1060&&x<1264?((y>=138&&y<160)?1:(y>=216&&y<240)?2:(y>=266&&y<286)?3:0):0;
  if(button==0){if(v.mode==13)v.raw_image=x>=610?1:0;else if(v.mode==14)v.raw_image=0;s.drag.left=!full_click(v,x,y,full_for(v.raw_board)->points.size(),full_for(v.raw_board)->aoi.regions.size());if(v.mode==15){int selected=full_for(v.raw_board)->raw_matrix_pick(v,x,y);if(selected>=0)v.point=selected;}redraw=!s.drag.left;}
  if(button==2||button==1)s.drag.right=!(v.hud&&(x<FULL_LEFT||x>=FULL_RIGHT||y<54||y>=554));
 }else if(kind==0){
  s.drag.total+=std::abs(dx)+std::abs(dy);
  if(s.drag.slider){full_click(v,std::max(1068,std::min(1248,x)),s.drag.start_y,full_for(v.raw_board)->points.size(),full_for(v.raw_board)->aoi.regions.size());redraw=true;}
  if((v.mode==13||v.mode==14)&&s.drag.left&&(dx||dy)){int i=v.raw_image;v.raw_x[i]=std::max(-.45,std::min(.45,v.raw_x[i]+dx/(v.mode==13?414.:512.)/v.raw_zoom[i]));v.raw_y[i]=std::max(-.45,std::min(.45,v.raw_y[i]+dy/(v.mode==13?320.:384.)/v.raw_zoom[i]));redraw=true;}
  else if(v.mode==12&&(s.drag.left||s.drag.right)&&(dx||dy)){v.aoi_pan_x=std::max(-1100.,std::min(1100.,v.aoi_pan_x+dx));v.aoi_pan_y=std::max(-800.,std::min(800.,v.aoi_pan_y+dy));redraw=true;}
  else if(s.drag.left&&(dx||dy)){if(v.mode==1)gfx_pan(v.pose,dx,dy);else{v.pose.yaw+=dx*.006;v.pose.polar=std::max(.05,std::min(3.09,v.pose.polar+dy*.006));}redraw=view_change=true;}
  else if(s.drag.right&&(dx||dy)){gfx_pan(v.pose,dx,dy);redraw=view_change=true;}
 }else if(kind==2){
  if(button==0&&s.drag.left&&s.drag.total<=5){if(v.mode==12){if(shown.mode==12&&shown.aoi_run==full_for(v.raw_board)->aoi.run){int p=full_for(v.raw_board)->aoi.pick(shown,x,y);if(p>=0){v.aoi_selected=p;redraw=true;}}}
   else{int p=full_for(v.raw_board)->pick(shown,x,y);if(p>=0){v.point=p;redraw=true;}double a[3];unsigned id=0;if(v.mode==14){full_for(v.raw_board)->temperature_image_pick(v,x,y);redraw=true;}else if(full_for(v.raw_board)->anchor(shown,x,y,a,&id)){v.selected_component=id;if(v.mode==0||v.mode==1)full_for(v.raw_board)->temperature_world_at(v,a[0],a[2]);redraw=true;}}}
  if(button==0){if(v.mode==13)v.raw_image=x>=610?1:0;else if(v.mode==14)v.raw_image=0;s.drag.left=false;s.drag.slider=0;}if(button==2||button==1)s.drag.right=false;
 }else if(kind==3&&wheel!=0&&v.mode!=15){
  if(v.mode==13||v.mode==14){int i=v.mode==13&&x>=610?1:0;v.raw_zoom[i]=std::max(1.,std::min(8.,v.raw_zoom[i]*std::exp(wheel*.12)));redraw=true;}
  else if(v.mode==12){full_for(v.raw_board)->aoi.zoom_at(v,x,y,wheel);redraw=true;}
  else if(v.hud&&v.mode==6&&x>=1048&&y>=342&&y<374){v.slice=std::max(.2,std::min(25.,v.slice+wheel*.25));redraw=true;}
  else{auto a=gfx_plane_anchor(shown.pose,x,y,shown.hud,FULL_PROJECTION_X);full_for(v.raw_board)->anchor(shown,x,y,a.data());gfx_zoom_anchor(v.pose,v.pose.zoom*std::exp(wheel*.12),x,y,v.hud,a.data(),FULL_PROJECTION_X);redraw=view_change=true;}
 }else if(kind==4){s.drag.left=s.drag.right=false;s.drag.slider=0;}
 if(dx||dy)v.cursor_revision++;
 if(view_change)v.view_revision++;else if(redraw){v.scene_revision++;v.menu_revision++;}
 // Older bitstreams retain the complete software cursor as a compatibility path.
 if(redraw||(!s.cursor_overlay&&(dx||dy))){v.sequence++;v.received=now_ns();}
}
#include "full_mouse.h"
#include "full_cursor_service.h"
static bool send_all(int fd,const void *p,size_t n){auto b=static_cast<const char*>(p);while(n){ssize_t k=send(fd,b,n,MSG_NOSIGNAL);if(k<=0)return false;b+=k;n-=k;}return true;}
static std::string full_app_json(const View &v){std::ostringstream s;s<<std::setprecision(12)
 <<"{\"sequence\":"<<v.sequence<<",\"mode\":"<<v.mode<<",\"base\":"<<v.base<<",\"heat\":"<<v.heat<<",\"emi\":"<<v.emi
 <<",\"demo_point\":"<<v.demo_point<<",\"demo_command\":"<<v.demo_command<<",\"demo_request\":"<<v.demo_request
 <<",\"scan_config_revision\":"<<v.scan_config_revision<<",\"scan_config\":{\"width\":"<<v.scan_width<<",\"height\":"<<v.scan_height<<",\"step_x\":"<<v.scan_step_x<<",\"step_y\":"<<v.scan_step_y<<",\"feed\":"<<v.scan_feed<<"}"
 <<",\"temperature_valid\":"<<(v.temperature_valid?"true":"false")<<",\"temperature_c\":"<<(v.temperature_valid?std::to_string(v.temperature_c):"null")<<",\"temperature_pl_c\":"<<(v.temperature_valid?std::to_string(v.temperature_pl_c):"null")
 <<",\"raw_thermal_xy\":["<<v.temperature_x<<","<<v.temperature_y<<"],\"raw_kelvin16\":"<<v.temperature_kelvin16<<",\"temperature_board_xy\":["<<v.temperature_board_x<<","<<v.temperature_board_y<<"],\"data_revision\":"<<v.data_revision<<",\"capture_id\":\""<<v.data_capture<<"\""
 <<",\"emi_alpha\":"<<v.emi_alpha<<",\"relief\":"<<v.relief<<",\"band\":"<<v.band<<",\"scenario\":"<<v.scenario<<",\"point\":"<<v.point
 <<",\"points\":"<<v.points<<",\"components\":"<<v.components<<",\"hud\":"<<v.hud<<",\"autorotate\":"<<v.autorotate
 <<",\"cursor_visible\":"<<v.cursor_visible<<",\"cursor_x\":"<<v.cursor_x<<",\"cursor_y\":"<<v.cursor_y
 <<",\"cursor_revision\":"<<v.cursor_revision<<",\"view_revision\":"<<v.view_revision<<",\"scene_revision\":"<<v.scene_revision<<",\"menu_revision\":"<<v.menu_revision<<",\"selected_component\":"<<v.selected_component
 <<",\"aoi_selected\":"<<v.aoi_selected<<",\"aoi_variant\":"<<v.aoi_variant<<",\"aoi_zoom\":"<<v.aoi_zoom<<",\"aoi_pan_x\":"<<v.aoi_pan_x<<",\"aoi_pan_y\":"<<v.aoi_pan_y<<",\"aoi_run\":\""<<v.aoi_run<<"\",\"aoi_status\":\""<<v.aoi_status<<"\""
 <<",\"raw_zoom_0\":"<<v.raw_zoom[0]<<",\"raw_zoom_1\":"<<v.raw_zoom[1]<<",\"raw_x_0\":"<<v.raw_x[0]<<",\"raw_y_0\":"<<v.raw_y[0]<<",\"raw_x_1\":"<<v.raw_x[1]<<",\"raw_y_1\":"<<v.raw_y[1]<<",\"board_menu\":"<<v.board_menu<<",\"raw_board\":"<<v.raw_board<<",\"slice\":"<<v.slice<<",\"time\":"<<v.time<<",\"native\":"<<v.native
 <<",\"yaw\":"<<v.pose.yaw<<",\"polar\":"<<v.pose.polar<<",\"zoom\":"<<v.pose.zoom
 <<",\"x\":"<<v.pose.target[0]<<",\"y\":"<<v.pose.target[1]<<",\"z\":"<<v.pose.target[2]<<"}";return s.str();}
#include "bounded_workers.h"
static void http_client(Shared &shared,Jpeg &jpeg,int c){
 struct CloseClient{int fd;~CloseClient(){close(fd);}} close_client{c};int yes=1;
  // Header and body use separate writes. Disable Nagle so the final small
  // packet cannot wait for a delayed ACK on every status/JPEG response.
  if(setsockopt(c,IPPROTO_TCP,TCP_NODELAY,&yes,sizeof(yes))){return;}
  timeval timeout={1,0};setsockopt(c,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout));setsockopt(c,SOL_SOCKET,SO_SNDTIMEO,&timeout,sizeof(timeout));
  std::string request;char chunk[2048];size_t split=std::string::npos,length=0;
  while(request.size()<12288){ssize_t n=recv(c,chunk,sizeof(chunk),0);if(n<=0)break;request.append(chunk,n);split=request.find("\r\n\r\n");
   if(split!=std::string::npos){auto p=request.find("Content-Length:");if(p!=std::string::npos)length=strtoul(request.c_str()+p+15,nullptr,10);
    if(length>4096)break;if(request.size()>=split+4+length)break;}}
  std::string body,mime="application/json",extra;int status=200;
  if(request.compare(0,11,"GET /status")==0){
   std::string m,im,err,app,device,backend,render_error;uint64_t serial,mouse_events,browser_events;
   {std::lock_guard<std::mutex> g(shared.lock);m=shared.metrics;app=full_app_json(shared.target);device=shared.mouse_device;backend=shared.mouse_backend;render_error=shared.render_error;mouse_events=shared.mouse_events;browser_events=shared.browser_events;}
   {std::lock_guard<std::mutex> g(jpeg.lock);im=jpeg.meta;serial=jpeg.serial;err=jpeg.error;}
   std::ostringstream s;s<<"{\"session_ns\":"<<jpeg.session<<",\"heartbeat_ns\":"<<now_ns()<<",\"metrics\":"<<m<<",\"image\":"<<im
    <<",\"jpeg_serial\":"<<serial<<",\"error\":\""<<err<<"\",\"render_error\":\""<<render_error<<"\",\"app\":"<<app<<",\"mouse\":{\"device\":\""<<device<<"\",\"backend\":\""<<backend<<"\",\"events\":"<<mouse_events<<"},\"browser_events\":"<<browser_events<<"}";body=s.str();
  }else if(request.compare(0,16,"GET /temperature")==0){
   double x,y;bool raw=request.compare(0,20,"GET /temperature/raw")==0;
   int parsed=sscanf(request.c_str(),raw?"GET /temperature/raw?x=%lf&y=%lf":"GET /temperature?x=%lf&y=%lf",&x,&y);
   if(parsed!=2||!std::isfinite(x)||!std::isfinite(y)||std::abs(x)>100000||std::abs(y)>100000){status=400;body="{\"error\":\"temperature coordinates required\"}";}
   else{std::lock_guard<std::mutex>g(shared.lock);auto &v=shared.target;if(raw)full_for(v.raw_board)->temperature_raw_at(v,int(std::lround(x)),int(std::lround(y)));else full_for(v.raw_board)->temperature_board_at(v,x,y);v.sequence++;v.scene_revision++;body=full_app_json(v);if(!v.temperature_valid)status=422;}
  }else if(request.compare(0,13,"GET /spectrum")==0){
   std::lock_guard<std::mutex> g(shared.lock);View v=shared.target;
   if(!(full_for(v.raw_board)->available_modalities&4)){status=503;body="{\"state\":\"waiting for Zynq ADC\"}";}else{
   std::ostringstream s;s<<std::setprecision(8)<<"{\"synthetic\":false"<<",\"point\":"<<v.point<<",\"scenario\":"<<v.scenario<<",\"input_sequence\":"<<v.sequence
    <<",\"bin_count\":"<<full_for(v.raw_board)->meta[4]<<",\"df_hz\":"<<full_for(v.raw_board)->df<<",\"frequency_min_hz\":0,\"frequency_max_hz\":"<<full_for(v.raw_board)->frequency_max*1e6<<",\"temperature_c\":";
   double temperature=full_for(v.raw_board)->points[v.point].temp;if(std::isfinite(temperature))s<<temperature;else s<<"null";
   s<<",\"psd_linear\":[";for(int k=0;k<int(full_for(v.raw_board)->meta[4]);k++){if(k)s<<',';s<<full_for(v.raw_board)->base(v.point,k,v.scenario);}s<<"]}";body=s.str();}
  }else if(request.compare(0,9,"POST /app")==0&&split!=std::string::npos&&request.size()>=split+4+length){
   std::istringstream in(request.substr(split+4,length));std::vector<std::pair<std::string,double>> actions;std::string key;double value;
   bool complete=true;while(in>>key){if(!(in>>value)){complete=false;break;}actions.push_back({key,value});if(actions.size()>32)break;}bool good=complete&&in.eof()&&!actions.empty()&&actions.size()<=32;
   {std::lock_guard<std::mutex>g(shared.lock);View next=shared.target;for(auto &a:actions){if(a.first=="focus")good=good&&full_for(next.raw_board)->focus(next,next.selected_component);else if(!full_action(next,a.first,a.second,full_for(next.raw_board)->points.size(),true))good=false;}good=good&&full_scan_grid_valid(next);
    if(good&&!shared.benchmark){if(next.cursor_visible!=shared.target.cursor_visible)next.cursor_revision++;next.view_revision++;next.scene_revision++;next.menu_revision++;next.sequence=shared.target.sequence+1;next.received=now_ns();shared.target=next;shared.browser_events++;body=full_app_json(next);}else{status=400;body="{\"error\":\"invalid application action\"}";}}
  }else if(request.compare(0,13,"POST /pointer")==0&&split!=std::string::npos&&request.size()>=split+4+length){
   int kind,x,y,button;double wheel;std::string extra_input;std::istringstream in(request.substr(split+4,length));in>>kind>>x>>y>>button>>wheel;
   if(!in||kind<0||kind>4||x<0||x>1279||y<0||y>719||button<0||button>2||!std::isfinite(wheel)||std::abs(wheel)>20||(in>>extra_input)){status=400;body="{\"error\":\"invalid pointer\"}";}
   else {std::lock_guard<std::mutex>g(shared.lock);full_input_locked(shared,kind,x,y,button,wheel);shared.browser_events++;body=full_app_json(shared.target);}
  }else if(request.compare(0,10,"GET /frame")==0){
   std::shared_ptr<const std::vector<unsigned char>> encoded_image;
   {std::lock_guard<std::mutex> g(jpeg.lock);mime="image/jpeg";extra=jpeg.headers;encoded_image=jpeg.bytes;}
   if(!encoded_image){status=503;body="JPEG pending";}else body.assign(reinterpret_cast<const char*>(encoded_image->data()),encoded_image->size());
  }else if(request.compare(0,10,"POST /view")==0&&split!=std::string::npos&&request.size()>=split+4+length){
   View v;std::istringstream input(request.substr(split+4,length));
   input>>v.sequence>>v.pose.yaw>>v.pose.polar>>v.pose.zoom>>v.pose.target[0]>>v.pose.target[1]>>v.pose.target[2]>>v.heat>>v.emi>>v.native;
   if(!input||!std::isfinite(v.pose.yaw)||!std::isfinite(v.pose.polar)||!std::isfinite(v.pose.zoom)||
     v.pose.polar<.05||v.pose.polar>3.09||v.pose.zoom<.2||v.pose.zoom>8.0||v.heat<0||v.heat>255||v.emi<0||v.emi>1||v.native<0||v.native>1||
     !std::isfinite(v.pose.target[0])||!std::isfinite(v.pose.target[1])||!std::isfinite(v.pose.target[2])||std::abs(v.pose.target[0])>100||std::abs(v.pose.target[1])>100||std::abs(v.pose.target[2])>100)status=400;
   else{std::lock_guard<std::mutex> g(shared.lock);if(shared.benchmark||v.sequence<=shared.target.sequence)status=409;else{v.received=now_ns();shared.target=v;}}
   body=status==200?"{\"accepted\":true}":"{\"error\":\"invalid or old view\"}";
  }else if(request.compare(0,11,"POST /quiet")==0&&split!=std::string::npos){
   auto b=request.substr(split+4,length);if(b!="0"&&b!="1"){status=400;body="{}";}
   else{std::lock_guard<std::mutex> g(shared.lock);if(shared.benchmark){status=409;body="{\"error\":\"benchmark running\"}";}else{shared.quiet_request=b=="1";body="{\"requested\":true}";}}
  }else{status=404;body="{\"error\":\"unknown endpoint\"}";}
  std::ostringstream header;header<<"HTTP/1.1 "<<status<<" Response\r\nConnection: close\r\nCache-Control: no-store\r\nContent-Type: "<<mime<<"\r\nContent-Length: "<<body.size()<<"\r\n"<<extra<<"\r\n";
  auto h=header.str();if(send_all(c,h.data(),h.size()))send_all(c,body.data(),body.size());
}
static void http_server(Shared &shared,Jpeg &jpeg,int port){
 int fd=socket(AF_INET,SOCK_STREAM,0);if(fd<0){alive=false;return;}
 int yes=1;setsockopt(fd,SOL_SOCKET,SO_REUSEADDR,&yes,sizeof(yes));
 sockaddr_in addr={};addr.sin_family=AF_INET;addr.sin_port=htons(port);addr.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
 if(bind(fd,reinterpret_cast<sockaddr*>(&addr),sizeof(addr))||listen(fd,8)){close(fd);alive=false;return;}
 BoundedWorkers requests(4,8);
 while(alive){
  pollfd wait={fd,POLLIN,0};if(poll(&wait,1,200)<=0)continue;
  int c=accept(fd,nullptr,nullptr);if(c<0)continue;
  if(!requests.submit([&shared,&jpeg,c]{http_client(shared,jpeg,c);}))close(c);
 }
 close(fd);
}
struct Flight{gfx3_job job={};gfx3_result result={};View view;uint64_t ordinal=0;int frame_index=0,slot=0;bool recorded=false,rejected=false;BO command_buffer,layer;std::shared_ptr<std::vector<uint32_t>> ui;};
struct ServerGuard{std::thread &t;~ServerGuard(){alive=false;if(t.joinable())t.join();}};
static double recent_rate(const std::deque<uint64_t> &events,uint64_t now,uint64_t start){
 return now>start?events.size()*1e9/std::min(uint64_t(5000000000ULL),now-start):0;
}
static std::string make_metrics(const gfx3_caps &caps,bool quiet_active,bool benchmark_running,const View &v,uint64_t frame,uint64_t count,uint64_t adopted,
 uint64_t start,uint64_t last,const std::vector<double> &ms,const std::vector<double> &latency,const gfx3_result &r,size_t cache,size_t cache_limit,bool preview,
 double render_rate,double present_rate){
 std::ostringstream s;s<<std::setprecision(9)<<"{\"abi\":3,\"source_tag\":"<<caps.reserved[0]<<",\"clock_hz\":"<<caps.clock_hz
  <<",\"viewport\":[1280,720],\"frame_id\":"<<frame<<",\"measured_frames\":"<<count<<",\"adopted_frames\":"<<adopted
  <<",\"render_new_fps\":"<<render_rate<<",\"present_new_fps\":"<<present_rate
  <<",\"session_render_fps\":"<<(last>start?count*1e9/(last-start):0)
  <<",\"render_p95_ms\":"<<percentile(ms,.95)<<",\"input_to_completion_p95_ms\":"<<percentile(latency,.95)
  <<",\"last_render_ms\":"<<(r.counters[GFX3_TOTAL]*1e3/caps.clock_hz)<<",\"allocated_bytes\":"<<caps.allocated_bytes
  <<",\"kernel_mapped_bytes\":"<<caps.kernel_mapped_bytes<<",\"asset_cache_bytes\":"<<cache<<",\"asset_cache_limit\":"<<cache_limit
  <<",\"quiet_active\":"<<quiet_active<<",\"preview_enabled\":"<<preview<<",\"input_sequence\":"<<v.sequence
  <<",\"benchmark_running\":"<<benchmark_running
  <<",\"yaw\":"<<v.pose.yaw<<",\"polar\":"<<v.pose.polar<<",\"zoom\":"<<v.pose.zoom<<",\"thermal_alpha\":"<<v.heat<<",\"emi_enabled\":"<<v.emi
  <<",\"x\":"<<v.pose.target[0]<<",\"y\":"<<v.pose.target[1]<<",\"z\":"<<v.pose.target[2]
  <<",\"full_version\":1,\"frame_app\":"<<full_app_json(v)
  <<",\"physical_hdmi_observed\":false,\"physical_usb_mouse_tested\":false,\"data_source\":\""<<(v.raw_board?"source-verified raw recomputation; separate acquisition batches; prior geometry":"STM32 inputs unavailable; waiting state")<<"\",\"counters\":[";
 for(int k=0;k<GFX3_COUNTER_COUNT;k++){if(k)s<<',';s<<r.counters[k];}s<<"]}";return s.str();
}
static int full_self_test(const std::string &root){
 FullScene scene(root);full_scene=&scene;View v;size_t maximum=0;
 for(int mode:{0,1,3,6,12,13,14,15}){
  if(!full_action(v,"mode",mode,scene.points.size()))throw std::runtime_error("mode action");
  for(int base=0;base<3;base++){v.base=base;auto commands=scene.build(v,"self-test",50);int32_t matrix[12];gfx_view_matrix(v.pose,matrix);matrix[3]-=full_q(FULL_PROJECTION_X);matrix[7]-=full_q(60);
   if(!gfx_pose_fits(commands.data(),commands.size(),matrix))throw std::runtime_error("default scene outside fixed point bounds");maximum=std::max(maximum,commands.size());
  }
 }
 v.mode=0;v.hud=1;if(!full_click(v,30,100,187)||v.mode!=0)throw std::runtime_error("GUI mode hit");
 full_click(v,1120,20,187);if(v.hud)throw std::runtime_error("hide panel");full_click(v,1120,20,187);if(!v.hud)throw std::runtime_error("show panel");
  if(full_action(v,"point",187,187)||full_action(v,"relief",0,187)||full_action(v,"mode",17,187))throw std::runtime_error("range check");
 unsigned char descriptor[]={0x05,0x01,0x09,0x02,0xa1,0x01,0x09,0x01,0xa1,0x00,0x05,0x09,0x19,0x01,0x29,0x03,0x15,0x00,0x25,0x01,0x95,0x03,0x75,0x01,0x81,0x02,0x95,0x01,0x75,0x05,0x81,0x01,0x05,0x01,0x09,0x30,0x09,0x31,0x09,0x38,0x15,0x81,0x25,0x7f,0x75,0x08,0x95,0x03,0x81,0x06,0xc0,0xc0};
 FullHid h;if(!h.parse(descriptor,sizeof(descriptor)))throw std::runtime_error("HID descriptor");int dx,dy,w,b;bool has;unsigned char report[]={1,5,253,1};
 if(!h.decode(report,sizeof(report),dx,dy,w,b,has)||dx!=5||dy!=-3||w!=1||b!=1||!has)throw std::runtime_error("HID report");
 std::cout<<"{\"self_test\":\"passed\",\"modes\":8,\"bases\":3,\"point_count\":"<<scene.points.size()<<",\"native_bins\":"<<scene.meta[4]<<",\"max_command_count\":"<<maximum<<",\"hid_decode\":true,\"gui_range_checks\":true}"<<std::endl;return 0;
}
static int full_aoi_self_test(const std::string &root){FullAoi aoi;if(!aoi.refresh(root)||!aoi.available||aoi.status!="READY")throw std::runtime_error("AOI snapshot unavailable or incomplete");
 std::cout<<"{\"aoi_snapshot\":\"passed\",\"run_id\":\""<<aoi.run<<"\",\"regions\":"<<aoi.regions.size()<<",\"board_width\":"<<aoi.width<<",\"board_height\":"<<aoi.height<<"}"<<std::endl;return 0;}
int main(int argc,char **argv){
 signal(SIGINT,stop);signal(SIGTERM,stop);signal(SIGPIPE,SIG_IGN);
 try{
  if(argc==3&&std::string(argv[1])=="--self-test")return full_self_test(argv[2]);
  if(argc==3&&std::string(argv[1])=="--aoi-self-test")return full_aoi_self_test(argv[2]);
  if(argc==2&&std::string(argv[1])=="--probe"){int f=open("/dev/pcb-gfx3",O_RDWR|O_CLOEXEC);if(f<0)fail("open graphics probe");gfx3_caps c={};if(ioctl(f,GFX3_CAPS,&c))fail("caps probe");std::cout<<"{\"abi\":"<<c.abi<<",\"source_tag\":"<<c.reserved[0]<<",\"faulted\":"<<c.faulted<<",\"allocated_bytes\":"<<c.allocated_bytes<<",\"last_sequence\":"<<c.reserved[1]<<"}"<<std::endl;close(f);return c.faulted?1:0;}
  if(argc<2)throw std::runtime_error("usage: gfx3_runtime ASSET_DIR --tag TAG [--benchmark N --warmup 60 --present 1 --preview 1 --port 8686 --log PREFIX]");
  std::string root=argv[1],prefix=root+"/run",mouse="auto",aoi_root=root+"/aoi-display",ai_model,demo_control;unsigned tag=0;bool tag_set=false;int start_board=1,benchmark=0,warmup=60,present=1,preview=1,port=8686,seconds=0,release_assets=0,single_plane=1;
  for(int a=2;a+1<argc;a+=2){std::string k=argv[a];if(k=="--demo-control")demo_control=argv[a+1];else if(k=="--single-plane")single_plane=atoi(argv[a+1]);else if(k=="--ai-model")ai_model=argv[a+1];else if(k=="--tag"){tag=strtoul(argv[a+1],nullptr,0);tag_set=true;}else if(k=="--board")start_board=atoi(argv[a+1]);else if(k=="--benchmark")benchmark=atoi(argv[a+1]);else if(k=="--warmup")warmup=atoi(argv[a+1]);else if(k=="--present")present=atoi(argv[a+1]);else if(k=="--preview")preview=atoi(argv[a+1]);else if(k=="--port")port=atoi(argv[a+1]);else if(k=="--seconds")seconds=atoi(argv[a+1]);else if(k=="--log")prefix=argv[a+1];else if(k=="--mouse")mouse=argv[a+1];else if(k=="--aoi"){if(std::string(argv[a+1])!=root+"/aoi-display")throw std::runtime_error("external AOI directory rejected; use fresh source-bound output");aoi_root=argv[a+1];}else if(k=="--release-assets")release_assets=atoi(argv[a+1]);else throw std::runtime_error("unknown option");}
  if(single_plane!=0&&single_plane!=1)throw std::runtime_error("invalid single plane option");
  if(release_assets!=0&&release_assets!=1)throw std::runtime_error("invalid asset release option");
  if(release_assets&&root!="/tmp/pcb-hdmi-aoi-v4i/assets"&&root!="/dev/pcb-fusion/pcb-hdmi-aoi-v4i/assets")throw std::runtime_error("asset release limited to a dedicated temporary directory");
  if(release_assets){char resolved[PATH_MAX];if(!realpath(root.c_str(),resolved)||root!=resolved)throw std::runtime_error("temporary asset directory must not be a symlink");}
  if(!tag_set||benchmark<0||benchmark>100000||warmup<0||port<1024||port>65535)throw std::runtime_error("invalid options");
  int fd=open("/dev/pcb-gfx3",O_RDWR|O_CLOEXEC);if(fd<0)fail("open graphics");
  gfx3_caps caps={};if(ioctl(fd,GFX3_CAPS,&caps)||caps.abi!=3||caps.build_id!=GFX3_BUILD_ID||caps.reserved[0]!=tag)throw std::runtime_error("driver, bitstream and runtime identity mismatch");
  if(caps.faulted||caps.reserved[1]>0x0fffff00U)throw std::runtime_error("renderer needs a coordinated reset");
  gfx3_quiet resume={0,0,0};if(ioctl(fd,GFX3_QUIET,&resume))fail("resume previous quiet session");
  bool tiled=bool(std::ifstream(root+"/texture-8x4.flag"));if(tiled!=bool(caps.features&256))throw std::runtime_error("texture storage layout does not match bitstream capability");
  AssetCache cache;FullScene primary_scene(root);full_scene=&primary_scene;full_scenes[0]=&primary_scene;
  std::unique_ptr<FullScene> power_scene;if(std::ifstream(root+"/dcdc/full.meta")){power_scene.reset(new FullScene(root+"/dcdc"));full_scenes[1]=power_scene.get();}
  primary_scene.aoi.refresh(root+"/aoi-display");if(power_scene)power_scene->aoi.refresh(root+"/dcdc/aoi-display");
  std::string asset_root=root;int loaded_board=0;

  auto allocate=[fd](unsigned kind,size_t n){return std::make_shared<Buffer>(fd,kind,n);};
  auto upload=[&](const std::string &name,unsigned kind){
   // Stream directly into the mapped DMA buffer. A full intermediate vector
   // temporarily duplicated each 2048 texture and could prevent safe recovery
   // after an AOI job on a 1 GB board.
   std::ifstream in(asset_root+"/"+name,std::ios::binary|std::ios::ate);
   if(!in&&std::ifstream(asset_root+"/"+name+".gz")){
    BO b=allocate(kind,22369920);std::string cmd="gzip -dc '"+asset_root+"/"+name+".gz'";FILE *pipe=popen(cmd.c_str(),"r");if(!pipe)throw std::runtime_error("texture decompressor");
    size_t got=0;while(got<22369920){size_t n=fread(static_cast<unsigned char*>(b->map)+got,1,22369920-got,pipe);if(!n)break;got+=n;}
    int status=pclose(pipe);if(got!=22369920||status)throw std::runtime_error("compressed texture incomplete");return b;
   }
   if(!in)throw std::runtime_error("cannot open texture: "+name);
   const std::streamoff length=in.tellg();if(length<=0||length>(64LL<<20))throw std::runtime_error("invalid texture length: "+name);
   BO b=allocate(kind,size_t(length));in.seekg(0);in.read(static_cast<char*>(b->map),std::streamsize(length));
   if(!in||in.gcount()!=std::streamsize(length))throw std::runtime_error("incomplete texture read: "+name);
   if(release_assets&&name!="ui.bin"&&std::remove((root+"/"+name).c_str()))throw std::runtime_error("temporary texture release failed: "+name);return b;};
  BO textures[5]={upload("gray.bin",GFX3_TEXTURE),upload("color.bin",GFX3_TEXTURE),upload("line.bin",GFX3_TEXTURE),upload("thermal.bin",GFX3_TEXTURE),upload("ui.bin",GFX3_TEXTURE)};
  cache.trim(0); // Immutable DMA textures already own the bytes; release duplicate PS copies.
  BO geometry[2],bins[2],frames[3],objects[3],thumbs[3],depths[3];
  for(int k=0;k<2;k++){geometry[k]=allocate(GFX3_GEOMETRY,16384*128);bins[k]=allocate(GFX3_BINS,16384+GFX3_INITIAL_REFS*4);}
  for(int k=0;k<3;k++){frames[k]=allocate(GFX3_FRAME,1280*720*4);objects[k]=allocate(GFX3_OBJECTS,1280*720*2);thumbs[k]=allocate(GFX3_PREVIEW,640*360*4);if(caps.features&GFX3_FEAT_DEPTH)depths[k]=allocate(GFX3_DEPTH,1280*720*2);}
  Jpeg jpeg(prefix);Shared shared;full_action(shared.target,"raw_board",start_board,primary_scene.points.size());shared.benchmark=benchmark!=0;
  const bool layers=present&&(caps.features&GFX3_FEAT_CURSOR)&&(caps.features&GFX3_FEAT_LAYER);
  // At 62.5 MHz the two DDR reads per pixel (RGB + UI) underrun HDMI.
  // Draw the UI into the real frame and scan only that complete image.
  if(single_plane&&present&&(caps.features&GFX3_FEAT_LAYER)){
   gfx3_layer clear={0,1,0,0};if(ioctl(fd,GFX3_LAYER,&clear))fail("disable scanout overlay");
  }
  shared.cursor_overlay=layers;CursorService cursor_service(fd,shared);
  std::unique_ptr<NativeFrameSynth> ai_frame;BO ai_display_layer,ai_texture,ai_commands,ai_objects;
  if(!ai_model.empty()&&layers&&(caps.features&GFX3_FEAT_DEPTH)){try{ai_frame.reset(new NativeFrameSynth(ai_model));}catch(const std::exception&e){std::cerr<<"frame AI unavailable: "<<e.what()<<std::endl;}}
  std::unique_ptr<FullReference> ui_reference;if(layers){ui_reference.reset(new FullReference(root,true));ui_reference->transparent_layer=true;}
  if(release_assets&&std::remove((root+"/ui.bin").c_str()))throw std::runtime_error("temporary UI texture release failed");
  std::thread server(http_server,std::ref(shared),std::ref(jpeg),port);ServerGuard guard{server};FullMouseInput mouse_input(shared,benchmark?"none":mouse);
  struct CommandEntry{std::string key;std::vector<gfx_command> source;BO sealed,layer;std::shared_ptr<std::vector<uint32_t>> ui;};
  std::vector<gfx_command> last_ui_commands;BO last_ui_layer;std::shared_ptr<std::vector<uint32_t>> last_ui_pixels;
  std::deque<CommandEntry> command_cache;uint64_t command_reuses=0,command_preparations=0;
  std::deque<Flight> flights;uint64_t sequence=uint64_t(caps.reserved[1])+1,submitted=0,measured=0,adopted=0,last_input=0,last_jpeg=0,last_full=0,measure_start=0,last_done=0,last_deferred_drain=0;
  // A new process may receive the same DMA addresses for different textures.
  // Continue the driver sequence so its first upload always invalidates caches.
  // Sixteen reserved generations per process. This stays beyond every previous
  // process's texture variants even when that process rendered only one frame.
  uint64_t texture_generation=sequence*16;
  uint64_t last_jpeg_request=0,last_cursor_preview=~uint64_t(0);
  std::vector<double> durations,latencies;int front=-1;bool slot_used[2]={false,false};
  uint64_t runtime_start=now_ns(),monitor_time=0,metrics_time=0,rotation_time=now_ns(),aoi_poll_time=0,aoi_generation=0;
  std::string aoi_loaded;BO aoi_texture;
  std::deque<uint64_t> render_events,present_events;
  AsyncLog log(prefix+"-frames.jsonl"),monitor(prefix+"-memory.log");AsyncSnapshot metric_file(prefix+"-metrics.json");gfx3_result latest={};View latest_view;Flight last_frame;bool have_frame=false;
  std::unique_ptr<AsyncSnapshot> demo_state;if(!demo_control.empty())demo_state.reset(new AsyncSnapshot(demo_control));
  int demo_seen_config=-1,demo_seen_command=-1,demo_seen_request=-1,demo_seen_mode=-1,demo_seen_board=-1,demo_seen_point=-1;
  uint64_t demo_poll=0;unsigned demo_revision=~0u;int demo_board=-1;
  while(alive){
   bool did=false;View target;bool quiet,quiet_active;
   {std::lock_guard<std::mutex> g(shared.lock);auto tick=now_ns();if(shared.target.autorotate&&!shared.quiet_request){if(tick>rotation_time){shared.target.pose.yaw+=.25*(tick-rotation_time)*1e-9;shared.target.view_revision++;shared.target.sequence++;shared.target.received=tick;rotation_time=tick;}}else rotation_time=tick;target=shared.target;quiet=shared.quiet_request;quiet_active=shared.quiet_active;}
   FullScene &scene=*full_for(target.raw_board);
   {std::lock_guard<std::mutex>g(shared.lock);if(shared.target.raw_board!=target.raw_board)continue;
    if(scene.poll_scan()){shared.target.point=std::min(shared.target.point,int(scene.points.size())-1);shared.target.data_revision++;shared.target.sequence++;shared.target.scene_revision++;shared.target.view_revision++;texture_generation++;}
    shared.target.data_capture=scene.capture_identity;
    if(shared.target.temperature_peak){scene.temperature_raw_at(shared.target,scene.peak_x,scene.peak_y);shared.target.temperature_peak=0;shared.target.sequence++;shared.target.scene_revision++;}
    target=shared.target;
   }
   if(demo_state){
    if(target.scan_config_revision!=demo_seen_config||target.demo_command!=demo_seen_command||target.demo_request!=demo_seen_request||target.mode!=demo_seen_mode||target.raw_board!=demo_seen_board||target.demo_point!=demo_seen_point){
     std::ostringstream state;state<<"{\"session_ns\":"<<jpeg.session<<",\"demo_command\":"<<target.demo_command<<",\"demo_request\":"<<target.demo_request<<",\"mode\":"<<target.mode<<",\"raw_board\":"<<target.raw_board<<",\"demo_point\":"<<target.demo_point<<",\"scan_config_revision\":"<<target.scan_config_revision<<",\"scan_config\":{\"width\":"<<target.scan_width<<",\"height\":"<<target.scan_height<<",\"step_x\":"<<target.scan_step_x<<",\"step_y\":"<<target.scan_step_y<<",\"feed\":"<<target.scan_feed<<"}}";demo_state->publish(state.str());demo_seen_config=target.scan_config_revision;
     demo_seen_command=target.demo_command;demo_seen_request=target.demo_request;demo_seen_mode=target.mode;demo_seen_board=target.raw_board;demo_seen_point=target.demo_point;
    }
    auto tick=now_ns();if(target.mode==16&&tick-demo_poll>=100000000ULL){
     demo_poll=tick;std::ifstream snapshot(scene.demo_path);std::string magic;unsigned revision;
     if(snapshot>>magic>>revision&&magic=="PDPVIEW3"&&(revision!=demo_revision||demo_board!=target.raw_board)){
      scene.demo.refresh(scene.demo_path);if(scene.demo.available&&scene.demo.revision==revision){
       demo_revision=revision;demo_board=target.raw_board;std::lock_guard<std::mutex>g(shared.lock);
       if(shared.target.mode==16&&shared.target.raw_board==target.raw_board){shared.target.demo_total=scene.demo.total;shared.target.demo_active=scene.demo.state>=1&&scene.demo.state<=6;shared.target.sequence++;shared.target.received=tick;shared.target.view_revision++;target=shared.target;}
      }
     }
    }
   }
   jpeg.pause(quiet);
   for(auto &f:flights){
    gfx3_result r={};r.sequence=f.job.sequence;
    if(ioctl(fd,GFX3_WAIT,&r)){if(errno==EAGAIN)continue;fail("wait frame");}
    if(r.error==-ERANGE&&r.rendered&&!benchmark){
     log<<"{\"event\":\"view_rejected\",\"frame\":"<<r.sequence<<",\"input\":"<<f.view.sequence<<",\"reason\":\"hardware_vertex_range\",\"error\":"<<r.error<<"}\n";log.flush();
     f.recorded=true;f.rejected=true;f.result=r;f.result.presented=1;slot_used[f.slot]=false;f.command_buffer.reset();did=true;
     {std::lock_guard<std::mutex>g(shared.lock);if(have_frame&&shared.target.sequence==f.view.sequence)shared.target.pose=latest_view.pose;}
     continue;
    }
    if(r.error){log<<"{\"frame\":"<<r.sequence<<",\"error\":"<<r.error<<",\"rendered\":"<<r.rendered<<",\"presented\":"<<r.presented<<"}\n";log.flush();
     std::ostringstream msg;msg<<"frame failed "<<r.error<<" sequence "<<r.sequence;throw std::runtime_error(msg.str());}
    if(r.rendered&&!f.recorded){
     f.recorded=true;f.result=r;slot_used[f.slot]=false;latest=r;latest_view=f.view;f.command_buffer.reset();last_frame=f;last_frame.layer.reset();have_frame=true;did=true;render_events.push_back(r.render_done_ns);
     if(f.ordinal>uint64_t(warmup)||!benchmark){if(!measure_start)measure_start=r.submit_ns;measured++;last_done=r.render_done_ns;
      if(durations.size()>=4096){durations.erase(durations.begin(),durations.begin()+2048);latencies.erase(latencies.begin(),latencies.begin()+2048);}
      durations.push_back(r.counters[GFX3_TOTAL]*1e3/caps.clock_hz);latencies.push_back((r.render_done_ns-f.view.received)*1e-6);}
     log<<"{\"event\":\"render\",\"frame\":"<<r.sequence<<",\"ordinal\":"<<f.ordinal<<",\"input\":"<<r.input_sequence<<",\"input_received_ns\":"<<f.view.received<<",\"submit_ns\":"<<r.submit_ns<<",\"done_ns\":"<<r.render_done_ns<<",\"app\":"<<full_app_json(f.view)<<",\"benchmark_pose\":"<<bool(benchmark)<<",\"counters\":[";
     for(int c=0;c<GFX3_COUNTER_COUNT;c++){if(c)log<<',';log<<r.counters[c];}log<<"]";
     if(caps.features&GFX3_FEAT_DIAGNOSTIC){gfx3_diagnostic d={};d.sequence=r.sequence;if(ioctl(fd,GFX3_DIAGNOSTIC,&d))fail("frame diagnostic");
      log<<",\"diagnostic\":[";for(int k=0;k<6;k++){if(k)log<<',';log<<d.value[k];}log<<"]";}
     log<<"}\n";log.flush();
    }
    f.result=r;
   }
   while(!flights.empty()&&flights.front().recorded&&(!present||flights.front().result.presented)){
    auto f=flights.front();flights.pop_front();did=true;if(f.rejected)continue;if(present){front=f.frame_index;if(f.ordinal>uint64_t(warmup)||!benchmark)adopted++;
     {std::lock_guard<std::mutex>g(shared.lock);shared.displayed=f.view;shared.have_displayed=true;}present_events.push_back(f.result.present_ns);log<<"{\"event\":\"present\",\"frame\":"<<f.result.sequence<<",\"present_ns\":"<<f.result.present_ns<<"}\n";log.flush();}
   }
   if(now_ns()-last_deferred_drain>=10000000ULL){deferred_free.drain(fd);last_deferred_drain=now_ns();}
   if(power_scene&&loaded_board!=target.raw_board){
    if(!flights.empty()){std::this_thread::sleep_for(std::chrono::milliseconds(1));continue;}
    command_cache.clear();aoi_texture.reset();aoi_loaded.clear();
    for(auto &texture:textures)texture.reset();deferred_free.drain(fd);
    asset_root=root+(target.raw_board?"/dcdc":"");
    const char *names[]={"gray.bin","color.bin","line.bin","thermal.bin","ui.bin"};
    for(int i=0;i<5;i++)textures[i]=upload(names[i],GFX3_TEXTURE);
    loaded_board=target.raw_board;texture_generation+=32;last_input=~uint64_t(0);
    std::lock_guard<std::mutex>g(shared.lock);
    if(shared.target.raw_board!=loaded_board)continue;
    shared.target.aoi_run=scene.aoi.run;shared.target.aoi_status=scene.aoi.status;target=shared.target;
   }
   // Snapshot metadata and texture ownership change only with no frame in flight.
   if(!benchmark&&!quiet&&flights.empty()&&now_ns()-aoi_poll_time>=500000000ULL){
    aoi_poll_time=now_ns();FullAoi next=scene.aoi;
    if(next.refresh(asset_root+"/aoi-display")){std::lock_guard<std::mutex>g(shared.lock);bool changed_run=next.run!=scene.aoi.run;
     scene.aoi=std::move(next);shared.target.aoi_run=scene.aoi.run;shared.target.aoi_status=scene.aoi.status;
     if(changed_run){shared.target.aoi_selected=0;shared.target.aoi_zoom=1.;shared.target.aoi_pan_x=shared.target.aoi_pan_y=0.;}
     if(shared.target.mode==12){shared.target.scene_revision++;shared.target.menu_revision++;shared.target.sequence++;shared.target.received=now_ns();target=shared.target;}}
   }
   if(quiet&&!quiet_active&&flights.empty()&&jpeg.idle()){
    gfx3_quiet q={1,0,100000000};if(ioctl(fd,GFX3_QUIET,&q))fail("quiet fence");{std::lock_guard<std::mutex>g(shared.lock);shared.quiet_active=q.active;}did=true;
   }else if(!quiet&&quiet_active){gfx3_quiet q={0,0,0};if(ioctl(fd,GFX3_QUIET,&q))fail("resume graphics");{std::lock_guard<std::mutex>g(shared.lock);shared.quiet_active=false;}did=true;}
   if(preview&&have_frame&&!quiet){
    uint64_t now=now_ns();bool full=!benchmark&&now-target.received>300000000&&last_frame.view.sequence==target.sequence;
    if((full&&(last_full!=last_frame.job.sequence||(layers&&last_cursor_preview!=target.cursor_revision&&now-last_jpeg_request>=66666667)))||(!full&&last_jpeg!=last_frame.job.sequence&&now-last_frame.result.render_done_ns<500000000&&now-last_jpeg_request>=66666667)){
     auto image=std::make_shared<ImageJob>(full?frames[last_frame.frame_index]:thumbs[last_frame.frame_index],full?1280*720*4:640*360*4);
     image->ui=single_plane?nullptr:last_frame.ui;image->cursor_x=target.cursor_x;image->cursor_y=target.cursor_y;image->cursor_visible=target.cursor_visible;image->cursor_revision=target.cursor_revision;last_cursor_preview=target.cursor_revision;
     image->frame=last_frame.result;image->w=full?1280:640;image->h=full?720:360;image->full=full;image->heat=last_frame.view.heat;image->emi=last_frame.view.emi;
     jpeg.submit(image);last_jpeg=last_frame.job.sequence;last_jpeg_request=now;if(full)last_full=last_frame.job.sequence;
    }
   }
   bool expired=seconds>0&&now_ns()-runtime_start>=uint64_t(seconds)*1000000000;
   if(now_ns()-monitor_time>=5000000000ULL){monitor_time=now_ns();cache.rebalance();monitor<<"MONOTONIC_NS "<<monitor_time<<'\n';std::ifstream info("/proc/meminfo");monitor<<info.rdbuf();
    double temperature=die_temperature_mC();if(std::isfinite(temperature))monitor<<"Temperature_mC "<<std::llround(temperature)<<'\n';monitor.flush();}
   bool wanted=!expired&&(benchmark?submitted<uint64_t(benchmark+warmup):target.sequence!=last_input);
   // Interactive poses are chosen when the renderer becomes free. Keep only
   // the latest complete view, instead of queueing another obsolete mouse pose.
   if(!benchmark)for(const auto &f:flights)if(!f.recorded)wanted=false;
   if(!quiet&&wanted&&target.mode==12&&scene.aoi.available){
    std::string key=scene.aoi.run+(target.aoi_variant?":rgb":":gray");
    if(target.aoi_run!=scene.aoi.run)wanted=false;
    else if(key!=aoi_loaded){
     if(!flights.empty())wanted=false;
     else{try{auto bytes=full_read<unsigned char>(scene.aoi.texture_path(target.aoi_variant));
       if(bytes.size()!=5592704)throw std::runtime_error("invalid AOI 8x4 texture size");
       if(!aoi_texture)aoi_texture=allocate(GFX3_TEXTURE,bytes.size());
       memcpy(aoi_texture->map,bytes.data(),bytes.size());aoi_loaded=key;aoi_generation=(sequence+1)*16+8;
      }catch(const std::exception &error){
       log<<"AOI texture unavailable: "<<error.what()<<'\n';log.flush();aoi_loaded.clear();
       std::lock_guard<std::mutex>g(shared.lock);scene.aoi.status="OFFLINE";scene.aoi.available=false;scene.aoi.run.clear();scene.aoi.regions.clear();
       shared.target.aoi_run.clear();shared.target.aoi_status="OFFLINE";shared.target.scene_revision++;shared.target.menu_revision++;shared.target.sequence++;shared.target.received=now_ns();target=shared.target;
      }}
    }
   }
   if(!quiet&&wanted&&flights.size()<2){
    int slot=slot_used[0]?(slot_used[1]?-1:1):0;
    for(int frame=0;slot>=0&&frame<3;frame++){
     bool used=frame==front||frames[frame]->jpeg_users||thumbs[frame]->jpeg_users;
     for(auto &f:flights)used=used||f.frame_index==frame;if(used)continue;
     if(!benchmark){std::lock_guard<std::mutex>g(shared.lock);target=shared.target;if(shared.quiet_request)break;}
     if(target.raw_board!=loaded_board)break;
     if(target.mode==12&&scene.aoi.available&&(target.aoi_run!=scene.aoi.run||aoi_loaded!=scene.aoi.run+(target.aoi_variant?":rgb":":gray")))break;
     Flight f;f.frame_index=frame;f.slot=slot;f.view=target;f.ordinal=submitted+1;
     if(benchmark){f.view.sequence=sequence;f.view.received=now_ns();f.view.pose.yaw+=submitted*.006;f.view.pose.polar+=.12*std::sin(submitted*.017);}
     auto &j=f.job;j.sequence=sequence;j.input_sequence=f.view.sequence;j.source_generation=(f.view.mode==12&&scene.aoi.available&&aoi_texture)?aoi_generation:texture_generation+f.view.base+(f.view.mode==11?8:0);
     std::string mouse_device;{std::lock_guard<std::mutex>g(shared.lock);mouse_device=shared.mouse_device;}
     auto key=FullScene::command_key(f.view,mouse_device,shared.cursor_overlay);
     // The scan page reads an atomic snapshot updated by the replay scheduler.
     // A refresh input must rebuild its commands even when the point is unchanged.
     if(f.view.mode==16)command_cache.clear();
     auto found=std::find_if(command_cache.begin(),command_cache.end(),[&](const CommandEntry&e){return e.key==key;});
     if(found==command_cache.end()){
      // Completed flights retain their own BO references. Evict old menu and
      // command copies before allocating a different mode on a 1 GB board.
      while(!command_cache.empty())command_cache.pop_front();
      deferred_free.drain(fd);
      try{
      auto build_view=f.view;if(shared.cursor_overlay)build_view.cursor_visible=0;
      CommandEntry entry;entry.key=key;entry.source=scene.build(build_view,mouse_device,0,!layers||single_plane);
      if(layers){FullDraw d(scene.glyphs);
       // Raw pages already contain their own complete UI in PL commands.
       if(build_view.mode<13)scene.hud(d,build_view,mouse_device,0,false);
       d.commands.push_back(gfx_command{});
       bool unchanged=last_ui_pixels&&d.commands.size()==last_ui_commands.size()&&!memcmp(d.commands.data(),last_ui_commands.data(),d.commands.size()*sizeof(gfx_command));
       if(!unchanged){int32_t identity[12]={};ui_reference->render(d.commands,identity,build_view);
        last_ui_pixels=std::make_shared<std::vector<uint32_t>>(ui_reference->pixels);
        if(!single_plane){last_ui_layer=allocate(GFX3_FRAME,1280*720*4);memcpy(last_ui_layer->map,last_ui_pixels->data(),1280*720*4);}last_ui_commands=std::move(d.commands);
       }
       entry.ui=last_ui_pixels;entry.layer=last_ui_layer;
      }
      entry.sealed=allocate(GFX3_COMMANDS,entry.source.size()*sizeof(gfx_command));memcpy(entry.sealed->map,entry.source.data(),entry.source.size()*sizeof(gfx_command));
      gfx3_seal seal={entry.sealed->u.handle,uint32_t(entry.source.size()),0,0};if(ioctl(fd,GFX3_SEAL,&seal))fail("seal cached commands");
      command_cache.push_back(std::move(entry));found=command_cache.end()-1;command_preparations++;
      }catch(const std::exception &error){
       const auto *system=dynamic_cast<const std::system_error*>(&error);
       if(!dynamic_cast<const std::bad_alloc*>(&error)&&(!system||(system->code().value()!=ENOMEM&&system->code().value()!=ENOSPC)))throw;
       log<<"render allocation failed; retaining displayed frame: "<<error.what()<<'\n';log.flush();
       std::lock_guard<std::mutex>g(shared.lock);shared.render_error="Insufficient memory; previous frame retained";
       if(shared.have_displayed){View keep=shared.displayed;keep.sequence=shared.target.sequence+1;keep.received=now_ns();shared.target=keep;target=keep;last_input=keep.sequence;}
       else throw;
       break;
      }
     }else command_reuses++;
     // Re-read the latest pose just before committing; keep scene revisions atomic.
     if(!benchmark){std::lock_guard<std::mutex>g(shared.lock);if(shared.quiet_request)break;
      if(FullScene::command_key(shared.target,shared.mouse_device,shared.cursor_overlay)!=key)continue;f.view=shared.target;}
     j.input_sequence=f.view.sequence;f.command_buffer=found->sealed;f.layer=found->layer;f.ui=found->ui;
     gfx_view_matrix(f.view.pose,j.matrix);if(f.view.hud){j.matrix[3]-=full_q(FULL_PROJECTION_X);j.matrix[7]-=full_q(60);}j.alpha=f.view.heat;j.background=0xff0d1722;
     size_t command_count=found->source.size();
     if(!gfx_pose_fits(found->source.data(),found->source.size(),j.matrix)){
      auto clipped=gfx_clip_overflow(found->source,j.matrix);f.command_buffer=allocate(GFX3_COMMANDS,clipped.size()*sizeof(gfx_command));
      memcpy(f.command_buffer->map,clipped.data(),clipped.size()*sizeof(gfx_command));gfx3_seal seal={f.command_buffer->u.handle,uint32_t(clipped.size()),0,0};
      if(ioctl(fd,GFX3_SEAL,&seal))fail("seal clipped zoom geometry");command_count=clipped.size();
     }
     j.commands=f.command_buffer->u.handle;j.command_count=command_count;j.geometry=geometry[slot]->u.handle;j.bins=bins[slot]->u.handle;j.refs_capacity=GFX3_INITIAL_REFS;
     j.frame=frames[frame]->u.handle;j.objects=objects[frame]->u.handle;j.thumbnail=thumbs[frame]->u.handle;
     j.width=1280;j.height=720;j.stride=5120;j.flags=(present?GFX3_PRESENT:0)|(preview?GFX3_THUMBNAIL:0)|(f.view.native?GFX3_NATIVE_DISPLAY:0)|((layers&&!single_plane)?GFX3_LAYER_JOB:0);if(layers&&!single_plane)j.reserved[0]=f.layer->u.handle;if(depths[frame]){j.flags|=GFX3_DEPTH_JOB;j.reserved[1]=depths[frame]->u.handle;}
     int tex_indices[3]={f.view.mode==11?3:f.view.base,4,3};gfx3_texture *tx[3]={&j.rgb,&j.ground,&j.thermal};for(int t=0;t<3;t++)*tx[t]={textures[tex_indices[t]]->u.handle,2048,2048,12};
     if(f.view.mode==12&&scene.aoi.available&&aoi_texture)j.rgb={aoi_texture->u.handle,1024,1024,11};
     // At most one intermediate display per completed real render. The next
     // real render is always submitted; synthetic pixels never enter analysis.
     if(ai_frame&&flights.empty()&&have_frame&&front==last_frame.frame_index&&depths[front]&&f.ui&&
       (f.view.mode==0||f.view.mode==3)&&last_frame.view.mode==f.view.mode&&last_frame.view.raw_board==f.view.raw_board&&
       FullScene::command_key(last_frame.view,mouse_device,true)==FullScene::command_key(f.view,mouse_device,true)&&
       last_frame.job.source_generation==j.source_generation&&last_frame.view.base==f.view.base&&last_frame.view.heat==f.view.heat&&
       last_frame.view.emi==f.view.emi&&last_frame.view.relief==f.view.relief&&last_frame.view.band==f.view.band&&
       last_frame.view.components==f.view.components&&last_frame.view.points==f.view.points&&last_frame.view.hud==f.view.hud&&
       std::abs(last_frame.view.pose.yaw-f.view.pose.yaw)<.025&&std::abs(last_frame.view.pose.polar-f.view.pose.polar)<.025&&
       std::abs(last_frame.view.pose.zoom-f.view.pose.zoom)<.0001&&
       last_frame.view.pose.target[0]==f.view.pose.target[0]&&last_frame.view.pose.target[1]==f.view.pose.target[1]&&last_frame.view.pose.target[2]==f.view.pose.target[2]){
      try{
       gfx3_layer available={};if(ioctl(fd,GFX3_LAYER,&available)==0&&!available.pending_handle){
        auto mid=f.view;mid.pose.yaw=(last_frame.view.pose.yaw+f.view.pose.yaw)*.5;mid.pose.polar=(last_frame.view.pose.polar+f.view.pose.polar)*.5;
        int32_t matrix[12];gfx_view_matrix(mid.pose,matrix);if(mid.hud){matrix[3]-=full_q(FULL_PROJECTION_X);matrix[7]-=full_q(60);}
        std::vector<uint32_t> pixels;auto begin=now_ns();
        if(ai_frame->generate(static_cast<const uint32_t*>(frames[front]->map),static_cast<const uint16_t*>(depths[front]->map),static_cast<const uint16_t*>(objects[front]->map),last_frame.job.matrix,matrix,last_frame.job.sequence,pixels)){
         // Composite the current UI independently. Hardware cursor remains a
         // separate scanout plane; picking stays bound to shared.displayed.
         NativeFrameSynth::overlay_ui(pixels,*f.ui);
         if(single_plane){
          // Keep the real RGB/depth/ID buffers immutable. Upload the prepared
          // intermediate to its own texture and let PL blit/present a separate
          // frame through the existing validated BO/job interface.
          if(!ai_texture){
           ai_texture=allocate(GFX3_TEXTURE,1280*720*4);
           ai_display_layer=allocate(GFX3_FRAME,1280*720*4);
           ai_objects=allocate(GFX3_OBJECTS,1280*720*2);
           FullDraw draw(scene.glyphs);draw.rgb_image(0,0,1280,720,0,0,1,1);draw.commands.push_back(gfx_command{});
           ai_commands=allocate(GFX3_COMMANDS,draw.commands.size()*sizeof(gfx_command));
           memcpy(ai_commands->map,draw.commands.data(),draw.commands.size()*sizeof(gfx_command));
           gfx3_seal seal={ai_commands->u.handle,uint32_t(draw.commands.size()),0,0};if(ioctl(fd,GFX3_SEAL,&seal))fail("seal intermediate frame");
          }
          auto tiled=static_cast<uint32_t*>(ai_texture->map);
          NativeFrameSynth::tile_display(pixels,tiled);
          gfx3_job intermediate=j;intermediate.sequence=sequence++;
          intermediate.source_generation=0x80000000U|uint32_t(intermediate.sequence);
          intermediate.commands=ai_commands->u.handle;intermediate.command_count=3;
          intermediate.frame=ai_display_layer->u.handle;intermediate.objects=ai_objects->u.handle;intermediate.thumbnail=0;
          intermediate.rgb={ai_texture->u.handle,1280,720,1};
          intermediate.flags=GFX3_PRESENT|(j.flags&GFX3_NATIVE_DISPLAY);intermediate.reserved[0]=intermediate.reserved[1]=0;
          if(ioctl(fd,GFX3_SUBMIT,&intermediate))fail("submit intermediate frame");
          gfx3_result shown={};shown.sequence=intermediate.sequence;auto deadline=now_ns()+3000000000ULL;
          do{if(ioctl(fd,GFX3_WAIT,&shown)&&errno!=EAGAIN)fail("wait intermediate frame");
           if(shown.error)throw std::runtime_error("intermediate render failed");
           if(now_ns()>deadline)throw std::runtime_error("intermediate present timeout");
           if(!shown.presented)std::this_thread::sleep_for(std::chrono::milliseconds(1));
          }while(!shown.presented);
          j.sequence=sequence;
          log<<"{\"event\":\"synthetic_display_submitted\",\"display_path\":\"single_plane_pl_blit\",\"picking_real_frame\":"<<last_frame.job.sequence<<",\"display_sequence\":"<<intermediate.sequence<<",\"blend_mean\":"<<ai_frame->blend_mean<<",\"neural_changed_pixels\":"<<ai_frame->changed_pixels<<",\"coverage\":"<<ai_frame->coverage<<",\"project_ns\":"<<ai_frame->project_ns<<",\"feature_ns\":"<<ai_frame->feature_ns<<",\"fallback_ns\":"<<ai_frame->fallback_ns<<",\"quantize_ns\":"<<ai_frame->quantize_ns<<",\"infer_ns\":"<<ai_frame->infer_ns<<",\"compose_ns\":"<<ai_frame->compose_ns<<",\"prepare_ns\":"<<now_ns()-begin<<",\"measurement_input\":false,\"pl_task\":2}\n";log.flush();
         }else{
          auto layer=allocate(GFX3_FRAME,1280*720*4);memcpy(layer->map,pixels.data(),pixels.size()*4);
          gfx3_layer show={layer->u.handle,1,0,0};if(ioctl(fd,GFX3_LAYER,&show)==0){ai_display_layer=layer;
           log<<"{\"event\":\"synthetic_display_submitted\",\"picking_real_frame\":"<<last_frame.job.sequence<<",\"blend_mean\":"<<ai_frame->blend_mean<<",\"neural_changed_pixels\":"<<ai_frame->changed_pixels<<",\"coverage\":"<<ai_frame->coverage<<",\"project_ns\":"<<ai_frame->project_ns<<",\"feature_ns\":"<<ai_frame->feature_ns<<",\"fallback_ns\":"<<ai_frame->fallback_ns<<",\"quantize_ns\":"<<ai_frame->quantize_ns<<",\"infer_ns\":"<<ai_frame->infer_ns<<",\"compose_ns\":"<<ai_frame->compose_ns<<",\"prepare_ns\":"<<now_ns()-begin<<",\"measurement_input\":false,\"pl_task\":2}\n";log.flush();}
         }
        }
       }
      }catch(const std::exception&e){log<<"frame synthesis rejected: "<<e.what()<<'\n';log.flush();}
     }
     if(ioctl(fd,GFX3_SUBMIT,&j)){if(errno==EBUSY)continue;fail("submit frame");}
     {std::lock_guard<std::mutex>g(shared.lock);shared.render_error.clear();}
     sequence++;submitted++;last_input=f.view.sequence;slot_used[slot]=true;flights.push_back(f);did=true;break;
    }
   }
   uint64_t metrics_now=now_ns();
   while(!render_events.empty()&&metrics_now-render_events.front()>5000000000ULL)render_events.pop_front();
   while(!present_events.empty()&&metrics_now-present_events.front()>5000000000ULL)present_events.pop_front();
   if(metrics_now-metrics_time>=100000000ULL){metrics_time=metrics_now;
    ioctl(fd,GFX3_CAPS,&caps);std::string text;
    bool metric_quiet,metric_benchmark;{std::lock_guard<std::mutex>g(shared.lock);metric_quiet=shared.quiet_active;metric_benchmark=shared.benchmark;}
    text=make_metrics(caps,metric_quiet,metric_benchmark,latest_view,latest.sequence,measured,adopted,measure_start,last_done,durations,latencies,latest,cache.bytes,cache.limit,preview,
     recent_rate(render_events,metrics_now,runtime_start),recent_rate(present_events,metrics_now,runtime_start));
    text.pop_back();text+=",\"single_plane_scanout\":"+std::to_string(single_plane)+"}";
    size_t deferred_count=0;uint64_t deferred_errors=0;deferred_free.stats(deferred_count,deferred_errors);
    text.pop_back();text+=",\"command_cache_hits\":"+std::to_string(command_reuses)+",\"command_preparations\":"+std::to_string(command_preparations)+",\"deferred_buffers\":"+std::to_string(deferred_count)+",\"release_errors\":"+std::to_string(deferred_errors)+",\"log_dropped\":"+std::to_string(log.dropped.load())+",\"log_write_errors\":"+std::to_string(log.write_errors.load())+",\"snapshot_write_errors\":"+std::to_string(metric_file.write_errors.load())+",\"cursor_error\":"+std::to_string(cursor_service.error.load())+"}";
    {std::lock_guard<std::mutex>g(shared.lock);shared.metrics=text;}
    // Publishing runs at 10 Hz; disk work is outside the input lock.
    static uint64_t file_time=0;if(metrics_now-file_time>=1000000000ULL){file_time=metrics_now;
     metric_file.publish(text);}
   }
   if((expired||(benchmark&&submitted==uint64_t(benchmark+warmup)))&&flights.empty())break;
   if(!did)usleep(flights.empty()&&!target.autorotate?5000:1000);
  }
  alive=false;server.join();gfx3_quiet q={1,0,10000000000ULL};ioctl(fd,GFX3_QUIET,&q);
  if(have_frame&&q.active){
   const auto &f=last_frame;
   std::ofstream raw(prefix+"-frame.argb",std::ios::binary);raw.write(static_cast<const char*>(frames[f.frame_index]->map),1280*720*4);
   std::ofstream ids(prefix+"-objects.u16",std::ios::binary);ids.write(static_cast<const char*>(objects[f.frame_index]->map),1280*720*2);
   std::ofstream state(prefix+"-last-view.json");state<<"{\"frame_id\":"<<f.result.sequence<<",\"input_sequence\":"<<f.result.input_sequence<<",\"source_tag\":"<<tag<<",\"width\":1280,\"height\":720,\"matrix\":[";
   for(int k=0;k<12;k++){if(k)state<<',';state<<f.job.matrix[k];}state<<"]}";
  }
  std::cout<<shared.metrics<<std::endl;
  // The retained display front remains pinned by the driver until a coordinated reset.
  return 0;
 }catch(const std::exception &e){std::cerr<<"GFX3_RUNTIME_ERROR "<<e.what()<<std::endl;return 1;}
}
