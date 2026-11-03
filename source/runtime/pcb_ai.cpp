// Production defaults to the actual PL device. Offline backend is explicit.
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
#ifndef _WIN32
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>
#endif
namespace pcbai {
using Bytes=std::vector<uint8_t>;
static Bytes read_file(const char*p){std::ifstream f(p,std::ios::binary|std::ios::ate);if(!f)throw std::runtime_error("missing file");auto n=f.tellg();if(n<0||n>1048576)throw std::runtime_error("oversize file");Bytes b(size_t(n),0);f.seekg(0);f.read((char*)b.data(),b.size());if(!f)throw std::runtime_error("short file");return b;}
static uint32_t u32(const Bytes&b,size_t&i){if(i+4>b.size())throw std::runtime_error("truncated model");uint32_t v=uint32_t(b[i])|uint32_t(b[i+1])<<8|uint32_t(b[i+2])<<16|uint32_t(b[i+3])<<24;i+=4;return v;}
static uint32_t fnv(const uint8_t*p,size_t n){uint32_t h=2166136261u;while(n--)h=(h^*p++)*16777619u;return h;}
struct Layer{uint32_t op,ci,co,k,s,p,shift,relu,iw,ih,ow,oh;std::vector<int8_t>w;std::vector<int32_t>b;};
struct Model{uint32_t task,ci,ih,iw;std::vector<Layer>layers;};
static Model parse(const Bytes&raw){size_t pos=0;uint32_t header[10];for(auto&v:header)v=u32(raw,pos);
 if(header[0]!=0x31494150||header[1]!=1||header[2]!=0x20261103||header[3]<1||header[3]>2||header[4]>8||header[4]==0||header[8]!=raw.size()-pos||header[9]!=fnv(raw.data()+pos,raw.size()-pos))throw std::runtime_error("model ABI/length/checksum");
 Model m{header[3],header[5],header[6],header[7],{}};uint32_t ci=m.ci,ih=m.ih,iw=m.iw;
 if((m.task==1&&(ci!=2||ih!=48||iw!=64))||(m.task==2&&(ci!=4||ih!=45||iw!=80)))throw std::runtime_error("task input shape");
 for(uint32_t n=0;n<header[4];n++){uint32_t v[12];for(auto&x:v)x=u32(raw,pos);Layer l{v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11],{}, {}};
  if(l.op>1||l.ci!=ci||l.iw!=iw||l.ih!=ih||!l.co||l.co>32||!l.ow||!l.oh||l.ow*l.oh*l.co>16384||l.shift>31||l.relu>1)throw std::runtime_error("layer bounds");
  if(l.op==1){if(l.iw!=8||l.ih!=6||l.co!=l.ci||l.ow!=1||l.oh!=1)throw std::runtime_error("GAP bounds");}
  else{if((l.k!=1&&l.k!=3)||(l.s!=1&&l.s!=2)||l.p>1||l.ow!=(l.iw+2*l.p-l.k)/l.s+1||l.oh!=(l.ih+2*l.p-l.k)/l.s+1)throw std::runtime_error("convolution shape");size_t size=l.ci*l.co*l.k*l.k;if(size>4096||pos+size+4*l.co>raw.size())throw std::runtime_error("weights bounds");l.w.assign((int8_t*)raw.data()+pos,(int8_t*)raw.data()+pos+size);pos+=size;for(uint32_t j=0;j<l.co;j++)l.b.push_back((int32_t)u32(raw,pos));}
  m.layers.push_back(l);ci=l.co;iw=l.ow;ih=l.oh;
 }if(pos!=raw.size())throw std::runtime_error("trailing model bytes");return m;
}
static std::vector<int8_t> reference(const Layer&l,const std::vector<int8_t>&x){std::vector<int8_t>out(l.co*l.oh*l.ow);
 if(l.op){for(unsigned c=0;c<l.ci;c++){int s=0;for(unsigned i=0;i<48;i++)s+=x[c*48+i];out[c]=s/48;}return out;}
 for(unsigned oc=0;oc<l.co;oc++)for(unsigned oy=0;oy<l.oh;oy++)for(unsigned ox=0;ox<l.ow;ox++){uint32_t acc=(uint32_t)l.b[oc];
  for(unsigned ic=0;ic<l.ci;ic++)for(unsigned ky=0;ky<l.k;ky++)for(unsigned kx=0;kx<l.k;kx++){int yy=int(oy*l.s+ky)-int(l.p),xx=int(ox*l.s+kx)-int(l.p);if(xx>=0&&yy>=0&&xx<(int)l.iw&&yy<(int)l.ih)acc+=int(x[(ic*l.ih+yy)*l.iw+xx])*int(l.w[((oc*l.ci+ic)*l.k+ky)*l.k+kx]);}
  int32_t a;memcpy(&a,&acc,4);int q=a>>l.shift;out[(oc*l.oh+oy)*l.ow+ox]=std::max(l.relu?0:-128,std::min(127,q));
 }return out;
}
#ifndef _WIN32
class Device{int fd;volatile uint32_t*r;public:
 explicit Device(const char*p){fd=open(p,O_RDWR|O_CLOEXEC);if(fd<0)throw std::runtime_error("PL device unavailable");r=(volatile uint32_t*)mmap(nullptr,0x40000,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);if(r==MAP_FAILED){close(fd);throw std::runtime_error("PL mapping failed");}if(rd(8)!=0x50414931||rd(68)!=0x20261103)throw std::runtime_error("PL version mismatch");}
 ~Device(){munmap((void*)r,0x40000);close(fd);}
 void barrier(){__sync_synchronize();}void wr(unsigned a,uint32_t v){r[a/4]=v;barrier();}uint32_t rd(unsigned a){barrier();uint32_t v=r[a/4];barrier();return v;}
 std::vector<int8_t> run(const Layer&l,const std::vector<int8_t>&x,unsigned task){wr(0,2);
  uint32_t vals[]={task,l.iw,l.ih,l.ci,l.co,l.k,l.s,l.p,l.shift,l.relu,l.op,l.ow,l.oh};for(unsigned i=0;i<13;i++)wr(12+i*4,vals[i]);
  for(unsigned i=0;i<x.size();i++)wr(0x10000+4*i,(uint8_t)x[i]);for(unsigned i=0;i<l.w.size();i++)wr(0x30000+4*i,(uint8_t)l.w[i]);for(unsigned i=0;i<l.b.size();i++)wr(0x38000+4*i,(uint32_t)l.b[i]);wr(0,1);
  auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(5);uint32_t status;
  do{status=rd(4);if(std::chrono::steady_clock::now()>deadline){wr(0,2);throw std::runtime_error("PL timeout; task aborted");}if(status&1)usleep(50);}while(status&1);
  if((status&6)!=2)throw std::runtime_error("PL task rejected");std::vector<int8_t>y(l.co*l.oh*l.ow);for(unsigned i=0;i<y.size();i++)y[i]=(int8_t)rd(0x20000+4*i);return y;
 }
};
#endif
} // namespace pcbai
#ifndef PCB_AI_LIBRARY
int main(int argc,char**argv){using namespace pcbai;try{
 if(argc!=6)throw std::runtime_error("usage: pcb_ai --registration|--frame model.pai input.i8 output.i8 /dev/pcb_ai|--offline-test");
 auto m=parse(read_file(argv[2]));unsigned requested=std::string(argv[1])=="--registration"?1:std::string(argv[1])=="--frame"?2:0;if(requested!=m.task)throw std::runtime_error("task/model mismatch");
 auto raw=read_file(argv[3]);if(raw.size()!=m.ci*m.ih*m.iw)throw std::runtime_error("input length");std::vector<int8_t>x((int8_t*)raw.data(),(int8_t*)raw.data()+raw.size());bool offline=std::string(argv[5])=="--offline-test";
#ifndef _WIN32
 Device*dev=offline?nullptr:new Device(argv[5]);
#else
 if(!offline)throw std::runtime_error("production PL runtime requires ARM Linux");
#endif
 for(const auto&l:m.layers){if(offline)x=reference(l,x);
#ifndef _WIN32
 else x=dev->run(l,x,m.task);
#endif
 }
#ifndef _WIN32
 delete dev;
#endif
 std::ofstream f(argv[4],std::ios::binary);f.write((char*)x.data(),x.size());if(!f)throw std::runtime_error("output write");std::cout<<(offline?"OFFLINE_REFERENCE":"PL_COMPUTE")<<" task="<<m.task<<" bytes="<<x.size()<<"\n";return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
#endif
