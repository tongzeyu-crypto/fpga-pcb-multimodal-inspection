// Whole-image scheduler for the report's shared PL operators. ARM generates
// addresses/halos; resize, filtering, gradient, normalization and morphology
// arithmetic are executed by PDP3. Missing hardware never selects a CPU path.
#include "pdp_device.hpp"
#include <iostream>
#include <map>
#include <limits>
int main(int argc,char **argv){try{
 if(argc<9||(argc-5)%2)throw std::runtime_error("usage: pl_image OP INPUT.i32 OUTPUT.i32 DEVICE --width W --height H [options]");
 std::string operation=argv[1];std::map<std::string,std::string> options;
 for(int i=5;i<argc;i+=2){std::string k=argv[i];if(options.count(k))throw std::runtime_error("duplicate option");options[k]=argv[i+1];}
 auto number=[&](const std::string&k,int64_t fallback){auto i=options.find(k);if(i==options.end())return fallback;size_t used=0;auto v=std::stoll(i->second,&used);if(used!=i->second.size())throw std::runtime_error("invalid integer");return v;};
 for(const auto &p:options)if(p.first!="--width"&&p.first!="--height"&&p.first!="--out-width"&&p.first!="--out-height"&&p.first!="--normalizer"&&p.first!="--low"&&p.first!="--high"&&p.first!="--threshold"&&p.first!="--kernel"&&p.first!="--second"&&p.first!="--valid")throw std::runtime_error("unknown image option");
 int64_t width=number("--width",0),height=number("--height",0),ow=number("--out-width",width),oh=number("--out-height",height);
 if(width<1||height<1||width>16384||height>16384||ow<1||oh<1||ow>16384||oh>16384||width*height>16*1024*1024||ow*oh>16*1024*1024)throw std::runtime_error("image dimensions");
 auto pixels=pcbpdp::read(argv[2]);if(pixels.size()!=size_t(width*height))throw std::runtime_error("image file shape");
 for(auto p:pixels)if(int32_t(p)<-0x3ffffff||int32_t(p)>0x3ffffff)throw std::runtime_error("image fixed-point bounds");
 std::vector<uint32_t> second,valid;
 unsigned task=0,mode=0,group=1;int kernel=number("--kernel",3);
 if(operation=="resize"){task=6;group=5;}
 else if(operation=="blur"){task=7;group=9;}
 else if(operation=="sobel"){task=7;mode=1;group=9;}
 else if(operation=="erode"||operation=="dilate"){
  if(kernel!=3&&kernel!=5)throw std::runtime_error("morphology kernel");task=7;mode=(kernel==5?4:2)+(operation=="dilate");group=kernel*kernel;
 }else if(operation=="normalize")task=8;
 else if(operation=="difference"){
  task=9;group=3;
  if(!options.count("--second")||!options.count("--valid"))throw std::runtime_error("difference inputs missing");
  second=pcbpdp::read(options["--second"].c_str());valid=pcbpdp::read(options["--valid"].c_str());
  if(second.size()!=pixels.size()||valid.size()!=pixels.size())throw std::runtime_error("difference shape");
  for(auto p:second)if(int32_t(p)<-0x3ffffff||int32_t(p)>0x3ffffff)throw std::runtime_error("difference fixed-point bounds");
 }else if(operation=="color")task=10;else throw std::runtime_error("unknown image operation");
 if(task!=6&&(ow!=width||oh!=height))throw std::runtime_error("only resize changes image dimensions");
 auto denominator=number("--normalizer",1),threshold=number("--threshold",30),low=number("--low",0),high=number("--high",100000);
 if(denominator<1||denominator>0xffffffffLL||threshold<0||threshold>0x7fffffff||low<-0x3ffffff||high>0x3ffffff||high<low)throw std::runtime_error("image parameters");
 pcbpdp::Device device(argv[4]);device.put(96,denominator);device.put(20,threshold);device.put(100,uint32_t(low));device.put(104,uint32_t(high));
 auto reflect=[](int64_t p,int64_t n){if(n==1)return int64_t(0);while(p<0||p>=n)p=p<0?-p:2*n-2-p;return p;};
 std::ofstream output(argv[3],std::ios::binary);if(!output)throw std::runtime_error("image output open");
 size_t total=size_t(ow*oh),batch=4096/group;
 for(size_t begin=0;begin<total;begin+=batch){
  size_t end=std::min(total,begin+batch);std::vector<uint32_t> input;input.reserve((end-begin)*group);
  for(size_t index=begin;index<end;index++){
   int64_t x=index%ow,y=index/ow;
   if(task==6){
    int64_t fx=std::max(int64_t(0),std::min((width-1)*4096,((2*x+1)*width*4096)/(2*ow)-2048));
    int64_t fy=std::max(int64_t(0),std::min((height-1)*4096,((2*y+1)*height*4096)/(2*oh)-2048));
    auto x0=fx>>12,y0=fy>>12,x1=std::min(width-1,x0+1),y1=std::min(height-1,y0+1);
    input.insert(input.end(),{pixels[y0*width+x0],pixels[y0*width+x1],pixels[y1*width+x0],pixels[y1*width+x1],uint32_t((fx&4095)|((fy&4095)<<16))});
   }else if(task==7){
    int radius=(group==25?2:1);
    for(int dy=-radius;dy<=radius;dy++)for(int dx=-radius;dx<=radius;dx++){
     int64_t xx=x+dx,yy=y+dy;
     if(mode>=2&&(xx<0||yy<0||xx>=width||yy>=height))input.push_back(mode&1?0x80000000u:0x7fffffffu);
     else input.push_back(pixels[reflect(yy,height)*width+reflect(xx,width)]);
    }
   }else if(task==9)input.insert(input.end(),{pixels[index],second[index],valid[index]});
   else input.push_back(pixels[index]);
  }
  auto result=device.run(task,input,mode);if(result.size()!=end-begin)throw std::runtime_error("image result length");
  for(auto value:result){uint32_t word=value;output.write((char*)&word,4);}
 }
 output.close();if(!output)throw std::runtime_error("image output write");
 std::cout<<"{\"backend\":\"PDP3 MMIO\",\"operation\":\""<<operation<<"\",\"input_pixels\":"<<pixels.size()<<",\"output_pixels\":"<<total<<",\"jobs\":"<<device.jobs<<",\"generation_start\":"<<device.first_generation<<",\"generation_end\":"<<device.get(52)<<"}\n";return 0;
}catch(const std::exception&e){if(argc>3)unlink(argv[3]);std::cerr<<e.what()<<"\n";return 1;}}
