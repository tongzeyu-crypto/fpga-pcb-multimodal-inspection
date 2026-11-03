#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <vector>
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>
static uint64_t now_ns(){return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
static std::string quoted(const std::string&s){std::ostringstream o;o<<'"';for(char c:s){if(c=='"'||c=='\\')o<<'\\';o<<c;}o<<'"';return o.str();}
int main(int argc,char**argv){int fd=-1;volatile uint32_t*r=nullptr;std::vector<std::string> paths;try{
 if(argc!=3&&argc!=5)throw std::runtime_error("usage: pcb_adc DEVICE OUTPUT [--frames 3]");unsigned count=1;
 if(argc==5){if(std::string(argv[3])!="--frames")throw std::runtime_error("unknown ADC option");count=std::stoul(argv[4]);if(count<1||count>3)throw std::runtime_error("ADC frame batch bounds");}
 fd=open(argv[1],O_RDWR|O_CLOEXEC);if(fd<0)throw std::runtime_error("ADC device absent");void *mapped=mmap(nullptr,0x20000,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);if(mapped==MAP_FAILED)throw std::runtime_error("ADC mmap");r=(volatile uint32_t*)mapped;
 auto rd=[&](unsigned index){__sync_synchronize();return r[index];};auto wr=[&](unsigned index,uint32_t value){r[index]=value;__sync_synchronize();};
 if(rd(2)!=0x50414432||rd(4)!=16384||rd(5)!=50000000||rd(6)!=2)throw std::runtime_error("ADC ping-pong ABI mismatch");
 if(!(rd(1)&8))throw std::runtime_error("ADC clock not locked");if(rd(1)&17)throw std::runtime_error("ADC already active");
 wr(9,3);usleep(100);if(rd(7))throw std::runtime_error("old ADC frame ownership not released");
 uint32_t previous=rd(3);wr(10,count>1);uint64_t trigger=now_ns();wr(0,1);std::ostringstream frames;
 for(unsigned frame=0;frame<count;frame++){
  auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(2);uint32_t ready;
  while(!(ready=rd(7))){if(rd(1)&4)throw std::runtime_error("ADC overrun");if(std::chrono::steady_clock::now()>deadline)throw std::runtime_error("ADC timeout; stale frames are not accepted");usleep(100);}
  unsigned bank=(ready&1)?0:1;if(ready==3&&int32_t(rd(12)-rd(11))<0)bank=1;
  uint32_t generation=rd(11+bank);if(generation!=uint32_t(previous+1))throw std::runtime_error("ADC frame sequence gap");previous=generation;
  unsigned offset=13+bank*4;uint64_t tick_begin=uint64_t(rd(offset))|(uint64_t(rd(offset+1))<<32),tick_end=uint64_t(rd(offset+2))|(uint64_t(rd(offset+3))<<32);
  if(tick_end-tick_begin!=16383)throw std::runtime_error("ADC sample tick interval mismatch");
  uint64_t observed=now_ns();wr(8,bank);std::string path=argc==3?std::string(argv[2]):std::string(argv[2])+"-"+std::to_string(frame)+".u32";paths.push_back(path);
  std::ofstream out(path,std::ios::binary);if(!out)throw std::runtime_error("ADC output open");for(unsigned i=0;i<16384;i++){uint32_t word=rd(0x10000/4+i);out.write((char*)&word,4);}out.close();if(!out)throw std::runtime_error("ADC output write");
  if(!(rd(7)&(1u<<bank))||rd(11+bank)!=generation)throw std::runtime_error("ADC owned bank changed during read");
  wr(9,1u<<bank);
  if(frame)frames<<',';frames<<"{\"file\":"<<quoted(path)<<",\"frame_index\":"<<frame<<",\"bank\":"<<bank<<",\"generation\":"<<generation<<",\"sample_tick_begin\":"<<tick_begin<<",\"sample_tick_end\":"<<tick_end<<",\"sample_clock_hz\":200000000,\"ready_observed_ns\":"<<observed<<",\"copy_done_ns\":"<<now_ns()<<"}";
 }
 wr(0,2);auto stop_deadline=std::chrono::steady_clock::now()+std::chrono::seconds(1);while(rd(1)&16){if(std::chrono::steady_clock::now()>stop_deadline)throw std::runtime_error("ADC stop acknowledgement timeout");usleep(100);}wr(9,3);wr(10,0);
 std::cout<<"{\"backend\":\"ADC_PINGPONG_V2\",\"trigger_ns\":"<<trigger<<",\"frames\":["<<frames.str()<<"],\"banks\":2}\n";munmap((void*)r,0x20000);close(fd);return 0;
 }catch(const std::exception&e){if(r){r[0]=2;__sync_synchronize();munmap((void*)r,0x20000);}if(fd>=0)close(fd);for(auto &path:paths)unlink(path.c_str());std::cerr<<e.what()<<"\n";return 1;}}
