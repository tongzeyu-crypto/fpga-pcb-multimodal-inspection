#ifndef HDMI_FULL_REFERENCE_H
#define HDMI_FULL_REFERENCE_H
// Offline numerical reference, never an FPGA performance measurement.
// Same command format, fixed point setup, mip layout, premultiplied filtering,
// shared-edge rule and blend arithmetic as the retained ABI-3 reference.
struct FullReferenceTexture {
 bool tiles=false;std::vector<uint32_t> data;struct Level {int w,h;size_t base;};std::vector<Level> levels;
 FullReferenceTexture(){}
 explicit FullReferenceTexture(const std::string &path,int size=2048,bool force_8x4=false){
  tiles=force_8x4||bool(std::ifstream(path.substr(0,path.find_last_of("/\\"))+"/texture-8x4.flag"));
  data=full_read<uint32_t>(path);size_t offset=0;int w=size,h=size;
  for(;;){offset=(offset+31)&~size_t(31);levels.push_back({w,h,offset});offset+=tiles?((w+7)&~7)*((h+3)&~3):((w+1)&~1)*((h+1)&~1);if(w==1&&h==1)break;w=std::max(1,w/2);h=std::max(1,h/2);}
  if(data.size()<offset)throw std::runtime_error("reference texture truncated");
 }
 std::array<int,4> bilinear(int u,int v,int level)const{
  const auto &l=levels[level];int64_t xx=int64_t(u)*(l.w-1),yy=int64_t(v)*(l.h-1);int x=xx>>16,y=yy>>16,ax=(xx>>8)&255,ay=(yy>>8)&255;
  auto texel=[&](int x,int y){size_t q=tiles?((y/4)*((l.w+7)/8)+x/8)*32+((y/2)%2)*16+((x/2)%4)*4+(y%2)*2+x%2:(((y/2)*((l.w+1)/2)+x/2)*4+(y%2)*2+x%2);return data[l.base+q];};
  uint32_t a=texel(x,y),b=texel(std::min(l.w-1,x+1),y),c=texel(x,std::min(l.h-1,y+1)),d=texel(std::min(l.w-1,x+1),std::min(l.h-1,y+1));std::array<int,4> out;
  for(int k=0;k<4;k++){int p=(((a>>(8*k))&255)*(256-ax)+((b>>(8*k))&255)*ax+128)>>8,q=(((c>>(8*k))&255)*(256-ax)+((d>>(8*k))&255)*ax+128)>>8;out[k]=(p*(256-ay)+q*ay+128)>>8;}return out;
 }
};
struct FullReference {
 using I=int64_t;struct V{I x,y,z,u,v;};
 std::vector<uint32_t> pixels;std::vector<uint16_t> depth,ids;uint64_t fragments=0;
 bool transparent_layer=false;std::vector<FullReferenceTexture> textures;
 explicit FullReference(const std::string &root,bool ui_only=false):pixels(1280*720),depth(1280*720),ids(1280*720){
  for(const char *name:{"gray","color","line","thermal","ui"}){if(ui_only&&std::string(name)!="ui")textures.emplace_back();else textures.emplace_back(root+"/"+name+".bin");}
 }
 static I edge(const V &a,const V &b,I x,I y){return (b.x-a.x)*(y-a.y)-(b.y-a.y)*(x-a.x);}
 static bool inclusive(const V &a,const V &b){return b.y<a.y||(b.y==a.y&&b.x>a.x);}
 static int clamp16(I q){return int(std::max<I>(0,std::min<I>(65535,q)));}
 static V transform(const gfx_vertex_word &v,const int32_t *matrix,bool screen){
  V p;p.u=v.uv&65535;p.v=v.uv>>16;
  if(screen){p.x=I(v.x)>>12;p.y=I(v.y)>>12;p.z=uint32_t(v.z)&65535;return p;}
  I q[3];for(int r=0;r<3;r++)q[r]=I(matrix[r*4])*v.x+I(matrix[r*4+1])*v.y+I(matrix[r*4+2])*v.z+I(matrix[r*4+3])*65536;
  p.x=q[0]>>28;p.y=q[1]>>28;p.z=clamp16(q[2]>>16);return p;
 }
 template<class State>void triangle(V p[3],const gfx_command &c,const State &state){
  I area=edge(p[0],p[1],p[2].x,p[2].y);if(!area)return;if(area<0){if(c.opcode_flags&GFX_CULL_BACK)return;std::swap(p[1],p[2]);area=-area;}
  I attr[3][3]={{p[0].z,p[1].z,p[2].z},{p[0].u,p[1].u,p[2].u},{p[0].v,p[1].v,p[2].v}},gx[3],gy[3];
  for(int k=0;k<3;k++){I a=attr[k][1]-attr[k][0],b=attr[k][2]-attr[k][0];gx[k]=(a*(p[2].y-p[0].y)-b*(p[1].y-p[0].y))*4096/area;gy[k]=((p[1].x-p[0].x)*b-(p[2].x-p[0].x)*a)*4096/area;}
  int x0=std::max<I>(0,std::min({p[0].x,p[1].x,p[2].x})>>4),x1=std::min<I>(1279,std::max({p[0].x,p[1].x,p[2].x})>>4);
  int y0=std::max<I>(0,std::min({p[0].y,p[1].y,p[2].y})>>4),y1=std::min<I>(719,std::max({p[0].y,p[1].y,p[2].y})>>4);
  bool sprite=(c.opcode_flags&255)==GFX_SPRITE,textured=c.opcode_flags&GFX_TEXTURED,thermal=c.opcode_flags&GFX_THERMAL;
  int texture=(c.opcode_flags&GFX_GROUND)?4:(state.mode==12?5+state.aoi_variant:state.mode==11?3:state.base),mip=0;
  if(textured&&texture>=int(textures.size()))throw std::runtime_error("AOI display texture unavailable");
  I footprint=std::max({std::abs(gx[1]),std::abs(gy[1]),std::abs(gx[2]),std::abs(gy[2])})*(textured?textures[texture].levels[0].w:2048);
  while(footprint>33554431&&textured&&mip+1<int(textures[texture].levels.size())){footprint>>=1;mip++;}
  bool e0=inclusive(p[1],p[2]),e1=inclusive(p[2],p[0]),e2=inclusive(p[0],p[1]);
  for(int y=y0;y<=y1;y++)for(int x=x0;x<=x1;x++){
   I px=x*16+8,py=y*16+8,a=edge(p[1],p[2],px,py),b=edge(p[2],p[0],px,py),cvalue=edge(p[0],p[1],px,py);
   if(a<0||b<0||cvalue<0||(!a&&!e0)||(!b&&!e1)||(!cvalue&&!e2))continue;
   int index=y*1280+x,z=clamp16((attr[0][0]*256+((gx[0]*(px-p[0].x)+gy[0]*(py-p[0].y))>>4))>>8);if(z>depth[index])continue;fragments++;
   int u=clamp16((attr[1][0]*256+((gx[1]*(px-p[0].x)+gy[1]*(py-p[0].y))>>4))>>8),v=clamp16((attr[2][0]*256+((gx[2]*(px-p[0].x)+gy[2]*(py-p[0].y))>>4))>>8);
   std::array<int,4> src;for(int k=0;k<4;k++)src[k]=(c.argb>>(8*k))&255;
   if(textured&&!sprite){src=textures[texture].bilinear(u,v,mip);if(thermal&&state.heat){auto heat=textures[3].bilinear(u,v,mip);int alpha=(heat[3]*state.heat+127)/255;for(int k=0;k<3;k++)src[k]=(src[k]*(255-alpha)+127)/255+((((heat[k]*state.heat+127)/255)*src[3]+127)/255);}}
   else for(int k=0;k<3;k++)src[k]=(src[k]*src[3]+127)/255;
   if(sprite){I radius=I(u-32768)*(u-32768)+I(v-32768)*(v-32768);int radial=radius>=1073741824?0:255-((radius*255)>>30);for(int k=0;k<4;k++)src[k]=(src[k]*radial+127)/255;}
   if(!src[3])continue;uint32_t old=pixels[index];uint32_t out=transparent_layer?uint32_t(src[3]+((old>>24)*(255-src[3])+127)/255)<<24:0xff000000;for(int k=0;k<3;k++){int dst=(old>>(8*k))&255;out|=uint32_t(std::min(255,src[k]+(sprite?dst:(dst*(255-src[3])+127)/255)))<<(8*k);}pixels[index]=out;
   if(!sprite){depth[index]=z;ids[index]=c.object_id;}
  }
 }
 template<class State>void render(const std::vector<gfx_command> &commands,const int32_t *matrix,const State &state){
  std::fill(pixels.begin(),pixels.end(),transparent_layer?0:0xff0d1722);std::fill(depth.begin(),depth.end(),65535);std::fill(ids.begin(),ids.end(),0);fragments=0;
  for(const auto &c:commands){int op=c.opcode_flags&255;if(op==GFX_END)break;
   if(op==GFX_SPRITE){V center=transform(c.v[0],matrix,false);I dx=I(c.v[1].x)>>13,dy=I(c.v[1].y)>>13;V q[4]={{center.x-dx,center.y-dy,center.z,0,0},{center.x+dx,center.y-dy,center.z,65535,0},{center.x+dx,center.y+dy,center.z,65535,65535},{center.x-dx,center.y+dy,center.z,0,65535}};
    V p[3]={q[0],q[1],q[2]};triangle(p,c,state);V p2[3]={q[0],q[2],q[3]};triangle(p2,c,state);
   }else{V p[3];for(int a=0;a<3;a++)p[a]=transform(c.v[a],matrix,op==GFX_SCREEN_TRIANGLE);triangle(p,c,state);}
  }
 }
};
#endif
