#ifndef PCB_NATIVE_AI_FRAME_H
#define PCB_NATIVE_AI_FRAME_H
#define PCB_AI_LIBRARY
#include "../../pcb_ai.cpp"
#undef PCB_AI_LIBRARY
#include <memory>
// Full-resolution reprojection + learned pixel fusion. PL task 2 predicts
// 80x45 fusion weights; these weights enter every repaired RGB pixel.
struct PreparedNeuralFrame {
 std::vector<uint32_t> warp,repair;std::vector<int8_t> features;
 double coverage=0;uint64_t input_pixels=0,repair_pixels=0;
};
struct NativeFrameSynth {
 pcbai::Model model;bool offline;double blend_mean=0,coverage=0;uint64_t used_real=0,changed_pixels=0;
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
  PreparedNeuralFrame frame;auto &out=frame.warp;
  double a[9],inv[9];for(int r=0;r<3;r++)for(int c=0;c<3;c++)a[r*3+c]=source[r*4+c]/(r<2?65536.:1.);
  if(!inverse(a,inv))throw std::runtime_error("singular source view");out.assign(1280*720,0xff0d1722);std::vector<uint16_t>z(1280*720,65535);
  double fx[3600]={},fy[3600]={},edge[3600]={};unsigned counts[3600]={};uint64_t input_pixels=0,projected=0;
  for(int y=0;y<720;y++)for(int x=0;x<1280;x++){
   size_t i=y*1280+x;if(depth[i]==65535||ids[i]>=64000)continue;input_pixels++;
   double p[3]={x+.5-source[3]/65536.,y+.5-source[7]/65536.,double(depth[i])-source[11]},world[3]={};
   for(int r=0;r<3;r++)for(int k=0;k<3;k++)world[r]+=inv[r*3+k]*p[k];
   double q[3]={};for(int r=0;r<3;r++){q[r]=target[r*4+3];for(int k=0;k<3;k++)q[r]+=target[r*4+k]*world[k];if(r<2)q[r]/=65536.;}
   int u=int(std::floor(q[0])),v=int(std::floor(q[1]));if(u<0||u>=1280||v<0||v>=720||q[2]<0||q[2]>=65535)continue;projected++;
   size_t j=v*1280+u;if(q[2]<=z[j]){z[j]=uint16_t(q[2]);out[j]=rgb[i];}
  }
  // Derive flow from target-grid pixels by inversely mapping target depth.
  double ta[9],ti[9];for(int r=0;r<3;r++)for(int c=0;c<3;c++)ta[r*3+c]=target[r*4+c]/(r<2?65536.:1.);if(!inverse(ta,ti))throw std::runtime_error("singular target view");
  for(int y=0;y<720;y++)for(int x=0;x<1280;x++){
   size_t i=y*1280+x;if(z[i]==65535)continue;int g=(y/16)*80+x/16;counts[g]++;
   double p[3]={x+.5-target[3]/65536.,y+.5-target[7]/65536.,double(z[i])-target[11]},world[3]={};for(int r=0;r<3;r++)for(int k=0;k<3;k++)world[r]+=ti[r*3+k]*p[k];
   double sx=source[3],sy=source[7];for(int k=0;k<3;k++){sx+=source[k]*world[k];sy+=source[4+k]*world[k];}fx[g]+=x+.5-sx/65536.;fy[g]+=y+.5-sy/65536.;
   double e=0;if(x>0&&z[i-1]!=65535)e=std::max(e,std::abs(double(z[i])-z[i-1]));if(y>0&&z[i-1280]!=65535)e=std::max(e,std::abs(double(z[i])-z[i-1280]));edge[g]+=std::min(1.,e/250.);
  }
  // Candidate B repairs only small holes from neighbouring projected geometry.
  // It does not read the target RGB or target depth. The CNN learns how much
  // of B to mix into A, from RGB reconstruction supervision, not good/bad labels.
  frame.repair=out;double difference[3600]={};
  for(int y=0;y<720;y++)for(int x=0;x<1280;x++){
   size_t i=y*1280+x;if(z[i]!=65535)continue;int best=100;size_t selected=i;
   for(int dy=-2;dy<=2;dy++)for(int dx=-2;dx<=2;dx++){
    int xx=x+dx,yy=y+dy,d=dx*dx+dy*dy;if(xx<0||xx>=1280||yy<0||yy>=720||d>=best)continue;
    size_t j=yy*1280+xx;if(z[j]!=65535){best=d;selected=j;}
   }
   if(selected!=i){frame.repair[i]=out[selected];if(frame.repair[i]!=out[i]){
     frame.repair_pixels++;double delta=0;for(int c=0;c<3;c++)delta+=std::abs(int((frame.repair[i]>>(8*c))&255)-int((out[i]>>(8*c))&255));
     difference[(y/16)*80+x/16]+=delta/(3.*255.);
   }}
  }
  auto &features=frame.features;features.resize(4*3600);for(int g=0;g<3600;g++){
   auto q=[](double v){return int8_t(std::max(-128,std::min(127,int(std::nearbyint(v*128)))));};double n=std::max(1u,counts[g]);
   features[g]=q(1.-counts[g]/256.);features[3600+g]=q(edge[g]/256.);
   features[7200+g]=q(difference[g]/256.);features[10800+g]=q(std::hypot(fx[g]/n,fy[g]/n)/32.);
  }
  frame.input_pixels=input_pixels;frame.coverage=double(projected)/std::max(uint64_t(1),input_pixels);return frame;
 }
 static void compose(const PreparedNeuralFrame &frame,const std::vector<uint8_t>&alpha,std::vector<uint32_t>&out){
  if(alpha.size()!=3600||frame.warp.size()!=1280*720||frame.repair.size()!=frame.warp.size())throw std::runtime_error("neural fusion shape");
  out.resize(frame.warp.size());for(int y=0;y<720;y++)for(int x=0;x<1280;x++){
   size_t i=y*1280+x;unsigned a=alpha[(y/16)*80+x/16];uint32_t color=0xff000000;
   for(int c=0;c<3;c++){unsigned va=(frame.warp[i]>>(8*c))&255,vb=(frame.repair[i]>>(8*c))&255;color|=(((255-a)*va+a*vb+127)/255)<<(8*c);}out[i]=color;
  }
 }
 std::vector<uint8_t> weights(const PreparedNeuralFrame &frame){
  auto logits=predict(frame.features);if(logits.size()!=3600)throw std::runtime_error("neural fusion weight shape");
  std::vector<uint8_t> alpha(3600);blend_mean=0;
  for(int g=0;g<3600;g++){double value=1/(1+std::exp(-std::max(-20.,std::min(20.,logits[g]*output_scale))));alpha[g]=uint8_t(std::nearbyint(255*value));blend_mean+=alpha[g]/255.;}
  blend_mean/=3600;return alpha;
 }
 bool generate(const uint32_t*rgb,const uint16_t*depth,const uint16_t*ids,const int32_t*source,const int32_t*target,uint64_t real_id,std::vector<uint32_t>&out){
  if(real_id==used_real||std::equal(source,source+12,target))return false;
  auto frame=prepare(rgb,depth,ids,source,target);coverage=frame.coverage;
  if(frame.input_pixels<1000||coverage<.94)return false;
  compose(frame,weights(frame),out);changed_pixels=0;for(size_t i=0;i<out.size();i++)if(out[i]!=frame.warp[i])changed_pixels++;
  used_real=real_id;return true;
 }
 double output_scale=1.;
};
#endif
