#ifndef HDMI_FULL_MOUSE_H
#define HDMI_FULL_MOUSE_H
// Raw HID fallback is needed for the retained vendor kernel: it exposes hidraw
// even when a mouse has no evdev listener. Keyboard/absolute reports are rejected.
struct FullHidField {int usage=0,offset=0,bits=0;bool signed_value=false;};
struct FullHid {
 std::map<int,std::vector<FullHidField>> reports;bool ids=false;
 bool parse(const unsigned char *data,size_t n){
  struct Globals {int page=0,size=0,count=0,id=0,minimum=0;}g;std::vector<Globals> stack;
  std::vector<int> usages;int usage_min=-1,usage_max=-1;std::map<int,int> bits;
  for(size_t i=0;i<n;){unsigned p=data[i++];if(p==254){if(i+2>n)return false;size_t count=data[i];i+=2;if(i+count>n)return false;i+=count;continue;}
   int size=p&3;if(size==3)size=4;if(i+size>n)return false;uint32_t value=0;for(int a=0;a<size;a++)value|=uint32_t(data[i++])<<(8*a);
   int32_t signed_value=size==1?int8_t(value):size==2?int16_t(value):int32_t(value);int type=(p>>2)&3,tag=p>>4;
   if(type==1){if(tag==0)g.page=value;else if(tag==1)g.minimum=signed_value;else if(tag==7)g.size=value;else if(tag==8){if(!value||value>255)return false;g.id=value;ids=true;}else if(tag==9)g.count=value;else if(tag==10)stack.push_back(g);else if(tag==11){if(stack.empty())return false;g=stack.back();stack.pop_back();}}
   else if(type==2){if(tag==0)usages.push_back(size==4?int(value):((g.page<<16)|value));if(tag==1)usage_min=value;if(tag==2)usage_max=value;}
   else if(type==0){
    if(tag==8){if(g.size<0||g.size>32||g.count<0||g.count>256)return false;int start=bits[g.id];
     for(int c=0;c<g.count;c++){
      int usage=c<int(usages.size())?usages[c]:usage_min>=0&&usage_min+c<=usage_max?(g.page<<16)|(usage_min+c):-1;
      int page=usage>>16,id=usage&65535;bool button=page==9&&id>=1&&id<=3;bool axis=page==1&&(id==0x30||id==0x31||id==0x38)&&(value&4);
      if(!(value&1)&&(value&2)&&(button||axis))reports[g.id].push_back({button?id:(id==0x30?100:id==0x31?101:102),start+c*g.size,g.size,g.minimum<0});
     }bits[g.id]+=g.size*g.count;
    }usages.clear();usage_min=usage_max=-1;
   }
  }
  for(const auto &r:reports){bool x=false,y=false;for(const auto &f:r.second){x|=f.usage==100;y|=f.usage==101;}if(x&&y)return true;}return false;
 }
 static int extract(const unsigned char *p,size_t n,int offset,int size,bool sign){
  if(size<=0||size>32||offset+size>int(n*8))return 0;uint32_t v=0;for(int b=0;b<size;b++)v|=uint32_t((p[(offset+b)/8]>>((offset+b)%8))&1)<<b;
  if(sign&&size<32&&(v&(1U<<(size-1))))v|=~((1U<<size)-1);return int32_t(v);
 }
 bool decode(const unsigned char *p,size_t n,int &dx,int &dy,int &wheel,int &buttons,bool &has_buttons){
  if(!n)return false;int id=ids?*p++:0;if(ids)n--;auto r=reports.find(id);if(r==reports.end())return false;
  dx=dy=wheel=0;buttons=0;has_buttons=false;bool axis=false;
  for(const auto &f:r->second){if(f.offset+f.bits>int(n*8))return false;int v=extract(p,n,f.offset,f.bits,f.signed_value);
   if(f.usage==100){dx=v;axis=true;}else if(f.usage==101){dy=v;axis=true;}else if(f.usage==102)wheel=v;
   else if(f.usage>=1&&f.usage<=3){if(v)buttons|=1<<(f.usage-1);has_buttons=true;}}
  return axis||has_buttons;
 }
};
struct FullMouseInput {
 Shared &shared;std::string requested;std::thread worker;std::atomic<bool> finish{false};
 FullMouseInput(Shared&s,const std::string&p):shared(s),requested(p){worker=std::thread([this]{run();});}
 static bool bit(const unsigned char *d,int n){return d[n/8]&(1U<<(n%8));}
 int find(bool &raw,FullHid &model,std::string &path){
  for(int pass=0;pass<2;pass++){glob_t g={};std::string pattern=requested=="auto"?(pass?"/dev/hidraw*":"/dev/input/event*"):requested;
   if(glob(pattern.c_str(),0,nullptr,&g))continue;
   for(size_t k=0;k<g.gl_pathc;k++){int fd=open(g.gl_pathv[k],O_RDONLY|O_NONBLOCK|O_CLOEXEC);if(fd<0)continue;bool valid=false;
    if(pass==0){unsigned char rel[(REL_MAX+8)/8]={},keys[(KEY_MAX+8)/8]={};valid=ioctl(fd,EVIOCGBIT(EV_REL,sizeof(rel)),rel)>=0&&ioctl(fd,EVIOCGBIT(EV_KEY,sizeof(keys)),keys)>=0&&bit(rel,REL_X)&&bit(rel,REL_Y)&&bit(keys,BTN_LEFT);}
    else {int bytes=0;hidraw_report_descriptor desc={};FullHid candidate;
     if(ioctl(fd,HIDIOCGRDESCSIZE,&bytes)==0&&bytes>0&&bytes<=HID_MAX_DESCRIPTOR_SIZE){desc.size=bytes;if(ioctl(fd,HIDIOCGRDESC,&desc)==0&&candidate.parse(desc.value,desc.size)){model=candidate;valid=true;}}}
    if(valid){raw=pass!=0;path=g.gl_pathv[k];globfree(&g);return fd;}close(fd);
   }globfree(&g);if(requested!="auto")break;
  }return -1;
 }
 void dispatch(int dx,int dy,int wheel,int buttons,int old){
  std::lock_guard<std::mutex> lock(shared.lock);auto &v=shared.target;
  if(dx||dy){full_input_locked(shared,0,std::max(0,std::min(1279,v.cursor_x+dx)),std::max(0,std::min(719,v.cursor_y+dy)),0);shared.mouse_events++;}
  for(int b=0;b<3;b++)if((buttons^old)&(1<<b)){int gui=b==1?2:b==2?1:0;full_input_locked(shared,(buttons&(1<<b))?1:2,v.cursor_x,v.cursor_y,gui);shared.mouse_events++;}
  if(wheel){full_input_locked(shared,3,v.cursor_x,v.cursor_y,0,wheel);shared.mouse_events++;}
 }
 void run(){if(requested=="none")return;while(!finish&&alive){
  bool raw=false;FullHid model;std::string path;int fd=find(raw,model,path);
  if(fd<0){for(int n=0;n<10&&!finish&&alive;n++)usleep(100000);continue;}
  {std::lock_guard<std::mutex> lock(shared.lock);shared.mouse_device=path;shared.mouse_backend=raw?"hidraw":"evdev";}
  int buttons=0,dx=0,dy=0,wheel=0;bool dropped=false;
  while(!finish&&alive){pollfd p={fd,POLLIN,0};if(poll(&p,1,100)<=0)continue;if(p.revents&(POLLHUP|POLLERR|POLLNVAL))break;
   if(raw){unsigned char bytes[256];ssize_t n=read(fd,bytes,sizeof(bytes));if(n<0&&errno==EAGAIN)continue;if(n<=0)break;int next=buttons;bool has=false;
    if(model.decode(bytes,n,dx,dy,wheel,next,has)){if(!has)next=buttons;dispatch(dx,dy,wheel,next,buttons);buttons=next;}
   }else{input_event batch[64];ssize_t n=read(fd,batch,sizeof(batch));if(n<0&&errno==EAGAIN)continue;if(n<=0||n%sizeof(input_event))break;
    for(size_t event_index=0;event_index<size_t(n)/sizeof(input_event);event_index++){const auto&e=batch[event_index];
    if(e.type==EV_SYN&&e.code==SYN_DROPPED){dropped=true;dx=dy=wheel=0;buttons=0;std::lock_guard<std::mutex>lock(shared.lock);shared.drag.left=shared.drag.right=false;shared.drag.slider=0;continue;}
    if(dropped){if(e.type==EV_SYN&&e.code==SYN_REPORT)dropped=false;continue;}
    if(e.type==EV_REL){if(e.code==REL_X)dx+=e.value;if(e.code==REL_Y)dy+=e.value;if(e.code==REL_WHEEL)wheel+=e.value;}
    if(e.type==EV_KEY){int mask=e.code==BTN_LEFT?1:e.code==BTN_RIGHT?2:e.code==BTN_MIDDLE?4:0;if(mask){int next=e.value?buttons|mask:buttons&~mask;dispatch(dx,dy,wheel,next,buttons);dx=dy=wheel=0;buttons=next;}}
    if(e.type==EV_SYN&&e.code==SYN_REPORT){dispatch(dx,dy,wheel,buttons,buttons);dx=dy=wheel=0;}
    }
   }
  }close(fd);{std::lock_guard<std::mutex>lock(shared.lock);shared.mouse_device.clear();shared.mouse_backend.clear();shared.drag.left=shared.drag.right=false;shared.drag.slider=0;}
 }}
 ~FullMouseInput(){finish=true;worker.join();}
};
#endif
