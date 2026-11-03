#define _FILE_OFFSET_BITS 64
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <errno.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/ioctl.h>
#include "../include/gfx3_uapi.h"
int main(int argc,char **argv)
{
 unsigned mib=argc>1?(unsigned)strtoul(argv[1],NULL,10):16;
 unsigned rounds=argc>2?(unsigned)strtoul(argv[2],NULL,10):3;
 int fd=open("/dev/pcb-gfx3",O_RDWR),rc=1;unsigned n,k;
 struct gfx3_caps caps;struct gfx3_bo bo={0};volatile uint32_t *p=MAP_FAILED;
 if(fd<0){perror("open");return 1;}
 if(!mib||mib>192||!rounds||rounds>100)return 2;
 if(ioctl(fd,GFX3_CAPS,&caps)||caps.abi!=3||caps.faulted){perror("caps");goto done;}
 for(n=0;n<rounds;n++){
  memset(&bo,0,sizeof(bo));bo.kind=GFX3_TEXTURE;bo.bytes=(uint64_t)mib<<20;
  if(ioctl(fd,GFX3_ALLOC,&bo)){perror("alloc");goto done;}
  p=mmap(NULL,bo.bytes,PROT_READ|PROT_WRITE,MAP_SHARED,fd,(off_t)bo.handle*getpagesize());
  if(p==MAP_FAILED){perror("mmap");goto done;}
  for(k=0;k<bo.bytes/4;k++)p[k]=k^0xa53cc35aU^n;
  __sync_synchronize();
  for(k=0;k<bo.bytes/4;k++)if(p[k]!=(k^0xa53cc35aU^n)){
   fprintf(stderr,"mismatch at %u\n",k);goto done;}
  if(ioctl(fd,GFX3_CAPS,&caps))goto done;
  if(caps.kernel_mapped_bytes){fprintf(stderr,"large BO consumed permanent KVA\n");goto done;}
  munmap((void *)p,bo.bytes);p=MAP_FAILED;
  if(ioctl(fd,GFX3_FREE,&bo)){perror("free");goto done;}
  printf("{\"round\":%u,\"bytes_verified\":%llu,\"kernel_mapped_bytes\":%u,\"result\":\"pass\"}\n",
   n+1,(unsigned long long)bo.bytes,caps.kernel_mapped_bytes);fflush(stdout);bo.handle=0;
 }
 if(ioctl(fd,GFX3_CAPS,&caps)||caps.allocated_bytes){fprintf(stderr,"allocation leak\n");goto done;}
 rc=0;
done:
 if(p!=MAP_FAILED)munmap((void *)p,bo.bytes);
 if(bo.handle)ioctl(fd,GFX3_FREE,&bo);
 close(fd);return rc;
}
