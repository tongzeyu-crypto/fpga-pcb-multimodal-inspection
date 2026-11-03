/* PL-independent negative/lifetime tests. Run only with memory_only=1. */
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
#include "../include/gfx3_uapi.h"
#define REQUIRE(x) do{if(!(x)){fprintf(stderr,"contract failure line %d errno %d\n",__LINE__,errno);return 1;}}while(0)
int main(void){
 int fd=open("/dev/pcb-gfx3",O_RDWR);struct gfx3_caps c={0};struct gfx3_bo b={0};
 struct gfx3_seal s={0};uint32_t *p;uint32_t baseline;
 REQUIRE(fd>=0);REQUIRE(!ioctl(fd,GFX3_CAPS,&c)&&c.features==0&&c.abi==3);baseline=c.allocated_bytes;
 b.kind=GFX3_TEXTURE;b.bytes=(uint64_t)GFX3_QUOTA+4096;REQUIRE(ioctl(fd,GFX3_ALLOC,&b)<0);
 b.bytes=4096;b.reserved=1;REQUIRE(ioctl(fd,GFX3_ALLOC,&b)<0);b.reserved=0;b.kind=GFX3_COMMANDS;
 REQUIRE(!ioctl(fd,GFX3_ALLOC,&b));
 p=mmap(0,b.bytes,PROT_READ|PROT_WRITE,MAP_SHARED,fd,(off_t)b.handle*4096);REQUIRE(p!=MAP_FAILED);
 memset(p,0,b.bytes);s.handle=b.handle;s.command_count=2;
 REQUIRE(ioctl(fd,GFX3_SEAL,&s)<0); /* Premature END. */
 p[0]=4;REQUIRE(ioctl(fd,GFX3_SEAL,&s)<0); /* Unsupported command. */
 p[0]=1;p[2]=65536;REQUIRE(ioctl(fd,GFX3_SEAL,&s)<0);
 p[2]=1;p[3]=1;REQUIRE(ioctl(fd,GFX3_SEAL,&s)<0);
 p[3]=0;p[0]=0x80000001;REQUIRE(ioctl(fd,GFX3_SEAL,&s)<0);
 p[0]=1;REQUIRE(!ioctl(fd,GFX3_SEAL,&s)&&s.expanded_triangles==1);
 REQUIRE(!ioctl(fd,GFX3_CAPS,&c)&&c.allocated_bytes==baseline+4096+128);
 p[0]=4;REQUIRE(!ioctl(fd,GFX3_SEAL,&s)&&s.expanded_triangles==1); /* Frozen snapshot reused. */
 REQUIRE(!ioctl(fd,GFX3_CAPS,&c)&&c.allocated_bytes==baseline+4096+128);
 REQUIRE(!ioctl(fd,GFX3_FREE,&b)); /* Mapping holds its own BO lifetime. */
 REQUIRE(p[0]==4);REQUIRE(!ioctl(fd,GFX3_CAPS,&c)&&c.allocated_bytes==baseline+4096+128);
 REQUIRE(!munmap(p,b.bytes));REQUIRE(!ioctl(fd,GFX3_CAPS,&c)&&c.allocated_bytes==baseline);
 REQUIRE(ioctl(fd,GFX3_FREE,&b)<0);
 close(fd);puts("GFX3_CONTRACT_PASS quota invalid_commands immutable_snapshot vma_lifetime no_leak");return 0;
}
