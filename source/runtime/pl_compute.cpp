// Report execution path: ADC extraction, FFT, PSD scaling and band RMS in PL.
#include "pdp_device.hpp"
#include <iostream>
int main(int argc,char **argv){try{
 if(argc<5||(argc-5)%2)throw std::runtime_error("usage: pl_demo TASK INPUT.u32 OUTPUT.u64 DEVICE [--mode N --length N --frames N --sample-rate N --bands FILE --base N --shift N --threshold MC]");
 unsigned task=std::stoul(argv[1]),mode=task==1?1:0,length=0,frames=1,base=4370,shift=2,fs=50000000;int32_t threshold=40000;std::string bands_file;
 for(int i=5;i<argc;i+=2){std::string key=argv[i];if(key=="--bands"){bands_file=argv[i+1];continue;}size_t used=0;int64_t value=std::stoll(argv[i+1],&used);if(used!=std::string(argv[i+1]).size())throw std::runtime_error("invalid integer");
  if(key=="--threshold"){if(value<INT32_MIN||value>INT32_MAX)throw std::runtime_error("threshold bounds");threshold=value;continue;}
  if(value<0||value>0xffffffffLL)throw std::runtime_error("option bounds");
  if(key=="--mode")mode=value;else if(key=="--length")length=value;else if(key=="--frames")frames=value;else if(key=="--base")base=value;else if(key=="--shift")shift=value;else if(key=="--sample-rate")fs=value;else throw std::runtime_error("unknown compute option");
 }
 auto input=pcbpdp::read(argv[2]);if(task<1||task>4||frames<1||frames>3||!fs||fs>200000000)throw std::runtime_error("task parameters");
 if(!length)length=input.size()/frames;
 if(task==1&&(length<64||length>4096||(length&(length-1))||input.size()!=size_t(length)*frames||mode>1))throw std::runtime_error("FFT frame shape");
 if(task!=1&&(frames!=1||mode>(task==3?2:0)||base>65535||shift>15))throw std::runtime_error("pixel parameters");
 if(task==4&&input.size()!=16384)throw std::runtime_error("one 16384-word ADC frame required");
 for(auto x:input)if((task==1&&(int32_t(x)<-8192||int32_t(x)>8191))||(task==2&&x>65535)||(task==3&&x>(mode==1?65535:0xffffff)))throw std::runtime_error("sample encoding");
 std::vector<std::pair<unsigned,unsigned>> bands;
 if(task==1){
  if(!bands_file.empty()){
   std::ifstream b(bands_file);unsigned lo,hi;if(!b)throw std::runtime_error("bands file missing");while(b>>lo>>hi){if(lo>hi||hi>length/2+1||bands.size()==8)throw std::runtime_error("band bin bounds");bands.emplace_back(lo,hi);}if(!b.eof()||bands.empty())throw std::runtime_error("bands file format");
  }else{
   const uint32_t hz[5][2]={{200000,25000000},{200000,3000000},{3000000,10000000},{10000000,25000000},{450000,550000}};
   for(auto &b:hz)bands.emplace_back(std::min(length/2+1,unsigned((uint64_t(b[0])*length+fs-1)/fs)),std::min(length/2+1,unsigned((uint64_t(b[1])*length+fs-1)/fs)));
  }
 }
 pcbpdp::Device d(argv[4]);d.put(20,threshold);d.put(28,base);d.put(32,shift);d.put(84,fs);
 if(task==1){d.put(88,bands.size());for(unsigned i=0;i<bands.size();i++){d.put(0x100+8*i,bands[i].first);d.put(0x104+8*i,bands[i].second);}}
 std::ofstream output(argv[3],std::ios::binary);if(!output)throw std::runtime_error("output open");
 auto begin=std::chrono::steady_clock::now();
 for(size_t start=0;start<input.size();){
  unsigned n=task==1?length:std::min(size_t(4096),input.size()-start);std::vector<uint32_t> tile(input.begin()+start,input.begin()+start+n);d.put(72,start);
  auto result=d.run(task,tile,task==1?mode|(start?2:0):(task==2||task==4)?(start?2:0):mode);
  start+=n;if(task!=1)for(auto x:result)output.write((char*)&x,8);
 }
 if(task==1){auto result=d.run(5,{},0,length);for(auto x:result)output.write((char*)&x,8);}
 output.close();if(!output)throw std::runtime_error("output write");
 auto elapsed=std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now()-begin).count();
 std::cout<<"{\"backend\":\"PDP3 MMIO\",\"task\":"<<task<<",\"jobs\":"<<d.jobs<<",\"generation_start\":"<<d.first_generation<<",\"generation_end\":"<<d.get(52)<<",\"frames\":"<<(task==1?d.get(60):1)<<",\"length\":"<<length<<",\"input_count\":"<<input.size()<<",\"unit\":\""<<(task==1?"PSD_Q40":"integer")<<"\",\"elapsed_us\":"<<elapsed<<",\"statistics\":{\"min_mc\":"<<int32_t(d.get(36))<<",\"max_mc\":"<<int32_t(d.get(40))<<",\"max_index\":"<<d.get(44)<<",\"hot_count\":"<<d.get(48)<<",\"processed_pixels\":"<<d.get(76)<<"},\"phase_counts\":[";
 for(unsigned i=0;i<4;i++)std::cout<<(i?",":"")<<d.get(112+4*i);
 std::cout<<"],\"bands_rms_q16\":[";for(unsigned i=0;i<bands.size();i++)std::cout<<(i?",":"")<<d.get(0x180+4*i);std::cout<<"],\"band_bins\":[";
 for(unsigned i=0;i<bands.size();i++)std::cout<<(i?",":"")<<"["<<bands[i].first<<","<<bands[i].second<<"]";
 std::cout<<"]}\n";return 0;
}catch(const std::exception&e){if(argc>3)unlink(argv[3]);std::cerr<<e.what()<<"\n";return 1;}}
