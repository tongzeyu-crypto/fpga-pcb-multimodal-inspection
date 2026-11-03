#include "src/driver/gfx3_view_matrix.h"
#include "src/driver/full_ai_frame.h"
template<class T>std::vector<T> file(const std::string&p,size_t n){std::ifstream f(p,std::ios::binary);std::vector<T>x(n);f.read((char*)x.data(),n*sizeof(T));if(!f)throw std::runtime_error("frame fixture length");return x;}
int main(int argc,char**argv){try{if(argc!=6)throw std::runtime_error("native_frame_test model.pai source_prefix target_prefix output real_id");
 auto rgb=file<uint32_t>(std::string(argv[2])+".argb",1280*720);auto depth=file<uint16_t>(std::string(argv[2])+".depth.u16",1280*720);auto ids=file<uint16_t>(std::string(argv[2])+".u16",1280*720);auto src=file<int32_t>(std::string(argv[2])+".matrix",12);auto dst=file<int32_t>(std::string(argv[3])+".matrix",12);
 NativeFrameSynth net(argv[1],true);std::vector<uint32_t>pixels;bool accepted=net.generate(rgb.data(),depth.data(),ids.data(),src.data(),dst.data(),std::stoull(argv[5]),pixels);
 std::ofstream f(argv[4],std::ios::binary);f.write((char*)pixels.data(),pixels.size()*4);
 bool repeated=accepted?net.generate(rgb.data(),depth.data(),ids.data(),src.data(),dst.data(),std::stoull(argv[5]),pixels):false;
 if(repeated)throw std::runtime_error("more than one synthesis per real frame");
 std::cout<<"{\"explicit_offline_int8_reference\":true,\"accepted\":"<<(accepted?"true":"false")<<",\"blend_mean\":"<<net.blend_mean<<",\"neural_changed_pixels\":"<<net.changed_pixels<<",\"coverage\":"<<net.coverage<<",\"repeated_insert_rejected\":true}"<<std::endl;return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<std::endl;return 1;}}
