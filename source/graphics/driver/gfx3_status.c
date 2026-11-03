#include "../include/gfx3_uapi.h"
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <stdio.h>
#include <stdint.h>
int main(void){
 int fd=open("/dev/pcb-gfx3",O_RDONLY);struct gfx3_caps c={0};struct gfx3_result r={0};
 if(fd<0||ioctl(fd,GFX3_CAPS,&c)){perror("caps");return 1;}
 printf("CAPS abi=%u tag=%08x last=%u fault=%u allocated=%u kva=%u clock=%u\n",c.abi,c.reserved[0],c.reserved[1],c.faulted,c.allocated_bytes,c.kernel_mapped_bytes,c.clock_hz);
 r.sequence=c.reserved[1];if(!ioctl(fd,GFX3_WAIT,&r)){
  printf("RESULT sequence=%llu error=%d rendered=%u presented=%u submit=%llu done=%llu\n",r.sequence,r.error,r.rendered,r.presented,r.submit_ns,r.render_done_ns);
  for(int i=0;i<GFX3_COUNTER_COUNT;i++)printf("COUNTER %d %llu\n",i,r.counters[i]);
 }else perror("result");close(fd);
 fd=open("/dev/mem",O_RDONLY|O_SYNC);if(fd<0){perror("devmem");return 0;}
 volatile uint32_t *p=mmap(0,4096,PROT_READ,MAP_SHARED,fd,0x43c00000);
 if(p==MAP_FAILED){perror("map registers");close(fd);return 0;}
 unsigned offsets[]={4,8,12,16,20,24,28,32,36,40,44,48,56,64,80,144,148,152,156,504,508};
 for(unsigned i=0;i<sizeof(offsets)/sizeof(offsets[0]);i++)printf("MMIO %03x %08x\n",offsets[i],p[offsets[i]/4]);
 munmap((void*)p,4096);
 p=mmap(0,4096,PROT_READ,MAP_SHARED,fd,0xf8000000);
 if(p!=MAP_FAILED){printf("SLCR TZ_DDR_RAM %08x\n",p[0x430/4]);munmap((void*)p,4096);}else perror("map SLCR read only");
 close(fd);return 0;
}
