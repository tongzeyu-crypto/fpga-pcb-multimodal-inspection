#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>
int main(int argc,char**argv){int fd=-1;volatile uint32_t*r=nullptr;try{
 if(argc!=3)throw std::runtime_error("usage: pcb_adc /dev/pcb_adc output.u32");fd=open(argv[1],O_RDWR|O_CLOEXEC);if(fd<0)throw std::runtime_error("ADC device absent");r=(volatile uint32_t*)mmap(nullptr,0x20000,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);if(r==MAP_FAILED){r=nullptr;throw std::runtime_error("ADC mmap");}
 if(r[2]!=0x50414431||r[4]!=16384||r[5]!=50000000)throw std::runtime_error("ADC ABI mismatch");if(!(r[1]&8))throw std::runtime_error("ADC clock not locked; capture disabled");if(r[1]&1)throw std::runtime_error("ADC already busy");uint32_t generation=r[3];r[0]=1;__sync_synchronize();auto end=std::chrono::steady_clock::now()+std::chrono::seconds(2);
 while((r[1]&3)!=2){if(std::chrono::steady_clock::now()>end)throw std::runtime_error("ADC timeout; do not reuse stale data");usleep(100);__sync_synchronize();}
 if(r[1]&4||r[3]!=generation+1)throw std::runtime_error("ADC overrun/generation mismatch");std::ofstream f(argv[2],std::ios::binary);for(unsigned i=0;i<16384;i++){uint32_t w=r[0x10000/4+i];f.write((char*)&w,4);}if(!f)throw std::runtime_error("ADC write");std::cout<<"ZYNQ_ADC_AXI_RAW generation="<<r[3]<<" words=16384\n";munmap((void*)r,0x20000);close(fd);return 0;
 }catch(const std::exception&e){if(r)munmap((void*)r,0x20000);if(fd>=0)close(fd);std::cerr<<e.what()<<"\n";return 1;}}
