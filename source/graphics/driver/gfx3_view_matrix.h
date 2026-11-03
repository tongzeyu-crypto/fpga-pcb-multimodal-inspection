#ifndef GFX3_VIEW_MATRIX_H
#define GFX3_VIEW_MATRIX_H
#include <cmath>
#include <cstdint>
#include <algorithm>
#include <cstddef>
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
#endif
