/* GRBL protocol and motion guards execute on Zynq, not the PC.
 * CH340 USB control definitions checked against Xilinx Linux 5.4 ch341.c.
 * No device firmware, EEPROM parameters, homing or alarm unlock are written. */
#define _DEFAULT_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/usbdevice_fs.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>
#include "grbl_guard.h"

static Guard guard;
static int fd=-1,usb=0,iface=0,ep_in=0,ep_out=0,ep_packet=0,inch=0,ready=0;
static struct usbdevfs_urb input_urb;
static unsigned char input_buffer[512];
static int input_pending=0;
static int init_index=0,waiting=0,motion=0,ack=0,canceled=0;
static unsigned pending_id=0;
static int motion_enabled=0;
static double sent_at=0,last_query=0,target_x=0,target_y=0,deadline=0;
static char error_text[128]="",rxline[1024],cmdline[256];
static size_t rxlen=0,cmdlen=0;static int cmd_drop=0,rx_drop=0;
static double wco_x=0,wco_y=0;static int wco_valid=0;
static double controller_steps_x=-1,controller_steps_y=-1;
static const char *init_cmds[]={"M5","$I","$$","$#","$G"};
static double now_s(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec/1e9;}
static void string_json(const char *s){putchar('"');for(;*s;s++){if(*s=='"'||*s=='\\')putchar('\\');if((unsigned char)*s>=32)putchar(*s);}putchar('"');}
static void state(unsigned id,int ok,const char *error){
    printf("{\"type\":\"state\",\"id\":%u,\"ok\":%s,\"origin_valid\":%s,\"configured\":%s,\"busy\":%s,\"position_valid\":%s,\"status\":",id,ok?"true":"false",guard.origin_valid?"true":"false",guard.configured?"true":"false",guard.busy?"true":"false",guard.position_valid?"true":"false");string_json(guard.status);
    printf(",\"motion_enabled\":%s,\"x\":%.6f,\"y\":%.6f,\"origin_x\":%.6f,\"origin_y\":%.6f,\"local_x\":%.6f,\"local_y\":%.6f,\"position_age_s\":%.3f,\"transport\":\"%s\",\"error\":",motion_enabled?"true":"false",guard.x,guard.y,guard.ox,guard.oy,local_x(&guard),local_y(&guard),guard.position_valid?now_s()-guard.stamp:-1.0,usb?"CH340_USBFS":"TTY");string_json(error?error:"");printf(",\"coordinate_frame\":\"%s\",\"envelope_max_x_mm\":%.6f,\"envelope_max_y_mm\":%.6f,\"controller_units_per_scan_x_mm\":%.12f,\"controller_units_per_scan_y_mm\":%.12f,\"controller_steps_per_mm_x\":%.6f,\"controller_steps_per_mm_y\":%.6f,\"monotonic_s\":%.9f}\n",guard.left_rear_frame==2?"scan_right_rear":(guard.left_rear_frame?"left_rear_right_front":"controller"),envelope_x(&guard),envelope_y(&guard),scale_x(&guard),scale_y(&guard),controller_steps_x,controller_steps_y,now_s());fflush(stdout);
}
static int control(int type,int req,int value,int index,void *data,int n){struct usbdevfs_ctrltransfer c={0};c.bRequestType=type;c.bRequest=req;c.wValue=value;c.wIndex=index;c.wLength=n;c.data=data;c.timeout=1000;return ioctl(fd,USBDEVFS_CONTROL,&c);}
static int send_bytes(const void *p,size_t n){
    if(usb){struct usbdevfs_bulktransfer b={0};b.ep=ep_out;b.len=n;b.data=(void *)p;b.timeout=1000;return ioctl(fd,USBDEVFS_BULK,&b)==(int)n?0:-1;}
    const char *s=p;while(n){ssize_t z=write(fd,s,n);if(z<0&&errno==EINTR)continue;if(z<=0)return -1;s+=z;n-=z;}return 0;
}
static int send_cmd(const char *s){char b[192];int n=snprintf(b,sizeof(b),"%s\n",s);if(n<0||n>=(int)sizeof(b))return -1;fprintf(stderr,"TX %s\n",s);fflush(stderr);return send_bytes(b,(size_t)n);}
static int receive(char *p,size_t n){
    /* Keep a receive URB pending between polls. Synchronous bulk timeouts
     * discarded partially received UART dumps, even for a single packet on
     * this CH340. Reaping the persistent URB exposes actual_length exactly. */
    if(usb){
        if(!input_pending){
            memset(&input_urb,0,sizeof(input_urb));input_urb.type=USBDEVFS_URB_TYPE_BULK;
            input_urb.endpoint=ep_in;input_urb.buffer=input_buffer;
            input_urb.buffer_length=n<(size_t)ep_packet?(int)n:ep_packet;
            if(ioctl(fd,USBDEVFS_SUBMITURB,&input_urb)<0)return -1;
            input_pending=1;
        }
        struct usbdevfs_urb *completed=NULL;
        if(ioctl(fd,USBDEVFS_REAPURBNDELAY,&completed)<0){
            if(errno==EAGAIN){usleep(1000);return 0;}return -1;
        }
        input_pending=0;
        if(completed!=&input_urb||completed->status||completed->actual_length<0||completed->actual_length>(int)n){errno=EIO;return -1;}
        memcpy(p,input_buffer,(size_t)completed->actual_length);return completed->actual_length;
    }
    struct pollfd device={fd,POLLIN,0};poll(&device,1,0);
    if(device.revents&(POLLHUP|POLLERR|POLLNVAL)){errno=ENODEV;return -1;}
    ssize_t r=read(fd,p,n);if(r<0&&(errno==EAGAIN||errno==EWOULDBLOCK))return 0;return (int)r;
}
static int open_transport(const char *path){
    fd=open(path,O_RDWR|O_NONBLOCK);if(fd<0)return -1;
    if(!strncmp(path,"/dev/bus/usb/",13)){
        usb=1;unsigned char d[4096];
        if(control(0x80,6,0x100,0,d,18)!=18||d[8]!=0x86||d[9]!=0x1a||d[10]!=0x23||d[11]!=0x75){errno=ENODEV;return -1;}
        if(control(0x80,6,0x200,0,d,9)!=9)return -1;
        int len=d[2]|(d[3]<<8);if(len<9||len>(int)sizeof(d)){errno=EINVAL;return -1;}
        if(control(0x80,6,0x200,0,d,len)!=len)return -1;
        int active=-1;
        for(int i=0;i+2<=len&&d[i]>=2&&i+d[i]<=len;i+=d[i]){
            if(d[i+1]==4&&d[i]>=9)active=d[i+2];
            if(d[i+1]==5&&d[i]>=7&&(d[i+3]&3)==2){
                if(active!=0){errno=EINVAL;return -1;}
                if(d[i+2]&0x80){ep_in=d[i+2];ep_packet=d[i+4]|(d[i+5]<<8);}else ep_out=d[i+2];
            }
        }
        if(!ep_in||!ep_out||ep_packet<1||ep_packet>512){errno=ENODEV;return -1;}
        if(ioctl(fd,USBDEVFS_CLAIMINTERFACE,&iface)<0)return -1;
        unsigned char version[2];if(control(0xc0,0x5f,0,0,version,2)!=2)return -1;
        if(control(0x40,0xa1,0,0,NULL,0)<0)return -1;
        /* 115200 8N1, RX/TX enabled; DTR/RTS left deasserted. */
        if(control(0x40,0x9a,0x1312,0xcc83,NULL,0)<0||control(0x40,0x9a,0x2518,0xc3,NULL,0)<0||control(0x40,0xa4,0xffff,0,NULL,0)<0)return -1;
        fprintf(stderr,"CH340_VERSION %u.%u bulk_in=%02x bulk_out=%02x\n",version[0],version[1],ep_in,ep_out);
    }else{
        struct termios t;if(tcgetattr(fd,&t)<0)return -1;cfmakeraw(&t);cfsetispeed(&t,B115200);cfsetospeed(&t,B115200);t.c_cflag|=CLOCAL|CREAD;t.c_cflag&=~(HUPCL|CRTSCTS);t.c_cc[VMIN]=0;t.c_cc[VTIME]=0;
        if(tcsetattr(fd,TCSANOW,&t)<0)return -1;
        int bits=0;if(ioctl(fd,TIOCMGET,&bits)==0){bits&=~(TIOCM_DTR|TIOCM_RTS);ioctl(fd,TIOCMSET,&bits);}
    }return 0;
}
static void fail(const char *reason){invalidate(&guard);motion_enabled=0;guard.busy=0;waiting=0;motion=0;snprintf(error_text,sizeof(error_text),"%s",reason);state(pending_id,0,reason);pending_id=0;}
static void handle_status(const char *line){
    const char *separator=strchr(line,'|');if(!separator)separator=strchr(line,'>');if(!separator)return;
    size_t z=(size_t)(separator-line-1);if(z>=sizeof(guard.status))z=sizeof(guard.status)-1;memcpy(guard.status,line+1,z);guard.status[z]=0;
    if(!strncmp(guard.status,"Alarm",5)){fail("controller_alarm");return;}
    double wx,wy,wz;const char *co=strstr(line,"|WCO:");
    if(co&&sscanf(co+5,"%lf,%lf,%lf",&wx,&wy,&wz)==3){if(!isfinite(wx)||!isfinite(wy)||!isfinite(wz)){unsigned char cancel=0x85;send_bytes(&cancel,1);guard.position_valid=0;fail("invalid_coordinate_offset");return;}double scale=inch?25.4:1.0;wx*=scale;wy*=scale;if(wco_valid&&(fabs(wx-wco_x)>.0001||fabs(wy-wco_y)>.0001))invalidate(&guard);wco_x=wx;wco_y=wy;wco_valid=1;}
    const char *pos=strstr(line,"|MPos:");int machine=1;if(!pos){pos=strstr(line,"|WPos:");machine=0;}
    if(pos&&guard.units_known&&sscanf(pos+6,"%lf,%lf,%lf",&wx,&wy,&wz)==3&&(machine||wco_valid)){
        if(!isfinite(wx)||!isfinite(wy)||!isfinite(wz)){unsigned char cancel=0x85;send_bytes(&cancel,1);guard.position_valid=0;fail("invalid_reported_position");return;}
        double scale=inch?25.4:1.0;guard.x=wx*scale+(machine?0:wco_x);guard.y=wy*scale+(machine?0:wco_y);guard.position_valid=isfinite(guard.x)&&isfinite(guard.y);guard.stamp=now_s();
    }
    if(guard.origin_valid&&guard.position_valid&&!inside_envelope(&guard)){unsigned char cancel=0x85;send_bytes(&cancel,1);fail("reported_position_outside_envelope");return;}
    if(motion&&ack&&!strcmp(guard.status,"Idle")&&guard.position_valid&&guard.stamp>=sent_at){
        if(canceled||(fabs(guard.x-target_x)<.05&&fabs(guard.y-target_y)<.05)){guard.busy=0;motion=0;waiting=0;state(pending_id,1,canceled?"jog_canceled":"");pending_id=0;}
    }
    state(0,error_text[0]==0,error_text);
}
static void serial_line(const char *line){
    printf("{\"type\":\"serial\",\"line\":");string_json(line);printf("}\n");fflush(stdout);fprintf(stderr,"RX %s\n",line);fflush(stderr);
    if(!strncmp(line,"Grbl ",5)){fail("controller_reset");guard.configured=0;guard.units_known=0;guard.position_valid=0;wco_valid=0;ready=0;init_index=0;error_text[0]=0;return;}
    if(!strncmp(line,"ALARM:",6)){fail("controller_alarm");return;}
    if(line[0]=='<'){handle_status(line);return;}
    int unit;if(sscanf(line,"$13=%d",&unit)==1){inch=unit!=0;guard.units_known=1;guard.position_valid=0;wco_valid=0;}
    double setting;if(sscanf(line,"$100=%lf",&setting)==1)controller_steps_x=setting;
    if(sscanf(line,"$101=%lf",&setting)==1)controller_steps_y=setting;
    if(!strcmp(line,"ok")){
        if(waiting){waiting=0;if(motion)ack=1;else if(!ready)init_index++;}
        return;
    }
    if(!strncmp(line,"error:",6)){fail(line);if(!ready)init_index=99;return;}
}
static void command_line(const char *line){
    unsigned id;char op[32],extra;if(sscanf(line,"%u %31s",&id,op)!=2)return;
    if((!strcmp(op,"INFO")||!strcmp(op,"CONTINUE")||!strcmp(op,"CANCEL")||!strcmp(op,"PAUSE")||!strcmp(op,"DISARM")||!strcmp(op,"RESET_TEST")||!strcmp(op,"QUIT"))&&sscanf(line,"%u %31s %c",&id,op,&extra)!=2){state(id,0,"unexpected_arguments");return;}
    if(!strcmp(op,"INFO")){state(id,1,error_text);return;}
    if(!strcmp(op,"SCALE")){
        double x,y;if(sscanf(line,"%u %31s %lf %lf %c",&id,op,&x,&y,&extra)!=4||
            !isfinite(x)||!isfinite(y)||x<.01||y<.01||x>10||y>10){state(id,0,"invalid_motion_scale");return;}
        if(guard.origin_valid||guard.busy||motion_enabled||!guard.configured||strcmp(guard.status,"Idle")){
            state(id,0,"scale_change_requires_disarmed_idle");return;
        }
        guard.scale_x=x;guard.scale_y=y;state(id,1,"");return;
    }
    if(!strcmp(op,"LIMITS")){
        double x,y;if(sscanf(line,"%u %31s %lf %lf %c",&id,op,&x,&y,&extra)!=4||
            !isfinite(x)||!isfinite(y)||x<=0||y<=0||x>200||y>200){state(id,0,"invalid_envelope_limits");return;}
        if(guard.origin_valid||guard.busy||motion_enabled||!guard.configured||strcmp(guard.status,"Idle")){
            state(id,0,"limits_change_requires_disarmed_idle");return;
        }
        guard.limit_x=x;guard.limit_y=y;state(id,1,"");return;
    }
    if(!strcmp(op,"FRAME")){
        char frame[32];if(sscanf(line,"%u %31s %31s %c",&id,op,frame,&extra)!=3||
            (strcmp(frame,"LEFT_REAR")&&strcmp(frame,"RIGHT_REAR")&&strcmp(frame,"CONTROLLER"))){state(id,0,"invalid_frame");return;}
        if(guard.origin_valid||guard.busy||motion_enabled||!guard.configured||strcmp(guard.status,"Idle")){
            state(id,0,"frame_change_requires_disarmed_idle");return;
        }
        guard.left_rear_frame=!strcmp(frame,"RIGHT_REAR")?2:!strcmp(frame,"LEFT_REAR");state(id,1,"");return;
    }
    if(!strcmp(op,"ORIGIN")){
        int confirmed;if(sscanf(line,"%u %31s %d %c",&id,op,&confirmed,&extra)!=3){state(id,0,"invalid_origin_request");return;}
        const char *error=arm_origin(&guard,confirmed==1,now_s());if(!error){error_text[0]=0;motion_enabled=1;}state(id,error==NULL,error);return;
    }
    if(!strcmp(op,"CONTINUE")){
        const char *error=check_move(&guard,local_x(&guard),local_y(&guard),60,now_s());
        if(!error){motion_enabled=1;}state(id,error==NULL,error);return;
    }
    if(!strcmp(op,"MOVE")){
        double x,y,feed;if(sscanf(line,"%u %31s %lf %lf %lf %c",&id,op,&x,&y,&feed,&extra)!=5){state(id,0,"invalid_move_request");return;}
        const char *error=check_move(&guard,x,y,feed,now_s());if(error){state(id,0,error);return;}
        if(!motion_enabled){state(id,0,"stopped_requires_explicit_continue");return;}
        double physical_dx=x-local_x(&guard),physical_dy=y-local_y(&guard);
        double sx=x*scale_x(&guard),sy=y*scale_y(&guard);
        target_x=guard.ox+(guard.left_rear_frame==2?sy:(guard.left_rear_frame?-sy:sx));target_y=guard.oy+(guard.left_rear_frame?-sx:sy);double dx=target_x-guard.x,dy=target_y-guard.y;
        if(fabs(dx)<.0001&&fabs(dy)<.0001){state(id,1,"");return;}
        double physical_distance=hypot(physical_dx,physical_dy);
        double controller_feed=feed*hypot(dx,dy)/physical_distance;
        char jog[160];snprintf(jog,sizeof(jog),"$J=G91 G21 X%.5f Y%.5f F%.3f",dx,dy,controller_feed);
        /* Allow acceleration/CoreXY travel overhead; position and status
         * watchdogs remain active. This does not calibrate physical speed. */
        pending_id=id;guard.busy=1;motion=1;waiting=1;ack=0;canceled=0;sent_at=now_s();deadline=sent_at+2*physical_distance/feed*60+10;
        if(send_cmd(jog)<0)fail("serial_write_failed");
        return;
    }
    if(!strcmp(op,"CANCEL")||!strcmp(op,"PAUSE")||!strcmp(op,"DISARM")){
        unsigned char stop=(strcmp(op,"PAUSE")||!strcmp(guard.status,"Jog"))?0x85:'!';
        fprintf(stderr,"TX_REALTIME %02x\n",stop);fflush(stderr);
        if(send_bytes(&stop,1)<0){fail("stop_write_failed");state(id,0,"stop_write_failed");return;}
        if(motion){canceled=1;deadline=now_s()+5;}
        /* A stop latches until an explicit CONTINUE at Idle. Keep the existing
         * work origin for a normal jog stop; resets/alarms still invalidate it. */
        motion_enabled=0;
        if(!strcmp(op,"DISARM")){invalidate(&guard);}
        state(id,1,"");return;
    }
    if(!strcmp(op,"RESET_TEST")){
        if(guard.busy||strcmp(guard.status,"Idle")||!guard.position_valid||now_s()-guard.stamp>1){state(id,0,"reset_requires_fresh_idle");return;}
        unsigned char reset=0x18;invalidate(&guard);motion_enabled=0;guard.configured=guard.units_known=guard.position_valid=0;wco_valid=0;ready=0;init_index=0;waiting=0;
        fprintf(stderr,"TX_REALTIME 18\n");fflush(stderr);
        if(send_bytes(&reset,1)<0){fail("reset_write_failed");state(id,0,"reset_write_failed");return;}
        state(id,1,"");return;
    }
    if(!strcmp(op,"QUIT")){unsigned char stop=0x85;send_bytes(&stop,1);send_cmd("M5");invalidate(&guard);state(id,1,"");exit(0);}
    state(id,0,"unsupported_command");
}
int main(int argc,char **argv){
    if(argc!=2){fprintf(stderr,"usage: grbl_control /dev/ttyUSBn OR /dev/bus/usb/BBB/DDD\n");return 2;}
    signal(SIGPIPE,SIG_IGN);strcpy(guard.status,"Unknown");
    if(open_transport(argv[1])<0){perror("transport");state(0,0,"transport_open_failed");if(fd>=0)close(fd);return 1;}
    double boot_wait=now_s()+1.5;
    for(;;){
        struct pollfd input={STDIN_FILENO,POLLIN,0};poll(&input,1,usb?0:20);
        if(input.revents&(POLLHUP|POLLERR)){unsigned char stop=0x85;send_bytes(&stop,1);invalidate(&guard);break;}
        if(input.revents&POLLIN){char b[128];ssize_t n=read(STDIN_FILENO,b,sizeof(b));if(n<=0)break;for(ssize_t i=0;i<n;i++){if(b[i]=='\n'){if(!cmd_drop){cmdline[cmdlen]=0;command_line(cmdline);}cmdlen=0;cmd_drop=0;}else if(b[i]!='\r'&&!cmd_drop){if(cmdlen+1>=sizeof(cmdline)){fail("command_overflow");cmdlen=0;cmd_drop=1;}else cmdline[cmdlen++]=b[i];}}}
        char b[256];int n=receive(b,sizeof(b));if(n<0){fail("device_disconnected");guard.position_valid=0;state(0,0,"device_disconnected");break;}
        for(int i=0;i<n;i++){if(b[i]=='\n'||b[i]=='\r'){if(rxlen&&!rx_drop){rxline[rxlen]=0;serial_line(rxline);}rxlen=0;rx_drop=0;}else if(!rx_drop&&rxlen+1<sizeof(rxline))rxline[rxlen++]=b[i];else if(!rx_drop){rxlen=0;rx_drop=1;fail("serial_line_overflow");}}
        double now=now_s();
        if((ready||!waiting)&&now-last_query>.2){char q='?';if(send_bytes(&q,1)<0){fail("status_query_failed");break;}last_query=now;}
        if(!ready&&!waiting&&now>boot_wait&&init_index<5){if(send_cmd(init_cmds[init_index])<0){fail("initialization_write_failed");break;}waiting=1;sent_at=now;}
        if(!ready&&init_index==5){ready=1;guard.configured=guard.units_known;error_text[0]=0;state(0,1,"");}
        if(waiting&&!motion&&now-sent_at>4){fail("initialization_timeout");init_index=99;}
        if(motion&&now>deadline){unsigned char stop=0x85;send_bytes(&stop,1);fail("motion_timeout");}
        if(guard.origin_valid&&now-guard.stamp>1){unsigned char stop=0x85;send_bytes(&stop,1);fail("position_stale");}
    }
    if(usb)ioctl(fd,USBDEVFS_RELEASEINTERFACE,&iface);
    close(fd);return 1;
}
