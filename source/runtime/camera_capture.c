/* Board USB acquisition. ARM processes raw matrices; neural layers use PL. */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

struct mapped { void *p; size_t n; };
static int xio(int fd, unsigned long req, void *p) {
    int r; do { r=ioctl(fd,req,p); } while(r<0 && errno==EINTR); return r;
}
static double now(void) {struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return t.tv_sec+t.tv_nsec/1e9;}
/* Parse JPEG dimensions without decoding pixels: some firmware advertises swapped dimensions. */
static int jpeg_size(const unsigned char *p,size_t n,unsigned *w,unsigned *h) {
    size_t i=2;
    while(i+3<n){
        if(p[i++]!=0xff)return 0;
        while(i<n && p[i]==0xff)i++;
        if(i>=n)return 0;
        unsigned marker=p[i++];
        if(marker==0xda||marker==0xd9)return 0;
        if(marker==0xd8||marker==0x01||(marker>=0xd0&&marker<=0xd7))continue;
        if(i+2>n)return 0;
        size_t len=((size_t)p[i]<<8)|p[i+1];if(len<2||len>n-i)return 0;
        if(marker>=0xc0&&marker<=0xcf&&marker!=0xc4&&marker!=0xc8&&marker!=0xcc){
            if(len<8)return 0;
            *h=((unsigned)p[i+3]<<8)|p[i+4];*w=((unsigned)p[i+5]<<8)|p[i+6];return *w&&*h;
        }
        i+=len;
    }
    return 0;
}
static int save(const char *path,const void *p,size_t n) {
    FILE *f=fopen(path,"wb"); if(!f)return -1;
    int ok=fwrite(p,1,n,f)==n; if(fclose(f)!=0)ok=0; return ok?0:-1;
}
int main(int argc,char **argv) {
    if(argc!=6) {fprintf(stderr,"usage: camera_capture DEVICE OUTDIR WIDTH HEIGHT COUNT\nCaptures MJPEG, discards first 30 frames. No temperature decoding.\n");return 2;}
    char *end; unsigned long w=strtoul(argv[3],&end,10); if(*end||w<1||w>4096)return 2;
    unsigned long h=strtoul(argv[4],&end,10); if(*end||h<1||h>4096)return 2;
    unsigned long count=strtoul(argv[5],&end,10); if(*end||count<1||count>1000)return 2;
    struct mapped maps[4]={{0}}; unsigned mapped=0,seen=0,saved=0,errors=0,gaps=0,last=0; int streaming=0,rc=1;
    int fd=open(argv[1],O_RDWR|O_NONBLOCK); if(fd<0){perror("open");return 1;}
    struct v4l2_capability cap={0}; if(xio(fd,VIDIOC_QUERYCAP,&cap)<0){perror("QUERYCAP");goto done;}
    uint32_t caps=(cap.capabilities&V4L2_CAP_DEVICE_CAPS)?cap.device_caps:cap.capabilities;
    if(!(caps&V4L2_CAP_VIDEO_CAPTURE)||!(caps&V4L2_CAP_STREAMING)){fprintf(stderr,"not a capture/streaming device\n");goto done;}
    printf("card=%s bus=%s\n",cap.card,cap.bus_info);
    struct v4l2_format fmt={0}; fmt.type=V4L2_BUF_TYPE_VIDEO_CAPTURE; fmt.fmt.pix.width=w;fmt.fmt.pix.height=h;
    fmt.fmt.pix.pixelformat=V4L2_PIX_FMT_MJPEG; fmt.fmt.pix.field=V4L2_FIELD_ANY;
    if(xio(fd,VIDIOC_S_FMT,&fmt)<0){perror("S_FMT");goto done;}
    if(fmt.fmt.pix.pixelformat!=V4L2_PIX_FMT_MJPEG){fprintf(stderr,"device substituted non-MJPEG format\n");goto done;}
    printf("negotiated=%ux%u sizeimage=%u\n",fmt.fmt.pix.width,fmt.fmt.pix.height,fmt.fmt.pix.sizeimage);
    struct v4l2_requestbuffers req={0}; req.count=4;req.type=fmt.type;req.memory=V4L2_MEMORY_MMAP;
    if(xio(fd,VIDIOC_REQBUFS,&req)<0||req.count<1||req.count>4){perror("REQBUFS");goto done;}
    for(unsigned i=0;i<req.count;i++){
        struct v4l2_buffer b={0}; b.type=fmt.type;b.memory=req.memory;b.index=i;
        if(xio(fd,VIDIOC_QUERYBUF,&b)<0){perror("QUERYBUF");goto done;}
        maps[i].n=b.length;maps[i].p=mmap(NULL,b.length,PROT_READ|PROT_WRITE,MAP_SHARED,fd,b.m.offset);
        if(maps[i].p==MAP_FAILED){maps[i].p=NULL;perror("mmap");goto done;} mapped++;
        if(xio(fd,VIDIOC_QBUF,&b)<0){perror("QBUF");goto done;}
    }
    enum v4l2_buf_type type=fmt.type; if(xio(fd,VIDIOC_STREAMON,&type)<0){perror("STREAMON");goto done;} streaming=1;
    double started=now(),measure=0,deadline=started+10+count/5.0;
    while(saved<count && now()<deadline){
        struct pollfd pfd={fd,POLLIN,0}; int pr=poll(&pfd,1,2000);
        if(pr<0&&errno==EINTR)continue;
        if(pr<=0){fprintf(stderr,"frame timeout/poll error\n");goto done;}
        struct v4l2_buffer b={0}; b.type=fmt.type;b.memory=req.memory;
        if(xio(fd,VIDIOC_DQBUF,&b)<0){if(errno==EAGAIN)continue;perror("DQBUF");goto done;}
        if(b.index>=mapped||b.bytesused>maps[b.index].n){fprintf(stderr,"invalid kernel buffer\n");goto done;}
        unsigned char *data=maps[b.index].p;
        if(seen && b.sequence>last+1)gaps+=b.sequence-last-1;
        last=b.sequence;seen++;
        unsigned jpeg_w=0,jpeg_h=0;
        int good=!(b.flags&V4L2_BUF_FLAG_ERROR)&&b.bytesused>=4&&data[0]==0xff&&data[1]==0xd8&&jpeg_size(data,b.bytesused,&jpeg_w,&jpeg_h);
        if(!good)errors++;
        if(seen==30)measure=now();
        if(seen>30&&good){
            char path[1024];int n=snprintf(path,sizeof(path),"%s/frame-%04u.jpg",argv[2],saved);
            if(n<0||n>=(int)sizeof(path)||save(path,data,b.bytesused)<0){perror("save JPEG");goto done;}
            n=snprintf(path,sizeof(path),"%s/frame-%04u.json",argv[2],saved);
            if(n<0||n>=(int)sizeof(path))goto done;
            FILE *meta=fopen(path,"w");if(!meta){perror("save metadata");goto done;}
            fprintf(meta,"{\"source\":\"USB_CAMERA_REAL\",\"driver_sequence\":%u,\"negotiated_width\":%u,\"negotiated_height\":%u,\"jpeg_width\":%u,\"jpeg_height\":%u,\"format\":\"MJPG\",\"bytes\":%u,\"v4l2_timestamp_us\":%lld,\"v4l2_flags\":%u,\"host_monotonic_s\":%.6f,\"temperature_matrix_valid\":false}\n",b.sequence,fmt.fmt.pix.width,fmt.fmt.pix.height,jpeg_w,jpeg_h,b.bytesused,(long long)b.timestamp.tv_sec*1000000+b.timestamp.tv_usec,b.flags,now());
            if(fclose(meta)!=0){perror("metadata close");goto done;}saved++;
        }
        if(xio(fd,VIDIOC_QBUF,&b)<0){perror("requeue");goto done;}
    }
    printf("saved=%u received=%u flagged_or_invalid=%u sequence_gaps=%u steady_elapsed_s=%.3f\n",saved,seen,errors,gaps,measure?now()-measure:0);
    rc=saved==count?0:1;
done:
    if(streaming){enum v4l2_buf_type type=V4L2_BUF_TYPE_VIDEO_CAPTURE;xio(fd,VIDIOC_STREAMOFF,&type);}
    for(unsigned i=0;i<mapped;i++)munmap(maps[i].p,maps[i].n);
    close(fd);return rc;
}
