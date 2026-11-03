#include <memory>
#include "src/driver/gfx3_view_matrix.h"
#include <array>
#include <map>
#include <vector>
#include <string>
#include <fstream>
#include <sstream>
#include <iostream>
#include <iomanip>
#include <stdexcept>
#include <chrono>
#include <cstdint>
#include <cstring>
#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#endif
#include "src/driver/full_state.h"
static uint64_t now_ns(){return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
struct View:FullState {GfxView pose;uint64_t sequence=1,received=now_ns();int heat=179,emi=1,native=0;View(){pose.zoom=.78;}};
#include "src/driver/full_scene.h"
#include "src/driver/full_reference.h"
static FullScene *full_scene=nullptr,*full_scenes[2]={nullptr,nullptr};
static FullScene *full_for(int board){return full_scenes[board?1:0]?full_scenes[board?1:0]:full_scene;}
struct Shared{View target,displayed;bool have_displayed=false,cursor_overlay=true;FullDrag drag;};
#include "reference-generated.h"
int main(int argc,char**argv){try{
 if(argc!=3&&argc!=5)throw std::runtime_error("reference_bridge ASSETS OUTPUT_PREFIX [--shared-memory NAME]");
 unsigned char *shared_pixels=nullptr;
#ifdef _WIN32
 HANDLE mapping=nullptr;
 if(argc==5){if(std::string(argv[3])!="--shared-memory")throw std::runtime_error("invalid shared image option");
  mapping=OpenFileMappingA(FILE_MAP_ALL_ACCESS,FALSE,argv[4]);if(!mapping)throw std::runtime_error("cannot open shared image");
  shared_pixels=static_cast<unsigned char*>(MapViewOfFile(mapping,FILE_MAP_ALL_ACCESS,0,0,1280*720*4));if(!shared_pixels)throw std::runtime_error("cannot map shared image");}
#else
 if(argc==5)throw std::runtime_error("named shared image is Windows-only; use the file reference on this host");
#endif
 FullScene primary(argv[1]);full_scene=&primary;full_scenes[0]=&primary;std::unique_ptr<FullScene> power;if(std::ifstream(std::string(argv[1])+"/dcdc/full.meta")){power.reset(new FullScene(std::string(argv[1])+"/dcdc"));full_scenes[1]=power.get();}FullScene &scene=primary;scene.aoi.refresh(std::string(argv[1])+"/aoi-display");FullReference renderer(argv[1]);
 if(scene.aoi.available){renderer.textures.emplace_back(scene.aoi.texture_path(0),1024,true);renderer.textures.emplace_back(scene.aoi.texture_path(1),1024,true);}
 int renderer_board=0;Shared shared;shared.target.aoi_run=scene.aoi.run;shared.target.aoi_status=scene.aoi.status;std::string prefix=argv[2],line;
 std::vector<gfx_command> cached_commands;std::vector<uint32_t> cached_pixels;std::vector<uint16_t> cached_ids,cached_depth;
 int32_t cached_matrix[12]={};int cached_base=-1,cached_heat=-1,cached_thermal_only=-1,cached_aoi_variant=-1;
 while(std::getline(std::cin,line))try{
  std::istringstream input(line);std::string operation;input>>operation;
  if(operation=="app"){
   View next=shared.target;std::string key;double value;int count=0;while(input>>key){if(!(input>>value)||!(key=="focus"?full_for(next.raw_board)->focus(next,next.selected_component):full_action(next,key,value,full_for(next.raw_board)->points.size())))throw std::runtime_error("invalid action");count++;}
   if(!input.eof()||!count)throw std::runtime_error("invalid command");if(next.cursor_visible!=shared.target.cursor_visible)next.cursor_revision++;next.sequence=shared.target.sequence+1;next.received=now_ns();shared.target=next;
  }else if(operation=="pointer"){
   int kind,x,y,button;double wheel;if(!(input>>kind>>x>>y>>button>>wheel)||kind<0||kind>4||x<0||x>1279||y<0||y>719||button<0||button>2||!std::isfinite(wheel)||std::abs(wheel)>20)throw std::runtime_error("invalid pointer");
   full_input_locked(shared,kind,x,y,button,wheel);
  }else if(operation!="dump")throw std::runtime_error("unknown command");
  auto t=now_ns();auto &v=shared.target;FullScene &active=*full_for(v.raw_board);
  if(renderer_board!=v.raw_board){renderer=FullReference(std::string(argv[1])+(v.raw_board?"/dcdc":""));renderer_board=v.raw_board;cached_base=-1;cached_commands.clear();}
  active.aoi.refresh(std::string(argv[1])+(v.raw_board?"/dcdc/aoi-display":"/aoi-display"));
  if(active.aoi.available&&renderer.textures.size()<7){renderer.textures.emplace_back(active.aoi.texture_path(0),1024,true);renderer.textures.emplace_back(active.aoi.texture_path(1),1024,true);}
  v.aoi_run=active.aoi.run;v.aoi_status=active.aoi.status;
  auto commands=active.build(v,"__reference__",0);int32_t matrix[12];gfx_view_matrix(v.pose,matrix);if(v.hud){matrix[3]-=full_q(FULL_PROJECTION_X);matrix[7]-=full_q(60);}
  if(!gfx_pose_fits(commands.data(),commands.size(),matrix))commands=gfx_clip_overflow(commands,matrix);
  bool cursor=v.cursor_visible&&commands.size()>=3&&commands[commands.size()-2].object_id==65530&&commands[commands.size()-3].object_id==65530;
  auto base_commands=commands;if(cursor){base_commands.resize(base_commands.size()-3);base_commands.push_back(gfx_command{});}
  bool reuse=cached_base==v.base&&cached_heat==v.heat&&cached_thermal_only==(v.mode==11)&&cached_aoi_variant==(v.mode==12?v.aoi_variant:-1)&&cached_commands.size()==base_commands.size()&&
    !std::memcmp(cached_matrix,matrix,48)&&!std::memcmp(cached_commands.data(),base_commands.data(),base_commands.size()*64);
  auto prepared=now_ns();
  if(!reuse){renderer.render(base_commands,matrix,v);cached_pixels=renderer.pixels;cached_ids=renderer.ids;cached_depth=renderer.depth;
   cached_commands=std::move(base_commands);std::memcpy(cached_matrix,matrix,48);cached_base=v.base;cached_heat=v.heat;cached_thermal_only=v.mode==11;cached_aoi_variant=v.mode==12?v.aoi_variant:-1;
  }else{renderer.pixels=cached_pixels;renderer.ids=cached_ids;renderer.depth=cached_depth;renderer.fragments=0;}
  if(cursor)for(size_t i=commands.size()-3;i<commands.size()-1;i++){FullReference::V p[3];for(int a=0;a<3;a++)p[a]=FullReference::transform(commands[i].v[a],matrix,true);renderer.triangle(p,commands[i],v);}
  auto rastered=now_ns();
  // The live preview uses an owned shared image; reference files are exported
  // only on request. No pixels, resolution, shader or rounding rules change.
  if(shared_pixels)std::memcpy(shared_pixels,renderer.pixels.data(),renderer.pixels.size()*4);
  if(!shared_pixels||operation=="dump"){
   std::ofstream raw(prefix+".argb",std::ios::binary);raw.write(reinterpret_cast<const char*>(renderer.pixels.data()),renderer.pixels.size()*4);raw.close();
   std::ofstream ids(prefix+".u16",std::ios::binary);ids.write(reinterpret_cast<const char*>(renderer.ids.data()),renderer.ids.size()*2);ids.close();
   std::ofstream depth(prefix+".depth.u16",std::ios::binary);depth.write(reinterpret_cast<const char*>(renderer.depth.data()),renderer.depth.size()*2);depth.close();
   std::ofstream cmd(prefix+".commands",std::ios::binary);cmd.write(reinterpret_cast<const char*>(commands.data()),commands.size()*64);cmd.close();
   std::ofstream mat(prefix+".matrix",std::ios::binary);mat.write(reinterpret_cast<const char*>(matrix),48);mat.close();
  }
  auto transported=now_ns();shared.displayed=v;shared.have_displayed=true;
  std::cout<<"{\"offline_reference\":true,\"app\":"<<full_app_json(v)<<",\"reference_render_ms\":"<<(transported-t)*1e-6
   <<",\"prepare_ms\":"<<(prepared-t)*1e-6<<",\"raster_ms\":"<<(rastered-prepared)*1e-6<<",\"transport_ms\":"<<(transported-rastered)*1e-6
   <<",\"scene_reused\":"<<reuse<<",\"shared_memory\":"<<bool(shared_pixels)<<",\"command_count\":"<<commands.size()<<",\"covered_fragments\":"<<renderer.fragments<<"}"<<std::endl;
 }catch(const std::exception&e){std::cout<<"{\"error\":\""<<e.what()<<"\"}"<<std::endl;}
#ifdef _WIN32
 if(shared_pixels)UnmapViewOfFile(shared_pixels);if(mapping)CloseHandle(mapping);
#endif
 return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<std::endl;return 1;}}
