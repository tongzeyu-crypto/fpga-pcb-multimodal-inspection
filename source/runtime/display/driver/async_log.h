#ifndef GFX_ASYNC_LOG_H
#define GFX_ASYNC_LOG_H
#include <thread>
#include <mutex>
#include <condition_variable>
#include <deque>
#include <sstream>
#include <fstream>
#include <atomic>
#include <cstdio>
class AsyncLog {
 std::string path;std::ostringstream draft;std::mutex m;std::condition_variable cv;std::deque<std::string> queue;bool stop=false;std::thread worker;
 void run(){std::ofstream file(path,std::ios::binary|std::ios::app);file.seekp(0,std::ios::end);size_t written=file?size_t(file.tellp()):0;
  for(;;){std::string line;{std::unique_lock<std::mutex>g(m);cv.wait(g,[&]{return stop||!queue.empty();});if(queue.empty()&&stop)break;line.swap(queue.front());queue.pop_front();}
   if(written+line.size()>(64u<<20)){file.close();for(int i=3;i>=1;i--){std::string dst=path+"."+std::to_string(i),src=i==1?path:path+"."+std::to_string(i-1);std::remove(dst.c_str());std::rename(src.c_str(),dst.c_str());}file.open(path,std::ios::binary|std::ios::trunc);written=0;}
   file<<line;file.flush();written+=line.size();if(!file)write_errors++;
  }file.flush();
 }
 public:std::atomic<uint64_t>dropped{0},write_errors{0};
 explicit AsyncLog(const std::string&p):path(p),worker([this]{run();}){}
 template<class T>AsyncLog&operator<<(const T&v){draft<<v;return *this;}
 AsyncLog&operator<<(std::streambuf*b){draft<<b;return *this;}
 void flush(){auto line=draft.str();draft.str("");draft.clear();if(line.empty())return;{std::lock_guard<std::mutex>g(m);if(queue.size()>=512){dropped++;return;}queue.push_back(std::move(line));}cv.notify_one();}
 ~AsyncLog(){flush();{std::lock_guard<std::mutex>g(m);stop=true;}cv.notify_one();worker.join();}
};

// One pending snapshot: slow disks cannot accumulate stale statistics.
class AsyncSnapshot {
 std::string path,pending;std::mutex m;std::condition_variable cv;bool stop=false,have=false;std::thread worker;
 void run(){for(;;){std::string data;{std::unique_lock<std::mutex>g(m);cv.wait(g,[&]{return stop||have;});if(!have&&stop)break;data.swap(pending);have=false;}
  std::string temp=path+".tmp";std::ofstream f(temp,std::ios::binary|std::ios::trunc);f<<data;f.close();
  if(!f||std::rename(temp.c_str(),path.c_str()))write_errors++;
 }}
 public:std::atomic<uint64_t>write_errors{0};
 explicit AsyncSnapshot(const std::string&p):path(p),worker([this]{run();}){}
 void publish(std::string text){{std::lock_guard<std::mutex>g(m);pending=std::move(text);have=true;}cv.notify_one();}
 ~AsyncSnapshot(){{std::lock_guard<std::mutex>g(m);stop=true;}cv.notify_one();worker.join();}
};
#endif

