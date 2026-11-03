#pragma once
#include <thread>
#include <mutex>
#include <condition_variable>
#include <functional>
#include <deque>
#include <vector>
#include <atomic>
// A slow preview connection cannot monopolize the control endpoint. Threads and
// queued connections are bounded. Destruction drains and joins before owners die.
class BoundedWorkers {
 std::mutex mutex;std::condition_variable ready;std::deque<std::function<void()>> queue;
 std::vector<std::thread> workers;size_t capacity;bool stopping=false;
 void run(){for(;;){std::function<void()> f;{std::unique_lock<std::mutex>g(mutex);ready.wait(g,[&]{return stopping||!queue.empty();});if(queue.empty()&&stopping)return;f=std::move(queue.front());queue.pop_front();}try{f();}catch(...){errors.fetch_add(1);}}}
public:
 std::atomic<unsigned> errors{0};
 BoundedWorkers(unsigned count,size_t max_pending):capacity(max_pending){try{for(unsigned n=0;n<count;n++)workers.emplace_back([this]{run();});}catch(...){{std::lock_guard<std::mutex>g(mutex);stopping=true;ready.notify_all();}for(auto&t:workers)t.join();throw;}}
 bool submit(std::function<void()> f){std::lock_guard<std::mutex>g(mutex);if(stopping||queue.size()>=capacity)return false;queue.push_back(std::move(f));ready.notify_one();return true;}
 ~BoundedWorkers(){{std::lock_guard<std::mutex>g(mutex);stopping=true;ready.notify_all();}for(auto&t:workers)t.join();}
};
