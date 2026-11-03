#ifndef PCB_PDP_DEVICE_HPP
#define PCB_PDP_DEVICE_HPP
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>

namespace pcbpdp {
inline std::vector<uint32_t> read(const char *path){
 std::ifstream f(path,std::ios::binary|std::ios::ate);if(!f)throw std::runtime_error("input file missing");auto bytes=f.tellg();
 if(bytes<=0||uint64_t(bytes)>64*1024*1024||uint64_t(bytes)%4)throw std::runtime_error("input file bounds");
 std::vector<uint32_t> out(size_t(bytes)/4);f.seekg(0);f.read((char*)out.data(),bytes);if(!f)throw std::runtime_error("input read failed");return out;
}
class Device {
 int fd=-1;volatile uint32_t *r=nullptr;
public:
 uint32_t jobs=0,first_generation=0;
 explicit Device(const char *path){
  fd=open(path,O_RDWR|O_CLOEXEC);if(fd<0)throw std::runtime_error("PDP3 device missing or owned by another task");
  void *p=mmap(nullptr,65536,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
  if(p==MAP_FAILED){close(fd);fd=-1;throw std::runtime_error("PDP3 mmap failed");}r=(volatile uint32_t*)p;
  if(get(8)!=0x50445033||get(56)!=4096){munmap((void*)r,65536);close(fd);r=nullptr;fd=-1;throw std::runtime_error("PDP3 identity mismatch; matching report implementation required");}
  if(get(4)&1){munmap((void*)r,65536);close(fd);r=nullptr;fd=-1;throw std::runtime_error("PDP3 busy");}
  first_generation=get(52);put(0,2);
 }
 Device(const Device&)=delete;Device&operator=(const Device&)=delete;
 ~Device(){if(r)munmap((void*)r,65536);if(fd>=0)close(fd);}
 void put(unsigned address,uint32_t value){r[address/4]=value;__sync_synchronize();}
 uint32_t get(unsigned address)const{__sync_synchronize();return r[address/4];}
 std::vector<uint64_t> run(unsigned task,const std::vector<uint32_t>&input,unsigned mode=0,unsigned count=0){
  if(input.size()>4096)throw std::runtime_error("PDP tile size");
  auto generation=get(52);put(12,task);put(16,count?count:input.size());put(24,mode);
  for(unsigned i=0;i<input.size();i++)r[0x1000/4+i]=input[i];
  __sync_synchronize();put(0,1);auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(5);
  for(;;){auto status=get(4);if(status&4)throw std::runtime_error("PDP3 error code "+std::to_string(get(128)));
   if(status==2&&get(52)==uint32_t(generation+1))break;
   if(std::chrono::steady_clock::now()>deadline){put(0,2);throw std::runtime_error("PDP3 timeout/stale task");}usleep(100);
  }
  ++jobs;auto n=get(92);if(n>4096)throw std::runtime_error("PDP output bounds");std::vector<uint64_t> out(n);
  for(unsigned i=0;i<n;i++)out[i]=uint64_t(get(0x8000+8*i))|(uint64_t(get(0x8004+8*i))<<32);
  return out;
 }
};
}
#endif
