#pragma once
struct CursorService {
 int fd;Shared &shared;std::atomic<bool> finish{false};std::atomic<int> error{0};std::thread thread;
 CursorService(int f,Shared&s):fd(f),shared(s){if(s.cursor_overlay)thread=std::thread([this]{run();});}
 void run(){uint64_t sent=~uint64_t(0);while(!finish&&alive){
  View v;bool quiet,ready;{std::lock_guard<std::mutex>g(shared.lock);v=shared.target;quiet=shared.quiet_request;ready=shared.have_displayed;}
  // The scanout must own a valid first frame before its cursor is committed.
  if(ready&&!quiet&&sent!=v.cursor_revision){gfx3_cursor c={v.cursor_x,v.cursor_y,uint32_t(v.cursor_visible),0,v.cursor_revision};
   if(!ioctl(fd,GFX3_CURSOR,&c))sent=v.cursor_revision;else if(errno!=EBUSY){error=errno;std::cerr<<"CURSOR_SERVICE_ERROR "<<errno<<std::endl;finish=true;break;}}
  usleep(5000);
 }}
 ~CursorService(){finish=true;if(thread.joinable())thread.join();}
};
