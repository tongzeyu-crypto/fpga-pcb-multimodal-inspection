#ifndef GFX3_VIEW_MATRIX_H
#define GFX3_VIEW_MATRIX_H
#include <cmath>
#include "full_layout.h"
#include <cstdint>
#include <algorithm>
#include <cstddef>
#include <array>
#include <vector>
#include <stdexcept>
#include "../include/gfx3_commands.h"
struct GfxView {double yaw=.5907126240134984,polar=.9642783264550344,radius=124.55922286205868,zoom=1.1;double target[3]={-2,1,0};};
inline void gfx_view_matrix(const GfxView &v,int32_t result[12],int width=1280,int height=720){
 double delta[3]={v.radius*std::sin(v.polar)*std::sin(v.yaw),v.radius*std::cos(v.polar),v.radius*std::sin(v.polar)*std::cos(v.yaw)};
 double eye[3],forward[3],right[3],up[3],length;
 for(int k=0;k<3;k++){eye[k]=v.target[k]+delta[k];forward[k]=-delta[k]/v.radius;}
 right[0]=-forward[2];right[1]=0;right[2]=forward[0];length=std::hypot(right[0],right[2]);
 for(int k=0;k<3;k++)right[k]/=length;
 up[0]=right[1]*forward[2]-right[2]*forward[1];up[1]=right[2]*forward[0]-right[0]*forward[2];up[2]=right[0]*forward[1]-right[1]*forward[0];
 double m[12]={0},scale=height/(72/v.zoom);m[3]=width*.5;m[7]=height*.5;
 for(int k=0;k<3;k++){m[k]=right[k]*scale;m[4+k]=-up[k]*scale;m[8+k]=forward[k]/400;m[3]-=m[k]*v.target[k];m[7]-=m[4+k]*v.target[k];m[11]-=forward[k]*eye[k]/400;}
 for(int k=0;k<12;k++)result[k]=int32_t(std::llround(m[k]*65536));
}
inline bool gfx_pose_fits(const gfx_command *commands,size_t count,const int32_t matrix[12]){
 for(size_t c=0;c<count;c++){
  unsigned op=commands[c].opcode_flags&255;if(op==GFX_END)break;
  int vertices=op==GFX_SPRITE?1:3;
  for(int p=0;p<vertices;p++)for(int row=0;row<2;row++){
   int64_t value;
   // SCREEN commands start in Q16.16 pixels, while the raster input and
   // transformed world vertices use signed Q12.4 pixels.
   if(op==GFX_SCREEN_TRIANGLE)value=int64_t(row?commands[c].v[p].y:commands[c].v[p].x)>>12;
   else{const auto &v=commands[c].v[p];value=(int64_t(matrix[row*4])*v.x+int64_t(matrix[row*4+1])*v.y+int64_t(matrix[row*4+2])*v.z+int64_t(matrix[row*4+3])*65536)>>28;}
   // Leave margin for the largest 26-pixel billboard around its centre.
   if(value < -32000 || value>32000)return false;
  }
 }
 return true;
}
// Screen-plane pan is invariant under polar angle, including side views.
inline void gfx_pan(GfxView &v,double dx,double dy){
 int32_t m[12];gfx_view_matrix(v,m);double scale=10*v.zoom;
 for(int k=0;k<3;k++)v.target[k]-=(dx*m[k]+dy*m[4+k])/(65536*scale*scale);
}
inline std::array<double,3> gfx_plane_anchor(const GfxView &v,double x,double y,bool hud,double hud_shift_x=4){
 int32_t m[12];gfx_view_matrix(v,m);double dx=x-(640-(hud?hud_shift_x:0)),dy=y-(360-(hud?60:0));
 std::array<double,3> a;double scale=10*v.zoom;
 for(int k=0;k<3;k++)a[k]=v.target[k]+(dx*m[k]+dy*m[4+k])/(65536*scale*scale);return a;
}
inline void gfx_zoom_anchor(GfxView &v,double zoom,double x,double y,bool hud,const double a[3],double hud_shift_x=4){
 v.zoom=std::max(.2,std::min(8.,zoom));int32_t m[12];gfx_view_matrix(v,m);
 double px=(m[0]*a[0]+m[1]*a[1]+m[2]*a[2]+m[3])/65536.-(hud?hud_shift_x:0);
 double py=(m[4]*a[0]+m[5]*a[1]+m[6]*a[2]+m[7])/65536.-(hud?60:0);
 gfx_pan(v,x-px,y-py);
}
// Exceptional zoom path only: normal in-range commands remain byte-identical.
// The PS clips overflowing geometry before the existing Q12.4 PL front end.
// This is preparation cost, not claimed as a hardware vertex-clip accelerator.
inline std::vector<gfx_command> gfx_clip_overflow(const std::vector<gfx_command>&src,const int32_t m[12]){
 struct P{long double x,y,z,u,v;};std::vector<gfx_command> out;out.reserve(src.size());
 for(const auto &c:src){unsigned op=c.opcode_flags&255;if(!op)break;
  if(gfx_pose_fits(&c,1,m)){out.push_back(c);continue;}
  auto transform=[&](const gfx_vertex_word &v){P p;p.u=v.uv&65535;p.v=v.uv>>16;
   if(op==GFX_SCREEN_TRIANGLE){p.x=int64_t(v.x)>>12;p.y=int64_t(v.y)>>12;p.z=uint32_t(v.z)&65535;}
   else{int64_t q[3];for(int k=0;k<3;k++)q[k]=int64_t(m[k*4])*v.x+int64_t(m[k*4+1])*v.y+int64_t(m[k*4+2])*v.z+int64_t(m[k*4+3])*65536;
    p.x=q[0]>>28;p.y=q[1]>>28;p.z=std::max<int64_t>(0,std::min<int64_t>(65535,q[2]>>16));}return p;};
  if(op==GFX_SPRITE){auto p=transform(c.v[0]);long double rx=std::abs(int64_t(c.v[1].x)>>13),ry=std::abs(int64_t(c.v[1].y)>>13);
   if(p.x+rx<0||p.x-rx>1280*16||p.y+ry<0||p.y-ry>720*16)continue;
   throw std::runtime_error("visible oversized sprite exceeds guarded format");}
  std::vector<P> polygon={transform(c.v[0]),transform(c.v[1]),transform(c.v[2])};
  const long double limits[4]={-32*16,1312*16,-32*16,752*16};
  for(int edge=0;edge<4&&!polygon.empty();edge++){
   auto value=[&](const P&p){return edge<2?p.x:p.y;};auto inside=[&](const P&p){return edge%2?value(p)<=limits[edge]:value(p)>=limits[edge];};
   std::vector<P> next;P a=polygon.back();bool ia=inside(a);
   for(const P &b:polygon){bool ib=inside(b);if(ia!=ib){long double t=(limits[edge]-value(a))/(value(b)-value(a));P q={a.x+t*(b.x-a.x),a.y+t*(b.y-a.y),a.z+t*(b.z-a.z),a.u+t*(b.u-a.u),a.v+t*(b.v-a.v)};if(edge<2)q.x=limits[edge];else q.y=limits[edge];next.push_back(q);}if(ib)next.push_back(b);a=b;ia=ib;}polygon.swap(next);
  }
  for(size_t j=1;j+1<polygon.size();j++){gfx_command n=c;n.opcode_flags=(c.opcode_flags&~255U)|GFX_SCREEN_TRIANGLE;P p[3]={polygon[0],polygon[j],polygon[j+1]};
   for(int k=0;k<3;k++){auto round16=[](long double v){return uint32_t(std::max(0LL,std::min(65535LL,std::llround(v))));};
    n.v[k]={int32_t(std::llround(p[k].x)*4096),int32_t(std::llround(p[k].y)*4096),int32_t(round16(p[k].z)),round16(p[k].u)|(round16(p[k].v)<<16)};}out.push_back(n);}
 }
 out.push_back(gfx_command{});size_t expanded=0;for(const auto&c:out)expanded+=(c.opcode_flags&255)==GFX_SPRITE?2:bool(c.opcode_flags&255);
 if(expanded>16384)throw std::runtime_error("clipped frame exceeds triangle capacity; previous frame retained");return out;
}
#endif
