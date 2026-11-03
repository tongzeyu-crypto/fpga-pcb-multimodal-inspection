/* Raw USB MJPEG acquisition only; pixel algorithms remain in PL. */
#define _POSIX_C_SOURCE 200809L
#include <arpa/inet.h>
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
#define MAX_FRAME_BYTES (32u*1024u*1024u)

static int io(int fd,unsigned long op,void *arg){int r;do{r=ioctl(fd,op,arg);}while(r<0&&errno==EINTR);return r;}
static double clock_s(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec/1e9;}
static int number(const char *s,unsigned *v){char *e;unsigned long n=strtoul(s,&e,10);if(!*s||*e||n>100000)return 0;*v=(unsigned)n;return 1;}
static int jpeg_size(const unsigned char *p,size_t n,unsigned *w,unsigned *h){
    if(n<4||p[0]!=255||p[1]!=216||p[n-2]!=255||p[n-1]!=217)return 0;
    size_t i=2;
    while(i+3<n){
        if(p[i++]!=255)return 0;
        while(i<n&&p[i]==255)i++;
        if(i>=n)return 0;
        unsigned m=p[i++];if(m==218||m==217)return 0;
        if(m==216||m==1||(m>=208&&m<=215))continue;
        if(i+2>n)return 0;
        size_t z=((size_t)p[i]<<8)|p[i+1];if(z<2||z>n-i)return 0;
        if(m>=192&&m<=207&&m!=196&&m!=200&&m!=204){if(z<8)return 0;*h=((unsigned)p[i+3]<<8)|p[i+4];*w=((unsigned)p[i+5]<<8)|p[i+6];return *w&&*h;}
        i+=z;
    }return 0;
}
static void json_string(const unsigned char *s){putchar('"');for(;*s;s++){if(*s=='"'||*s=='\\')putchar('\\');if(*s>=32)putchar(*s);}putchar('"');}
static int list(int fd,int raw){
    struct v4l2_capability c={0};if(io(fd,VIDIOC_QUERYCAP,&c)<0)return 1;
    unsigned caps=(c.capabilities&V4L2_CAP_DEVICE_CAPS)?c.device_caps:c.capabilities;
    printf("{\"card\":");json_string(c.card);printf(",\"bus\":");json_string(c.bus_info);
    printf(",\"capture\":%s,\"modes\":[",(caps&V4L2_CAP_VIDEO_CAPTURE)?"true":"false");
    unsigned first=1;
    struct v4l2_fmtdesc f={0};f.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;
    for(f.index=0;io(fd,VIDIOC_ENUM_FMT,&f)==0;f.index++){
        if(f.pixelformat!=(raw?V4L2_PIX_FMT_YUYV:V4L2_PIX_FMT_MJPEG))continue;
        struct v4l2_frmsizeenum s={0};s.pixel_format=f.pixelformat;
        for(s.index=0;io(fd,VIDIOC_ENUM_FRAMESIZES,&s)==0;s.index++){
            if(s.type!=V4L2_FRMSIZE_TYPE_DISCRETE)continue;
            if(!first)putchar(',');
            first=0;
            printf("{\"width\":%u,\"height\":%u,\"fps\":[",s.discrete.width,s.discrete.height);
            struct v4l2_frmivalenum t={0};t.pixel_format=f.pixelformat;t.width=s.discrete.width;t.height=s.discrete.height;unsigned first_fps=1;
            for(t.index=0;io(fd,VIDIOC_ENUM_FRAMEINTERVALS,&t)==0;t.index++){
                if(t.type!=V4L2_FRMIVAL_TYPE_DISCRETE||!t.discrete.numerator)continue;
                if(!first_fps)putchar(',');
                first_fps=0;
                printf("%.6f",(double)t.discrete.denominator/t.discrete.numerator);
            }printf("]}");
        }
    }printf("]}\n");return 0;
}
static int output(const void *p,size_t n){const unsigned char *b=p;while(n){ssize_t r=write(STDOUT_FILENO,b,n);if(r<0&&errno==EINTR)continue;if(r<=0)return -1;b+=r;n-=(size_t)r;}return 0;}
int main(int argc,char **argv){
    if(argc==3&&(!strcmp(argv[1],"--list")||!strcmp(argv[1],"--list-raw"))){int fd=open(argv[2],O_RDWR|O_NONBLOCK);if(fd<0){perror("open");return 1;}int r=list(fd,!strcmp(argv[1],"--list-raw"));close(fd);return r;}
    int raw=argc==8&&!strcmp(argv[7],"raw");
    if(argc!=7&&!raw){fprintf(stderr,"usage: camera_stream DEVICE WIDTH HEIGHT FPS COUNT DURATION_SECONDS [raw]\nraw preserves YUYV carrier bytes for Tiny1-B dual uint16 planes; no color conversion.\nCOUNT=0 and DURATION=0 mean bounded-memory continuous stream; EOF on stdin stops it.\n");return 2;}
    unsigned width,height,count,duration;char *e;double fps=strtod(argv[4],&e);
    if(!number(argv[2],&width)||!number(argv[3],&height)||!number(argv[5],&count)||!number(argv[6],&duration)||*e||fps<=0||fps>120||width<1||height<1||width>4096||height>4096)return 2;
    struct {void *p;size_t n;} map[4]={{0}};unsigned mapped=0;int streaming=0,rc=1;
    unsigned received=0,good=0,invalid=0,gaps=0,warm_invalid=0,warm_gaps=0,last=0;double start=clock_s(),steady=0;
    int fd=open(argv[1],O_RDWR|O_NONBLOCK);if(fd<0){perror("open");return 1;}
    struct v4l2_capability cap={0};if(io(fd,VIDIOC_QUERYCAP,&cap)<0){perror("QUERYCAP");goto done;}
    unsigned caps=(cap.capabilities&V4L2_CAP_DEVICE_CAPS)?cap.device_caps:cap.capabilities;
    if(!(caps&V4L2_CAP_VIDEO_CAPTURE)||!(caps&V4L2_CAP_STREAMING)){fprintf(stderr,"not a streaming video capture node\n");goto done;}
    struct v4l2_format f={0};f.type=V4L2_BUF_TYPE_VIDEO_CAPTURE;f.fmt.pix.width=width;f.fmt.pix.height=height;f.fmt.pix.pixelformat=raw?V4L2_PIX_FMT_YUYV:V4L2_PIX_FMT_MJPEG;f.fmt.pix.field=V4L2_FIELD_ANY;
    if(io(fd,VIDIOC_S_FMT,&f)<0||f.fmt.pix.pixelformat!=(raw?V4L2_PIX_FMT_YUYV:V4L2_PIX_FMT_MJPEG)){perror("S_FMT");goto done;}
    unsigned stride=f.fmt.pix.bytesperline?f.fmt.pix.bytesperline:f.fmt.pix.width*2;
    if(raw&&(f.fmt.pix.width!=256||f.fmt.pix.height!=384||stride<512||stride>4096)){fprintf(stderr,"Tiny1-B dual format mismatch; no substitution allowed\n");goto done;}
    if(f.fmt.pix.sizeimage>MAX_FRAME_BYTES){fprintf(stderr,"frame buffer exceeds 32 MiB cap\n");goto done;}
    struct v4l2_streamparm parm={0};parm.type=f.type;parm.parm.capture.timeperframe.numerator=1000;parm.parm.capture.timeperframe.denominator=(unsigned)(fps*1000+.5);
    if(io(fd,VIDIOC_S_PARM,&parm)<0)fprintf(stderr,"S_PARM unsupported: %s\n",strerror(errno));
    fprintf(stderr,"CAMERA_START device=%s bus=%s requested=%ux%u negotiated=%ux%u requested_fps=%.3f\n",argv[1],cap.bus_info,width,height,f.fmt.pix.width,f.fmt.pix.height,fps);fflush(stderr);
    struct v4l2_requestbuffers req={0};req.count=count==1?2:4;req.type=f.type;req.memory=V4L2_MEMORY_MMAP;
    if(io(fd,VIDIOC_REQBUFS,&req)<0||req.count<1||req.count>4){perror("REQBUFS");goto done;}
    for(unsigned i=0;i<req.count;i++){
        struct v4l2_buffer b={0};b.type=f.type;b.memory=req.memory;b.index=i;
        if(io(fd,VIDIOC_QUERYBUF,&b)<0){perror("QUERYBUF");goto done;}
        if(b.length>MAX_FRAME_BYTES){fprintf(stderr,"kernel buffer exceeds cap\n");goto done;}
        map[i].n=b.length;map[i].p=mmap(NULL,b.length,PROT_READ|PROT_WRITE,MAP_SHARED,fd,b.m.offset);
        if(map[i].p==MAP_FAILED){map[i].p=NULL;perror("mmap");goto done;}mapped++;
        if(io(fd,VIDIOC_QBUF,&b)<0){perror("QBUF");goto done;}
    }
    size_t pool_bytes=0;for(unsigned i=0;i<mapped;i++){pool_bytes+=map[i].n;}
    fprintf(stderr,"CAMERA_BUFFERS count=%u bytes=%zu\n",mapped,pool_bytes);fflush(stderr);
    enum v4l2_buf_type type=f.type;if(io(fd,VIDIOC_STREAMON,&type)<0){perror("STREAMON");goto done;}streaming=1;
    while(!count||good<count){
        if(duration&&clock_s()-start>=duration){rc=0;break;}
        /* First raw frame may need the approved 30 s cold-start window;
         * subsequent frame gaps retain the 2 s acceptance limit. */
        struct pollfd p[2]={{fd,POLLIN,0},{STDIN_FILENO,POLLIN,0}};int pr=poll(p,2,raw&&!received?30000:2000);
        if(pr<0&&errno==EINTR)continue;
        if(pr<=0){fprintf(stderr,"FRAME_TIMEOUT\n");goto done;}
        if(p[1].revents&(POLLIN|POLLHUP|POLLERR)){rc=0;break;}
        if(p[0].revents&(POLLHUP|POLLERR|POLLNVAL)){fprintf(stderr,"DEVICE_DISCONNECTED\n");goto done;}
        if(!(p[0].revents&POLLIN))continue;
        struct v4l2_buffer b={0};b.type=f.type;b.memory=req.memory;
        if(io(fd,VIDIOC_DQBUF,&b)<0){if(errno==EAGAIN)continue;perror("DQBUF");goto done;}
        if(b.index>=mapped||b.bytesused>map[b.index].n){fprintf(stderr,"INVALID_KERNEL_BUFFER\n");goto done;}
        if(received){uint32_t delta=b.sequence-last;if(delta>1&&delta<0x80000000u){if(received<30)warm_gaps+=delta-1;else gaps+=delta-1;}}
        last=b.sequence;received++;unsigned jw=0,jh=0;
        int valid=!(b.flags&V4L2_BUF_FLAG_ERROR)&&(raw?b.bytesused>=(size_t)stride*f.fmt.pix.height:jpeg_size(map[b.index].p,b.bytesused,&jw,&jh));
        if(!valid){if(received<=30)warm_invalid++;else invalid++;}
        if(received==30)steady=clock_s();
        if((raw||received>30)&&valid){
            char meta[1200];int len=snprintf(meta,sizeof(meta),"{\"source\":\"ZYNQ_USB_REAL\",\"sequence\":%u,\"received\":%u,\"frames\":%u,\"requested_width\":%u,\"requested_height\":%u,\"negotiated_width\":%u,\"negotiated_height\":%u,\"jpeg_width\":%u,\"jpeg_height\":%u,\"bytes\":%u,\"v4l2_timestamp_us\":%lld,\"monotonic_s\":%.6f,\"steady_elapsed_s\":%.6f,\"invalid\":%u,\"sequence_gaps\":%u,\"warm_invalid\":%u,\"warm_sequence_gaps\":%u,\"temperature_matrix_valid\":false}",b.sequence,received,good+1,width,height,f.fmt.pix.width,f.fmt.pix.height,jw,jh,b.bytesused,(long long)b.timestamp.tv_sec*1000000+b.timestamp.tv_usec,clock_s(),steady?clock_s()-steady:0,invalid,gaps,warm_invalid,warm_gaps);
            if(len<0||len>=(int)sizeof(meta))goto done;
            if(raw){
                /* Replace the closing brace only; the transport remains the
                 * original two-length header + JSON + unconverted payload. */
                len--;int extra=snprintf(meta+len,sizeof(meta)-(size_t)len,",\"payload_format\":\"TINY1B_DUAL_U16LE\",\"bytesperline\":%u,\"sizeimage\":%u,\"carrier_fourcc\":\"YUYV\",\"v4l2_timestamp_flags\":%u}",stride,f.fmt.pix.sizeimage,b.flags&V4L2_BUF_FLAG_TIMESTAMP_MASK);
                if(extra<0||extra>=(int)(sizeof(meta)-(size_t)len))goto done;
                len+=extra;
            }
            uint32_t header[2]={htonl((uint32_t)len),htonl(b.bytesused)};
            if(output(header,sizeof(header))||output(meta,(size_t)len)||output(map[b.index].p,b.bytesused))goto done;
            good++;
        }
        if(io(fd,VIDIOC_QBUF,&b)<0){perror("requeue");goto done;}
    }
    if(count&&good==count)rc=0;
done:
    fprintf(stderr,"CAMERA_SUMMARY received=%u frames=%u invalid=%u gaps=%u elapsed_s=%.3f rc=%d\n",received,good,invalid,gaps,clock_s()-start,rc);fflush(stderr);
    if(streaming){enum v4l2_buf_type t=V4L2_BUF_TYPE_VIDEO_CAPTURE;io(fd,VIDIOC_STREAMOFF,&t);}
    for(unsigned i=0;i<mapped;i++)munmap(map[i].p,map[i].n);
    close(fd);return rc;
}
