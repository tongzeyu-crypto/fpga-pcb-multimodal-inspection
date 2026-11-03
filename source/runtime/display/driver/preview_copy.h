#pragma once
#include <memory>
#include <vector>
#include <cstring>
#include <stdexcept>
// Pin only until the preview worker has copied the completed buffer. Encoding
// never owns a display buffer; replacing a pending job releases its pin via RAII.
template<class Buffer> class PreviewCopy {
 std::shared_ptr<Buffer> source;size_t size;
 void release(){if(source){source->jpeg_users.fetch_sub(1);source.reset();}}
public:
 std::vector<unsigned char> pixels;
 PreviewCopy(const std::shared_ptr<Buffer>& b,size_t bytes):source(b),size(bytes){
  if(!b||!bytes)throw std::invalid_argument("empty preview source");
  source->jpeg_users.fetch_add(1);
 }
 PreviewCopy(const PreviewCopy&)=delete;PreviewCopy& operator=(const PreviewCopy&)=delete;
 ~PreviewCopy(){release();}
 void materialize(){
  if(!source)return;
  std::vector<unsigned char> copy(size);
  std::memcpy(copy.data(),source->map,size);pixels.swap(copy);release();
 }
};
