#ifndef PCB_NATIVE_AI_FRAME_H
#define PCB_NATIVE_AI_FRAME_H
#define PCB_AI_LIBRARY
#include "../../pcb_ai.cpp"
#undef PCB_AI_LIBRARY
#include <memory>
#include <cfenv>
// Full-resolution reprojection + learned pixel fusion. PL task 2 predicts
// 80x45 fusion weights; these weights enter valid reprojected RGB pixels, with the previous complete frame.
struct PreparedNeuralFrame {
 std::vector<uint32_t> warp,previous;std::vector<int8_t> features;std::vector<uint8_t> valid;
 double coverage=0;uint64_t input_pixels=0,fallback_pixels=0;
 uint64_t project_ns=0,feature_ns=0,fallback_ns=0,quantize_ns=0;
};
struct NativeFrameSynth {
 pcbai::Model model;bool offline;double blend_mean=0,coverage=0;uint64_t used_real=0,changed_pixels=0;
 uint64_t project_ns=0,feature_ns=0,fallback_ns=0,quantize_ns=0,infer_ns=0,compose_ns=0;
 uint8_t alpha_table[256]={};double alpha_scale=0;int alpha_rounding=-1;
 static uint64_t stamp(){return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
#ifndef _WIN32
 std::unique_ptr<pcbai::Device> device;
#endif
 explicit NativeFrameSynth(const std::string &path,bool offline_test=false):model(pcbai::parse(pcbai::read_file(path.c_str()))),offline(offline_test){
  if(model.task!=2)throw std::runtime_error("frame model task mismatch");
  std::ifstream purpose_file(path+".kind");std::string purpose;purpose_file>>purpose;
  if(purpose!="NEURAL_PIXEL_FUSION_V1")throw std::runtime_error("neural fusion weights required; legacy confidence model rejected");
  std::ifstream scale_file(path+".scale");if(!(scale_file>>output_scale)||!std::isfinite(output_scale)||output_scale<=0||output_scale>8)throw std::runtime_error("frame output scale missing");
#ifndef _WIN32
  if(!offline)device.reset(new pcbai::Device("/dev/pcb_ai"));
#else
  if(!offline)throw std::runtime_error("PL frame generation requires board Linux");
#endif
 }
 static bool inverse(const double*a,double*b){double d=a[0]*(a[4]*a[8]-a[5]*a[7])-a[1]*(a[3]*a[8]-a[5]*a[6])+a[2]*(a[3]*a[7]-a[4]*a[6]);if(!std::isfinite(d)||std::abs(d)<1e-9)return false;
  b[0]=(a[4]*a[8]-a[5]*a[7])/d;b[1]=(a[2]*a[7]-a[1]*a[8])/d;b[2]=(a[1]*a[5]-a[2]*a[4])/d;
  b[3]=(a[5]*a[6]-a[3]*a[8])/d;b[4]=(a[0]*a[8]-a[2]*a[6])/d;b[5]=(a[2]*a[3]-a[0]*a[5])/d;
  b[6]=(a[3]*a[7]-a[4]*a[6])/d;b[7]=(a[1]*a[6]-a[0]*a[7])/d;b[8]=(a[0]*a[4]-a[1]*a[3])/d;return true;
 }
 std::vector<int8_t> predict(std::vector<int8_t>x){for(const auto&l:model.layers){if(offline)x=pcbai::reference(l,x);
#ifndef _WIN32
  else x=device->run(l,x,2);
#endif
 }return x;}
 static PreparedNeuralFrame prepare(const uint32_t*rgb,const uint16_t*depth,const uint16_t*ids,const int32_t*source,const int32_t*target){
  PreparedNeuralFrame frame;auto &out=frame.warp;auto stage=stamp();
  double a[9],inv[9];for(int r=0;r<3;r++)for(int c=0;c<3;c++)a[r*3+c]=source[r*4+c]/(r<2?65536.:1.);
  if(!inverse(a,inv))throw std::runtime_error("singular source view");out.assign(1280*720,0xff0d1722);std::vector<uint16_t>z(1280*720,65535);
  double fx[3600]={},fy[3600]={},edge[3600]={};unsigned counts[3600]={};uint64_t input_pixels=0,projected=0;
  // Bit rows identify occupied pixels without revisiting the empty background.
  // Each word is traversed from its least significant bit, preserving the
  // original row-major floating-point accumulation and equal-distance ties.
  constexpr unsigned words=1280/32;std::vector<uint32_t> occupied(720*words,0);
  for(int y=0;y<720;y++)for(int x=0;x<1280;x++){
   size_t i=y*1280+x;if(depth[i]==65535||ids[i]>=64000)continue;input_pixels++;
   double p[3]={x+.5-source[3]/65536.,y+.5-source[7]/65536.,double(depth[i])-source[11]},world[3]={};
   for(int r=0;r<3;r++)for(int k=0;k<3;k++)world[r]+=inv[r*3+k]*p[k];
   double q[3]={};for(int r=0;r<3;r++){q[r]=target[r*4+3];for(int k=0;k<3;k++)q[r]+=target[r*4+k]*world[k];if(r<2)q[r]/=65536.;}
   // Nonnegative in-range coordinates truncate exactly like floor. Rejecting
   // out-of-range coordinates first also avoids undefined integer conversion.
   if(!(q[0]>=0&&q[0]<1280&&q[1]>=0&&q[1]<720&&q[2]>=0&&q[2]<65535))continue;
   int u=int(q[0]),v=int(q[1]);projected++;
   size_t j=v*1280+u;if(q[2]<=z[j]){z[j]=uint16_t(q[2]);out[j]=rgb[i];occupied[v*words+unsigned(u)/32]|=uint32_t(1)<<(u&31);}
  }
  frame.project_ns=stamp()-stage;stage=stamp();
  // Derive flow from target-grid pixels by inversely mapping target depth.
  double ta[9],ti[9];for(int r=0;r<3;r++)for(int c=0;c<3;c++)ta[r*3+c]=target[r*4+c]/(r<2?65536.:1.);if(!inverse(ta,ti))throw std::runtime_error("singular target view");
  for(int y=0;y<720;y++)for(unsigned word=0;word<words;word++)for(uint32_t bits=occupied[y*words+word];bits;bits&=bits-1){
   int x=int(word*32+unsigned(__builtin_ctz(bits)));size_t i=y*1280+x;int g=(y/16)*80+x/16;counts[g]++;
   double p[3]={x+.5-target[3]/65536.,y+.5-target[7]/65536.,double(z[i])-target[11]},world[3]={};for(int r=0;r<3;r++)for(int k=0;k<3;k++)world[r]+=ti[r*3+k]*p[k];
   double sx=source[3],sy=source[7];for(int k=0;k<3;k++){sx+=source[k]*world[k];sy+=source[4+k]*world[k];}fx[g]+=x+.5-sx/65536.;fy[g]+=y+.5-sy/65536.;
   double e=0;if(x>0&&z[i-1]!=65535)e=std::max(e,std::abs(double(z[i])-z[i-1]));if(y>0&&z[i-1280]!=65535)e=std::max(e,std::abs(double(z[i])-z[i-1280]));edge[g]+=std::min(1.,e/250.);
  }
  frame.feature_ns=stamp()-stage;stage=stamp();
  // The report specifies the previous complete frame as the second candidate.
  frame.previous.assign(rgb,rgb+1280*720);frame.valid.resize(1280*720);
  for(size_t k=0;k<frame.valid.size();k++){frame.valid[k]=z[k]!=65535;if(!frame.valid[k]){out[k]=frame.previous[k];frame.fallback_pixels++;}}
  frame.fallback_ns=stamp()-stage;stage=stamp();
  auto &features=frame.features;features.resize(4*3600);
  for(int g=0;g<3600;g++){
   auto q=[](double v){return int8_t(std::max(-128,std::min(127,int(std::nearbyint(v*128)))));};double n=std::max(1u,counts[g]);
   features[g]=q(fx[g]/n/32.);features[3600+g]=q(fy[g]/n/32.);
   features[7200+g]=q(edge[g]/n);features[10800+g]=q(counts[g]/256.);
  }
  frame.quantize_ns=stamp()-stage;
  frame.input_pixels=input_pixels;frame.coverage=double(projected)/std::max(uint64_t(1),input_pixels);return frame;
 }
 static std::vector<uint8_t> interpolate_alpha(const std::vector<uint8_t>&alpha){
  if(alpha.size()!=3600)throw std::runtime_error("fusion grid shape");
  std::vector<uint8_t> out(1280*720);
  for(int y=0;y<720;y++){int qy=std::max(0,std::min(44*256,16*y-120)),y0=qy>>8,y1=std::min(44,y0+1),fy=qy&255;
   for(int x=0;x<1280;x++){int qx=std::max(0,std::min(79*256,16*x-120)),x0=qx>>8,x1=std::min(79,x0+1),fx=qx&255;
    unsigned a=alpha[y0*80+x0]*(256-fx)+alpha[y0*80+x1]*fx;
    unsigned b=alpha[y1*80+x0]*(256-fx)+alpha[y1*80+x1]*fx;
    out[y*1280+x]=uint8_t((a*(256-fy)+b*fy+32768)>>16);
   }
  }return out;
 }
 static void compose(const PreparedNeuralFrame &frame,const std::vector<uint8_t>&alpha,std::vector<uint32_t>&out,uint64_t *changed=nullptr){
  if(frame.warp.size()!=1280*720||frame.previous.size()!=frame.warp.size())throw std::runtime_error("neural fusion shape");
  auto expanded=interpolate_alpha(alpha);uint64_t differences=0;out.resize(frame.warp.size());
  for(size_t i=0;i<out.size();i++){
   if(!frame.valid[i]||frame.warp[i]==frame.previous[i]){out[i]=frame.previous[i]|0xff000000u;continue;}
   unsigned a=expanded[i];uint32_t color=0xff000000;
   for(int c=0;c<3;c++){unsigned va=(frame.warp[i]>>(8*c))&255,vb=(frame.previous[i]>>(8*c))&255;color|=((a*va+(255-a)*vb+127)/255)<<(8*c);}
   out[i]=color;differences+=color!=frame.warp[i];
  }if(changed)*changed=differences;
 }
 std::vector<uint8_t> weights(const PreparedNeuralFrame &frame){
  auto begin=stamp();auto logits=predict(frame.features);infer_ns=stamp()-begin;if(logits.size()!=3600)throw std::runtime_error("neural fusion weight shape");
  // Stored logits use the previous-frame basis. Negate that logit so the
  // public alpha is exactly the report's reprojected-candidate weight.
  int rounding=std::fegetround();if(alpha_scale!=output_scale||alpha_rounding!=rounding){for(unsigned i=0;i<256;i++){double value=1/(1+std::exp(std::max(-20.,std::min(20.,int8_t(i)*output_scale))));alpha_table[i]=uint8_t(std::nearbyint(255*value));}alpha_scale=output_scale;alpha_rounding=rounding;}
  std::vector<uint8_t> alpha(3600);blend_mean=0;
  for(int g=0;g<3600;g++){alpha[g]=alpha_table[uint8_t(logits[g])];blend_mean+=alpha[g]/255.;}
  blend_mean/=3600;return alpha;
 }
 // Generated frames are opaque; transparent UI pixels leave their RGB intact.
 static void overlay_ui(std::vector<uint32_t> &pixels,const std::vector<uint32_t> &ui_pixels){
  if(pixels.size()!=ui_pixels.size())throw std::runtime_error("UI overlay dimensions");
  for(size_t i=0;i<pixels.size();i++){uint32_t ui=ui_pixels[i];if(!ui)continue;unsigned a=ui>>24;if(a==255){pixels[i]=ui;continue;}
   uint32_t dst=pixels[i],out=0xff000000;for(int c=0;c<3;c++){unsigned v=((ui>>(8*c))&255)+((((dst>>(8*c))&255)*(255-a)+127)/255);out|=std::min(255u,v)<<(8*c);}pixels[i]=out;
  }
 }
 static void tile_display(const std::vector<uint32_t> &pixels,uint32_t *tiled){
  if(pixels.size()!=1280*720)throw std::runtime_error("display dimensions");
  for(unsigned y=0;y<720;y+=4)for(unsigned x=0;x<1280;x+=8)for(unsigned dy=0;dy<4;dy+=2)for(unsigned dx=0;dx<8;dx+=2){
   const uint32_t *row=pixels.data()+(y+dy)*1280+x+dx;*tiled++=row[0];*tiled++=row[1];*tiled++=row[1280];*tiled++=row[1281];
  }
 }
 bool generate(const uint32_t*rgb,const uint16_t*depth,const uint16_t*ids,const int32_t*source,const int32_t*target,uint64_t real_id,std::vector<uint32_t>&out){
  if(real_id==used_real||std::equal(source,source+12,target))return false;
  auto frame=prepare(rgb,depth,ids,source,target);coverage=frame.coverage;
  project_ns=frame.project_ns;feature_ns=frame.feature_ns;fallback_ns=frame.fallback_ns;quantize_ns=frame.quantize_ns;
  if(frame.input_pixels<1000||coverage<.94)return false;
  auto alpha=weights(frame);auto begin=stamp();compose(frame,alpha,out,&changed_pixels);compose_ns=stamp()-begin;
  used_real=real_id;return true;
 }
 double output_scale=1.;
};
#endif
