#include <sstream>
#include "src/driver/gfx3_view_matrix.h"
#include "src/driver/full_ai_frame.h"

template<class T>std::vector<T> read_plane(const std::string&p,size_t n){std::ifstream f(p,std::ios::binary);std::vector<T>x(n);f.read(reinterpret_cast<char*>(x.data()),n*sizeof(T));if(!f)throw std::runtime_error("frame plane length: "+p);return x;}
template<class T>void write_plane(const std::string&p,const std::vector<T>&x){std::ofstream f(p,std::ios::binary);f.write(reinterpret_cast<const char*>(x.data()),x.size()*sizeof(T));if(!f)throw std::runtime_error("frame output write");}
int main(int argc,char**argv){try{
 if(argc!=5&&argc!=6)throw std::runtime_error("prepare SOURCE TARGET OUTPUT | generate MODEL SOURCE TARGET OUTPUT");
 bool generate=std::string(argv[1])=="generate";if(!generate&&std::string(argv[1])!="prepare")throw std::runtime_error("invalid operation");
 if(argc!=(generate?6:5))throw std::runtime_error("invalid argument count");
 std::string source=argv[generate?3:2],target=argv[generate?4:3],output=argv[generate?5:4];
 auto rgb=read_plane<uint32_t>(source+".argb",1280*720);auto depth=read_plane<uint16_t>(source+".depth.u16",1280*720);auto ids=read_plane<uint16_t>(source+".u16",1280*720);
 auto src=read_plane<int32_t>(source+".matrix",12),dst=read_plane<int32_t>(target+".matrix",12);
 auto frame=NativeFrameSynth::prepare(rgb.data(),depth.data(),ids.data(),src.data(),dst.data());
 write_plane(output+".warp.argb",frame.warp);write_plane(output+".repair.argb",frame.repair);write_plane(output+".features.i8",frame.features);
 std::ostringstream report;report<<"{\"coverage\":"<<frame.coverage<<",\"input_pixels\":"<<frame.input_pixels<<",\"repair_pixels\":"<<frame.repair_pixels;
 if(generate){
  NativeFrameSynth net(argv[2],true);auto alpha=net.weights(frame);std::vector<uint32_t>pixels,disabled,all_repair;
  write_plane(output+".logits.i8",net.predict(frame.features));
  NativeFrameSynth::compose(frame,alpha,pixels);NativeFrameSynth::compose(frame,std::vector<uint8_t>(3600,0),disabled);NativeFrameSynth::compose(frame,std::vector<uint8_t>(3600,255),all_repair);
  if(disabled!=frame.warp||all_repair!=frame.repair)throw std::runtime_error("fusion endpoint regression");
  uint64_t changed=0,soft=0;for(size_t i=0;i<pixels.size();i++){if(pixels[i]!=frame.warp[i])changed++;if(pixels[i]!=frame.warp[i]&&pixels[i]!=frame.repair[i])soft++;}
  write_plane(output+".neural.argb",pixels);write_plane(output+".alpha.u8",alpha);
  report<<",\"network_participated\":"<<(changed?"true":"false")<<",\"neural_changed_pixels\":"<<changed<<",\"soft_blended_pixels\":"<<soft<<",\"blend_mean\":"<<net.blend_mean<<",\"explicit_offline_int8\":true";
 }
 report<<"}";std::ofstream metadata(output+".json");metadata<<report.str()<<'\n';std::cout<<report.str()<<std::endl;return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<std::endl;return 1;}}
