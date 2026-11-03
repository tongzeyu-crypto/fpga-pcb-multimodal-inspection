// Optional ARM MMIO client for the independent PDP1 demo IP. Never run by replay.
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>
int main(int argc,char **argv){int fd=-1;volatile uint32_t *r=nullptr;try{
 if(argc<5)throw std::runtime_error("usage: pl_demo TASK INPUT.u32 OUTPUT.u32 MMIO_DEVICE [MODE]");
 unsigned task=std::stoul(argv[1]);std::ifstream input(argv[2],std::ios::binary);if(!input)throw std::runtime_error("input missing");
 std::vector<uint32_t> values;uint32_t value;while(input.read((char*)&value,4))values.push_back(value);
 if(input.gcount()!=0||!input.eof()||values.empty()||values.size()>256||task<1||task>3||(task==1&&values.size()!=64))throw std::runtime_error("task/input bounds");
 fd=open(argv[4],O_RDWR|O_CLOEXEC);if(fd<0)throw std::runtime_error("explicit demo MMIO device unavailable");
 r=(volatile uint32_t*)mmap(nullptr,0x3000,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);if(r==MAP_FAILED){r=nullptr;throw std::runtime_error("mmap failed");}
 if(r[2]!=0x50445031)throw std::runtime_error("PDP1 demo IP absent; prior combined bitstream does not contain it");
 if(r[1]&1)throw std::runtime_error("demo IP already busy");
 uint32_t generation=r[13];r[0]=2;
 r[3]=task;r[4]=values.size();r[5]=40000;r[6]=argc>5?std::stoul(argv[5]):0;r[7]=4370;r[8]=2;
 for(size_t i=0;i<values.size();++i)r[0x1000/4+i]=values[i];
 __sync_synchronize();r[0]=1;
 auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(2);
 while(r[1]&1){if(std::chrono::steady_clock::now()>deadline){r[0]=2;throw std::runtime_error("demo IP timeout");}usleep(100);__sync_synchronize();}
 if(r[1]!=2||r[13]!=generation+1)throw std::runtime_error("demo IP error/stale completion");
 std::ofstream output(argv[3],std::ios::binary);unsigned n=task==1?33:values.size();
 for(unsigned i=0;i<n;++i){value=r[0x2000/4+i];output.write((char*)&value,4);}if(!output)throw std::runtime_error("output write failed");
 std::cout<<"PDP1 task="<<task<<" words="<<n<<" generation="<<r[13]<<" min_mc="<<(int32_t)r[9]<<" max_mc="<<(int32_t)r[10]<<" max_index="<<r[11]<<" hot_count="<<r[12]<<"\n";
 munmap((void*)r,0x3000);close(fd);return 0;
 }catch(const std::exception&error){if(r)munmap((void*)r,0x3000);if(fd>=0)close(fd);std::cerr<<error.what()<<"\n";return 1;}}
