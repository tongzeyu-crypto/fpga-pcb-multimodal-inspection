/* ABI 3: typed BOs, no large permanent kernel mappings, ordered async jobs.
 * Never unload while scanout/AXI owns a buffer. A fault pins the module.
 */
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/of.h>
#include <linux/io.h>
#include <linux/interrupt.h>
#include <linux/miscdevice.h>
#include <linux/dma-mapping.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/mutex.h>
#include <linux/clk.h>
#include <linux/mm.h>
#include <linux/idr.h>
#include <linux/refcount.h>
#include <linux/workqueue.h>
#include <linux/completion.h>
#include <linux/poll.h>
#include <linux/ktime.h>
#include <linux/swap.h>
#include <linux/delay.h>
#include "../include/gfx3_protocol.h"
#define HISTORY 64
#define MAX_JOB_BOS 11
static bool memory_only;
static unsigned int expected_tag;
static bool expected_tag_set;
static int g3_set_expected_tag(const char *value, const struct kernel_param *kp)
{
 int rc=param_set_uint(value,kp);
 if(!rc)expected_tag_set=true;
 return rc;
}
static const struct kernel_param_ops g3_expected_tag_ops={
 .set=g3_set_expected_tag,.get=param_get_uint,
};
module_param_cb(expected_tag,&g3_expected_tag_ops,&expected_tag,0444);
MODULE_PARM_DESC(expected_tag,"Required matching hardware source tag; explicit zero is valid");
module_param(memory_only, bool, 0444);
MODULE_PARM_DESC(memory_only, "BO preflight only; never touches PL registers");
struct g3_device;
struct g3_buffer {
 struct g3_device *g; void *cookie; dma_addr_t dma; size_t bytes;
 unsigned long attrs; u32 kind,handle; refcount_t refs;
 unsigned int users; bool immutable;
 void *frozen;dma_addr_t frozen_dma;u32 frozen_bytes,command_count,expanded;
};
struct g3_slot {
 struct work_struct work; struct g3_device *g; bool occupied;
 struct gfx3_job job; struct g3_buffer *bo[MAX_JOB_BOS];
};
struct g3_record {struct gfx3_diagnostic diagnostic;struct gfx3_result r; bool valid;};
struct g3_device {
 struct device *dev; struct clk *clock; void __iomem *regs;
 struct miscdevice misc; struct mutex lock; struct idr handles;
 struct workqueue_struct *wq; struct g3_slot slot[2];
 struct completion rendered; wait_queue_head_t changed;
 struct g3_record history[HISTORY];
 struct g3_buffer *front[3],*pending[3],*layer_front,*layer_pending;
 bool layer_wait;u64 layer_sent_ns;
 u64 last_sequence,pending_sequence; u32 allocated,kernel_bytes,live_bos;
 atomic_t opened; bool quiet,quiet_active,faulted,pinned;
};
static struct platform_device *test_device;
static void g3_pin(struct g3_device *g)
{if(!g->pinned){__module_get(THIS_MODULE);g->pinned=true;}}
static void g3_buffer_put(struct g3_buffer *b)
{
 struct g3_device *g;
 if(!b||!refcount_dec_and_test(&b->refs))return;
 g=b->g;dma_free_attrs(g->dev,b->bytes,b->cookie,b->dma,b->attrs);
 if(b->frozen){dma_free_coherent(g->dev,b->frozen_bytes,b->frozen,b->frozen_dma);
  g->allocated-=b->frozen_bytes;g->kernel_bytes-=b->frozen_bytes;}
 g->allocated-=b->bytes;if(!b->attrs)g->kernel_bytes-=b->bytes;
 g->live_bos--;kfree(b);
}
static struct g3_buffer *g3_lookup(struct g3_device *g,u32 h,u32 kind)
{struct g3_buffer *b=idr_find(&g->handles,h);return b&&b->kind==kind?b:NULL;}
static bool g3_size(struct g3_buffer *b,u64 need)
{return b&&need&&need<=b->bytes;}
static u64 texture_bytes(struct gfx3_texture t)
{
 u64 size=0;u32 w=t.width,h=t.height,n;
 if(!w||!h||w>2048||h>2048||!t.levels||t.levels>12)return 0;
 for(n=0;n<t.levels;n++){
  size=ALIGN(size,128)+ALIGN(w,8)*ALIGN(h,4)*4ULL;
  if(w==1&&h==1){if(n+1!=t.levels)return 0;break;}
  w=max(1U,w>>1);h=max(1U,h>>1);
 }
 return ALIGN(size,128);
}
static bool g3_low_memory(size_t bytes)
{
 struct sysinfo info;unsigned long low;
 si_meminfo(&info);low=info.freeram-info.freehigh;
 return si_mem_available()<((192UL<<20)+bytes)/PAGE_SIZE||low<(64UL<<20)/PAGE_SIZE;
}
static int g3_allocate(struct g3_device *g,struct gfx3_bo *u)
{
 struct g3_buffer *b;u64 bytes=PAGE_ALIGN(u->bytes);int id;
 if(u->reserved||u->flags||u->handle||!u->bytes||bytes<u->bytes||bytes>GFX3_QUOTA||
    u->kind<GFX3_CONTROL||u->kind>GFX3_DEPTH)return -EINVAL;
 if(bytes>GFX3_QUOTA-g->allocated||g3_low_memory(bytes))return -ENOMEM;
 if(u->kind<=GFX3_COMMANDS&&bytes>GFX3_KERNEL_QUOTA-g->kernel_bytes)return -ENOSPC;
 b=kzalloc(sizeof(*b),GFP_KERNEL);if(!b)return -ENOMEM;
 b->g=g;b->bytes=bytes;b->kind=u->kind;
 b->attrs=u->kind<=GFX3_COMMANDS?0:DMA_ATTR_NO_KERNEL_MAPPING;
 b->cookie=dma_alloc_attrs(g->dev,b->bytes,&b->dma,GFP_KERNEL,b->attrs);
 if(!b->cookie){kfree(b);return -ENOMEM;}
 /* NO_KERNEL_MAPPING returns a cookie. Never dereference it. */
 id=idr_alloc(&g->handles,b,1,65536,GFP_KERNEL);
 if(id<0){dma_free_attrs(g->dev,b->bytes,b->cookie,b->dma,b->attrs);kfree(b);return id;}
 b->handle=id;refcount_set(&b->refs,1);g->allocated+=bytes;
 if(!b->attrs)g->kernel_bytes+=bytes;
 g->live_bos++;
 u->handle=id;u->bytes=bytes;return 0;
}
static struct g3_record *g3_record(struct g3_device *g,u64 seq)
{struct g3_record *r=&g->history[seq%HISTORY];return r->valid&&r->r.sequence==seq?r:NULL;}
static void g3_wr(struct g3_device *g,u32 r,u32 v){writel(v,g->regs+r);}
static void g3_drop_array(struct g3_buffer **b)
{int i;for(i=0;i<3;i++){if(b[i]){b[i]->users--;g3_buffer_put(b[i]);b[i]=NULL;}}}
static irqreturn_t g3_irq(int irq,void *data)
{
 struct g3_device *g=data;u32 st=readl(g->regs+G3_STATUS);
 if(!(st&GFX3_ST_IRQ))return IRQ_NONE;
 g3_wr(g,G3_CONTROL,GFX3_CTL_ACK|(g->quiet?GFX3_CTL_QUIET:0));
 complete(&g->rendered);wake_up_all(&g->changed);return IRQ_HANDLED;
}
/* Called under lock. Hardware's presented ID is latched only after old DDR
 * reads drain and the new source address has crossed the display boundary. */
static void g3_collect_present(struct g3_device *g)
{
 struct g3_record *r;u32 seq;int i;
 if(!g->pending_sequence)return;
 seq=readl(g->regs+G3_PRESENTED);
 if(seq!=(u32)g->pending_sequence)return;
 r=g3_record(g,g->pending_sequence);
 if(r){r->r.presented=1;r->r.present_ns=ktime_get_ns();}
 g3_drop_array(g->front);
 for(i=0;i<3;i++){g->front[i]=g->pending[i];g->pending[i]=NULL;}
 g->pending_sequence=0;wake_up_all(&g->changed);
}
static void g3_collect_layer(struct g3_device *g)
{
 u32 addr;if(!g->layer_wait||memory_only)return;
 addr=readl(g->regs+G3_ACTIVE_LAYER);
 if(addr!=(g->layer_pending?(u32)g->layer_pending->dma:0)){
  if(ktime_get_ns()-g->layer_sent_ns>1000000000ULL){g->faulted=true;g3_pin(g);}return;
 }
 if(g->layer_front){g->layer_front->users--;g3_buffer_put(g->layer_front);}
 g->layer_front=g->layer_pending;g->layer_pending=NULL;g->layer_wait=false;
}
static void g3_finish(struct g3_slot *s,int error)
{
 struct g3_device *g=s->g;struct g3_record *r=g3_record(g,s->job.sequence);int i;
 if(r){r->r.error=error;r->r.rendered=1;}
 for(i=0;i<MAX_JOB_BOS;i++)if(s->bo[i]){
  s->bo[i]->users--;g3_buffer_put(s->bo[i]);s->bo[i]=NULL;
 }
 s->occupied=false;wake_up_all(&g->changed);
}
static void g3_run(struct work_struct *work)
{
 struct g3_slot *s=container_of(work,struct g3_slot,work);
 struct g3_device *g=s->g;struct gfx3_job *j=&s->job;
 struct g3_record *r;u32 k,st;int error=0;
 mutex_lock(&g->lock);
 if(g->faulted){g3_finish(s,-EIO);mutex_unlock(&g->lock);return;}
 reinit_completion(&g->rendered);g3_wr(g,G3_CONTROL,GFX3_CTL_ACK);
 g3_wr(g,G3_CMD,(u32)s->bo[0]->frozen_dma);g3_wr(g,G3_COUNT,j->command_count);
 g3_wr(g,G3_GEOMETRY,(u32)s->bo[1]->dma);g3_wr(g,G3_BINS,(u32)s->bo[2]->dma);
 g3_wr(g,G3_REFS,j->refs_capacity);g3_wr(g,G3_FRAME,(u32)s->bo[3]->dma);
 g3_wr(g,G3_OBJECTS,(u32)s->bo[4]->dma);g3_wr(g,G3_THUMB,s->bo[5]?(u32)s->bo[5]->dma:0);
 g3_wr(g,G3_WH,j->width|(j->height<<16));g3_wr(g,G3_STRIDE,j->stride);
 g3_wr(g,G3_RGB,(u32)s->bo[6]->dma);g3_wr(g,G3_RGB_WH,j->rgb.width|(j->rgb.height<<16));
 g3_wr(g,G3_GROUND,(u32)s->bo[7]->dma);g3_wr(g,G3_GROUND_WH,j->ground.width|(j->ground.height<<16));
 g3_wr(g,G3_THERMAL,(u32)s->bo[8]->dma);g3_wr(g,G3_THERMAL_WH,j->thermal.width|(j->thermal.height<<16));
 g3_wr(g,G3_ALPHA,j->alpha);g3_wr(g,G3_BACKGROUND,j->background);
 if(readl(g->regs+G3_FEATURES)&GFX3_FEAT_DEPTH)g3_wr(g,448,s->bo[10]?(u32)s->bo[10]->dma:0);
 g3_wr(g,G3_FRAME_ID,(u32)j->sequence);g3_wr(g,G3_FLAGS,j->flags);
 g3_wr(g,G3_LEVELS,j->rgb.levels|(j->ground.levels<<4)|(j->thermal.levels<<8));
 g3_wr(g,G3_GENERATION,(u32)j->source_generation);
 for(k=0;k<12;k++)g3_wr(g,G3_MATRIX+4*k,j->matrix[k]);
 dma_wmb();g3_wr(g,G3_CONTROL,GFX3_CTL_START);mutex_unlock(&g->lock);
 if(!wait_for_completion_timeout(&g->rendered,msecs_to_jiffies(10000)))error=-ETIMEDOUT;
 mutex_lock(&g->lock);dma_rmb();st=readl(g->regs+G3_STATUS);
 if(st&GFX3_ST_FAULT)error=-EIO;
 if(readl(g->regs+G3_RENDERED)!=(u32)j->sequence&&!error)error=-EIO;
 r=g3_record(g,j->sequence);
 if(r){r->r.render_done_ns=ktime_get_ns();r->r.rendered=1;
  for(k=0;k<GFX3_COUNTER_COUNT;k++)r->r.counters[k]=
   readl(g->regs+G3_PERF+k*8)|((u64)readl(g->regs+G3_PERF+k*8+4)<<32);
  if(readl(g->regs+G3_FEATURES)&GFX3_FEAT_DIAGNOSTIC){r->diagnostic.sequence=j->sequence;
   for(k=0;k<6;k++)r->diagnostic.value[k]=readl(g->regs+400+k*8)|((u64)readl(g->regs+404+k*8)<<32);}}
 if(error){
  /* Keep every slot reference on error: bus quiescence has not been proven. */
  g->faulted=true;g3_pin(g);if(r)r->r.error=error;
  wake_up_all(&g->changed);mutex_unlock(&g->lock);return;
 }
 k=readl(g->regs+G3_ERROR);
 if(k){g3_finish(s,k==GFX3_REF_OVERFLOW?-ENOSPC:k==GFX3_VERTEX_OVERFLOW?-ERANGE:-EINVAL);
  mutex_unlock(&g->lock);return;}
 if(j->flags&GFX3_PRESENT){
  /* One pending mailbox; rendering of the next frame may overlap scanout. */
  while(g->pending_sequence||g->layer_wait){
   g3_collect_present(g);g3_collect_layer(g);if(!g->pending_sequence&&!g->layer_wait)break;
   mutex_unlock(&g->lock);msleep(1);mutex_lock(&g->lock);
   if(ktime_get_ns()-r->r.render_done_ns>1000000000ULL){
    g->faulted=true;g3_pin(g);r->r.error=-ETIMEDOUT;
    wake_up_all(&g->changed);mutex_unlock(&g->lock);return;
   }
  }
  for(k=0;k<3;k++)if(s->bo[k+3]){
   g->pending[k]=s->bo[k+3];refcount_inc(&g->pending[k]->refs);g->pending[k]->users++;
  }
  g->pending_sequence=j->sequence;g3_pin(g);
  if(j->flags&GFX3_LAYER_JOB){
   g->layer_pending=s->bo[9];refcount_inc(&g->layer_pending->refs);g->layer_pending->users++;
   g->layer_wait=true;g->layer_sent_ns=ktime_get_ns();g3_wr(g,G3_LAYER,(u32)s->bo[9]->dma);
  }
  /* Separate present doorbell. Never tied to pure render completion. */
  g3_wr(g,G3_FRONT,(u32)s->bo[3]->dma);g3_wr(g,G3_PRESENTED,(u32)j->sequence);
 }
 g3_finish(s,0);g3_collect_present(g);mutex_unlock(&g->lock);
}
static int g3_seal(struct g3_device *g,struct gfx3_seal *u)
{
 struct g3_buffer *b=g3_lookup(g,u->handle,GFX3_COMMANDS);u32 *cmd,k,n=0,bytes;void *copy;dma_addr_t dma;
 if(!b||u->reserved||!u->command_count||u->command_count>16385)return -EINVAL;
 if(b->immutable){if(b->command_count!=u->command_count)return -EINVAL;u->expanded_triangles=b->expanded;return 0;}
 bytes=u->command_count*64;
 if(b->users||!g3_size(b,bytes))return -EBUSY;
 if(bytes>GFX3_QUOTA-g->allocated||bytes>GFX3_KERNEL_QUOTA-g->kernel_bytes)return -ENOSPC;
 copy=dma_alloc_coherent(g->dev,bytes,&dma,GFP_KERNEL);if(!copy)return -ENOMEM;
 memcpy(copy,b->cookie,bytes);cmd=copy;
 for(k=0;k<u->command_count;k++){
  u32 f=cmd[k*16],op=f&255;
  if(cmd[k*16+3]||cmd[k*16+2]>65535||f&~(255U|0x4700U)||op>3||
   (op==0)!=(k==u->command_count-1))goto bad;
  if(op)n+=op==3?2:1;
 }
 if(n>GFX3_MAX_TRIANGLES)goto bad;
 dma_wmb();b->frozen=copy;b->frozen_dma=dma;b->frozen_bytes=bytes;
 b->command_count=u->command_count;b->expanded=n;b->immutable=true;
 g->allocated+=bytes;g->kernel_bytes+=bytes;u->expanded_triangles=n;return 0;
bad:dma_free_coherent(g->dev,bytes,copy,dma);return -EINVAL;
}
static int g3_submit(struct g3_device *g,struct gfx3_job *j)
{
 static const u32 kinds[MAX_JOB_BOS]={GFX3_COMMANDS,GFX3_GEOMETRY,GFX3_BINS,
  GFX3_FRAME,GFX3_OBJECTS,GFX3_PREVIEW,GFX3_TEXTURE,GFX3_TEXTURE,GFX3_TEXTURE,GFX3_FRAME,GFX3_DEPTH};
 u32 handles[MAX_JOB_BOS]={j->commands,j->geometry,j->bins,j->frame,j->objects,
  j->thumbnail,j->rgb.handle,j->ground.handle,j->thermal.handle,j->reserved[0],j->reserved[1]};
 struct g3_slot *s=NULL;struct g3_record *r;u32 k,n;u64 geom;
 g3_collect_present(g);
 if(memory_only)return -EOPNOTSUPP;
 if(g->faulted)return -EIO;
 if(g->quiet)return -EBUSY;
 if(!j->sequence||j->sequence>0xffffffffULL||j->sequence<=g->last_sequence||
  ((j->flags&GFX3_LAYER_JOB)?(!j->reserved[0]||!(j->flags&GFX3_PRESENT)||!(readl(g->regs+G3_FEATURES)&GFX3_FEAT_LAYER)):j->reserved[0])||((j->flags&GFX3_DEPTH_JOB)?(!j->reserved[1]||!(readl(g->regs+G3_FEATURES)&GFX3_FEAT_DEPTH)):j->reserved[1])||j->width==0||j->width>1280||j->height==0||
  j->height>720||(j->width&31)||(j->height&1)||j->stride!=j->width*4||
  j->alpha>255||j->flags&~(GFX3_PRESENT|GFX3_THUMBNAIL|GFX3_NATIVE_DISPLAY|GFX3_LAYER_JOB|GFX3_DEPTH_JOB)||
  !j->command_count||j->command_count>16385||!j->refs_capacity||j->refs_capacity>GFX3_MAX_REFS)
  return -EINVAL;
 for(k=0;k<2;k++)if(!g->slot[k].occupied){s=&g->slot[k];break;}
 if(!s)return -EBUSY;
 memset(s->bo,0,sizeof(s->bo));
 for(k=0;k<MAX_JOB_BOS;k++){
  if(k==5&&!(j->flags&GFX3_THUMBNAIL))continue;
  if(k==9&&!(j->flags&GFX3_LAYER_JOB))continue;
  if(k==10&&!(j->flags&GFX3_DEPTH_JOB))continue;
  s->bo[k]=g3_lookup(g,handles[k],kinds[k]);if(!s->bo[k])return -EINVAL;
  for(n=0;n<k;n++)if(s->bo[k]==s->bo[n]&&!(k>=6&&n>=6))return -EINVAL;
  if(((k>=1&&k<=5)||k==10)&&s->bo[k]->users)return -EBUSY;
 }
 if(!s->bo[0]->immutable||s->bo[0]->command_count!=j->command_count)return -EINVAL;
 geom=(u64)s->bo[0]->expanded*GFX3_GEOMETRY_STRIDE;
 if(!g3_size(s->bo[0],j->command_count*64ULL)||!g3_size(s->bo[1],max(128ULL,geom))||
  !g3_size(s->bo[2],GFX3_BIN_HEADER_BYTES+j->refs_capacity*4ULL)||
  !g3_size(s->bo[3],j->stride*(u64)j->height)||
  !g3_size(s->bo[4],j->width*(u64)j->height*2)||
  ((j->flags&GFX3_THUMBNAIL)&&!g3_size(s->bo[5],j->width*(u64)j->height))||
  !g3_size(s->bo[6],texture_bytes(j->rgb))||!g3_size(s->bo[7],texture_bytes(j->ground))||
  !g3_size(s->bo[8],texture_bytes(j->thermal))||
  ((j->flags&GFX3_LAYER_JOB)&&!g3_size(s->bo[9],1280*720*4ULL))||
  ((j->flags&GFX3_DEPTH_JOB)&&!g3_size(s->bo[10],j->width*(u64)j->height*2)))return -EINVAL;
 s->job=*j;s->occupied=true;g->last_sequence=j->sequence;
 for(k=0;k<MAX_JOB_BOS;k++)if(s->bo[k]){refcount_inc(&s->bo[k]->refs);s->bo[k]->users++;}
 r=&g->history[j->sequence%HISTORY];memset(r,0,sizeof(*r));r->valid=true;
 r->r.sequence=j->sequence;r->r.input_sequence=j->input_sequence;
 r->r.source_generation=j->source_generation;r->r.submit_ns=ktime_get_ns();
 r->r.frame=j->frame;r->r.objects=j->objects;r->r.thumbnail=j->thumbnail;
 queue_work(g->wq,&s->work);return 0;
}
static long g3_ioctl(struct file *file,unsigned int req,unsigned long arg)
{
 struct g3_device *g=container_of(file->private_data,struct g3_device,misc);
 void __user *p=(void __user *)arg;struct gfx3_bo bo;struct gfx3_job job;
 struct gfx3_result result;struct gfx3_quiet quiet;struct gfx3_seal seal;struct g3_buffer *b;
 struct gfx3_diagnostic diagnostic;struct gfx3_cursor cursor;struct gfx3_layer layer;struct gfx3_caps caps;struct g3_record *r;int rc=0;long waited;
 if(req==GFX3_WAIT){
  if(copy_from_user(&result,p,sizeof(result)))return -EFAULT;
  if(result.timeout_ns>10000000000ULL)return -EINVAL;
  /* Poll in 1ms slices also collects VSYNC adoption without a render IRQ. */
  for(waited=0;;waited++){
   mutex_lock(&g->lock);if(!memory_only)g3_collect_present(g);
   r=g3_record(g,result.sequence);
   if(!r){mutex_unlock(&g->lock);return -ENOENT;}
   if(r->r.rendered||r->r.error){result=r->r;mutex_unlock(&g->lock);break;}
   mutex_unlock(&g->lock);if(waited*1000000ULL>=result.timeout_ns)return -EAGAIN;
   if(msleep_interruptible(1))return -ERESTARTSYS;
  }
  return copy_to_user(p,&result,sizeof(result))?-EFAULT:0;
 }
 if(mutex_lock_interruptible(&g->lock))return -ERESTARTSYS;
 g3_collect_layer(g);
 if(req==GFX3_CAPS){
  memset(&caps,0,sizeof(caps));caps.abi=3;caps.build_id=GFX3_BUILD_ID;
  caps.width=1280;caps.height=720;caps.max_texture=2048;caps.max_triangles=GFX3_MAX_TRIANGLES;
  caps.max_refs=GFX3_MAX_REFS;caps.queue_depth=2;caps.quota_bytes=GFX3_QUOTA;
  caps.allocated_bytes=g->allocated;caps.kernel_mapped_bytes=g->kernel_bytes;
  caps.faulted=g->faulted;caps.clock_hz=memory_only?100000000:clk_get_rate(g->clock);caps.features=memory_only?0:15|readl(g->regs+496);
  caps.reserved[0]=memory_only?0:readl(g->regs+G3_SOURCE);
  caps.reserved[1]=(u32)g->last_sequence;
  rc=copy_to_user(p,&caps,sizeof(caps))?-EFAULT:0;
 }else if(req==GFX3_DIAGNOSTIC){
  if(copy_from_user(&diagnostic,p,sizeof(diagnostic)))rc=-EFAULT;
  else if(memory_only||!(readl(g->regs+G3_FEATURES)&GFX3_FEAT_DIAGNOSTIC))rc=-EOPNOTSUPP;
  else if(!(r=g3_record(g,diagnostic.sequence)))rc=-ENOENT;
  else if(!r->r.rendered)rc=-EAGAIN;
  else rc=copy_to_user(p,&r->diagnostic,sizeof(r->diagnostic))?-EFAULT:0;
 }else if(req==GFX3_CURSOR){
  if(copy_from_user(&cursor,p,sizeof(cursor)))rc=-EFAULT;
  else if(memory_only||!(readl(g->regs+G3_FEATURES)&GFX3_FEAT_CURSOR))rc=-EOPNOTSUPP;
  else if(g->quiet||g->faulted)rc=-EBUSY;
  else if(cursor.visible>1||cursor.x<0||cursor.x>=1280||cursor.y<0||cursor.y>=720)rc=-EINVAL;
  else{g3_wr(g,G3_CURSOR,(cursor.visible<<31)|(cursor.y<<16)|cursor.x);
   cursor.active_xy=readl(g->regs+G3_ACTIVE_CURSOR);rc=copy_to_user(p,&cursor,sizeof(cursor))?-EFAULT:0;}
 }else if(req==GFX3_LAYER){
  if(copy_from_user(&layer,p,sizeof(layer)))rc=-EFAULT;
  else if(memory_only||!(readl(g->regs+G3_FEATURES)&GFX3_FEAT_LAYER))rc=-EOPNOTSUPP;
  else if(layer.flags>1)rc=-EINVAL;
  else{
   if(layer.flags){
    b=layer.handle?g3_lookup(g,layer.handle,GFX3_FRAME):NULL;
    if(g->quiet||g->faulted||g->layer_wait)rc=-EBUSY;
    else if(layer.handle&&(!g3_size(b,1280*720*4ULL)||b->users))rc=-EINVAL;
    else{g->layer_pending=b;if(b){refcount_inc(&b->refs);b->users++;}
     g->layer_wait=true;g->layer_sent_ns=ktime_get_ns();g3_pin(g);dma_wmb();
     g3_wr(g,G3_LAYER,b?(u32)b->dma:0);g3_wr(g,G3_UI_COMMIT,1);}
   }
   layer.active_handle=g->layer_front?g->layer_front->handle:0;
   layer.pending_handle=g->layer_wait&&g->layer_pending?g->layer_pending->handle:0;
   if(!rc&&copy_to_user(p,&layer,sizeof(layer)))rc=-EFAULT;
  }
 }else if(req==GFX3_ALLOC){
  if(copy_from_user(&bo,p,sizeof(bo)))rc=-EFAULT;
  else if(!(rc=g3_allocate(g,&bo))&&copy_to_user(p,&bo,sizeof(bo))){
   b=idr_remove(&g->handles,bo.handle);g3_buffer_put(b);rc=-EFAULT;
  }
 }else if(req==GFX3_FREE){
  if(copy_from_user(&bo,p,sizeof(bo)))rc=-EFAULT;
  else if(!(b=idr_find(&g->handles,bo.handle)))rc=-ENOENT;
  else if(b->users)rc=-EBUSY;
  else{idr_remove(&g->handles,bo.handle);g3_buffer_put(b);}
 }else if(req==GFX3_SUBMIT){
  if(copy_from_user(&job,p,sizeof(job)))rc=-EFAULT;else rc=g3_submit(g,&job);
 }else if(req==GFX3_SEAL){
  if(copy_from_user(&seal,p,sizeof(seal)))rc=-EFAULT;
  else if(!(rc=g3_seal(g,&seal))&&copy_to_user(p,&seal,sizeof(seal)))rc=-EFAULT;
 }else if(req==GFX3_QUIET){
  if(copy_from_user(&quiet,p,sizeof(quiet)))rc=-EFAULT;
  else if(quiet.enable>1||quiet.timeout_ns>10000000000ULL)rc=-EINVAL;
  else{
   u64 deadline=ktime_get_ns()+quiet.timeout_ns;g->quiet=quiet.enable;
   g->quiet_active=false;
   while(g->quiet&&g->layer_wait&&!g->faulted){
    g3_collect_layer(g);if(!g->layer_wait)break;
    if(ktime_get_ns()>=deadline){rc=-ETIMEDOUT;break;}
    mutex_unlock(&g->lock);msleep(1);mutex_lock(&g->lock);
   }
   while(g->quiet&&(g->slot[0].occupied||g->slot[1].occupied)&&!g->faulted){
    if(ktime_get_ns()>=deadline){rc=-ETIMEDOUT;break;}
    mutex_unlock(&g->lock);msleep(1);mutex_lock(&g->lock);
   }
   if(!rc){
    if(!memory_only)g3_wr(g,G3_CONTROL,g->quiet?GFX3_CTL_QUIET:0);
    g->quiet_active=g->quiet&&!g->faulted;
    while(g->quiet_active&&!memory_only&&!(readl(g->regs+G3_STATUS)&8)){
     if(ktime_get_ns()>=deadline){g->quiet_active=false;rc=-ETIMEDOUT;break;}
     mutex_unlock(&g->lock);usleep_range(100,200);mutex_lock(&g->lock);
    }
    quiet.active=g->quiet_active;rc=copy_to_user(p,&quiet,sizeof(quiet))?-EFAULT:0;
   }
  }
 }else rc=-ENOTTY;
 mutex_unlock(&g->lock);return rc;
}
static void g3_vma_open(struct vm_area_struct *vma)
{struct g3_buffer *b=vma->vm_private_data;refcount_inc(&b->refs);}
static void g3_vma_close(struct vm_area_struct *vma)
{struct g3_buffer *b=vma->vm_private_data;struct g3_device *g=b->g;mutex_lock(&g->lock);g3_buffer_put(b);mutex_unlock(&g->lock);}
static const struct vm_operations_struct g3_vm_ops={.open=g3_vma_open,.close=g3_vma_close};
static int g3_mmap(struct file *file,struct vm_area_struct *vma)
{
 struct g3_device *g=container_of(file->private_data,struct g3_device,misc);
 struct g3_buffer *b;int rc=-EINVAL;unsigned long handle=vma->vm_pgoff;
 mutex_lock(&g->lock);b=idr_find(&g->handles,handle);
 if(b&&vma->vm_end-vma->vm_start<=b->bytes){
  vma->vm_pgoff=0;vma->vm_flags|=VM_DONTEXPAND|VM_DONTDUMP;
  rc=dma_mmap_attrs(g->dev,vma,b->cookie,b->dma,b->bytes,b->attrs);
  if(!rc){vma->vm_ops=&g3_vm_ops;vma->vm_private_data=b;refcount_inc(&b->refs);}
 }
 mutex_unlock(&g->lock);return rc;
}
static int g3_open(struct inode *i,struct file *f)
{struct g3_device *g=container_of(f->private_data,struct g3_device,misc);return atomic_cmpxchg(&g->opened,0,1)?-EBUSY:0;}
static int g3_close(struct inode *i,struct file *f)
{
 struct g3_device *g=container_of(f->private_data,struct g3_device,misc);
 struct g3_buffer *b;int id=0;
 flush_workqueue(g->wq);mutex_lock(&g->lock);
 while((b=idr_get_next(&g->handles,&id))){idr_remove(&g->handles,id);g3_buffer_put(b);}
 atomic_set(&g->opened,0);mutex_unlock(&g->lock);return 0;
}
static const struct file_operations g3_fops={.owner=THIS_MODULE,.open=g3_open,.release=g3_close,
 .unlocked_ioctl=g3_ioctl,.compat_ioctl=g3_ioctl,.mmap=g3_mmap};
static void g3_clock_off(void *p){clk_disable_unprepare(p);}
static int g3_probe(struct platform_device *pdev)
{
 struct g3_device *g;struct resource *res;int rc,k;
 g=devm_kzalloc(&pdev->dev,sizeof(*g),GFP_KERNEL);if(!g)return -ENOMEM;
 g->dev=&pdev->dev;
 if(memory_only){g->dev->coherent_dma_mask=DMA_BIT_MASK(32);g->dev->dma_mask=&g->dev->coherent_dma_mask;}
 rc=dma_set_mask_and_coherent(g->dev,DMA_BIT_MASK(32));if(rc)return rc;
 mutex_init(&g->lock);idr_init(&g->handles);init_completion(&g->rendered);
 init_waitqueue_head(&g->changed);atomic_set(&g->opened,0);
 if(!memory_only){
  g->clock=devm_clk_get(g->dev,"aclk");if(IS_ERR(g->clock))return PTR_ERR(g->clock);
  rc=clk_prepare_enable(g->clock);if(rc)return rc;
  rc=devm_add_action_or_reset(g->dev,g3_clock_off,g->clock);if(rc)return rc;
  res=platform_get_resource(pdev,IORESOURCE_MEM,0);g->regs=devm_ioremap_resource(g->dev,res);
  if(IS_ERR(g->regs))return PTR_ERR(g->regs);
  if(readl(g->regs+G3_ID)!=GFX3_BUILD_ID||!expected_tag_set||readl(g->regs+G3_SOURCE)!=expected_tag)return -ENODEV;
  rc=platform_get_irq(pdev,0);if(rc<0)return rc;
  rc=devm_request_irq(g->dev,rc,g3_irq,0,dev_name(g->dev),g);if(rc)return rc;
 }
 g->wq=alloc_ordered_workqueue("pcb-gfx3",WQ_MEM_RECLAIM);if(!g->wq)return -ENOMEM;
 for(k=0;k<2;k++){g->slot[k].g=g;INIT_WORK(&g->slot[k].work,g3_run);}
 g->misc.minor=MISC_DYNAMIC_MINOR;g->misc.name="pcb-gfx3";
 g->misc.fops=&g3_fops;g->misc.parent=g->dev;rc=misc_register(&g->misc);
 if(rc){destroy_workqueue(g->wq);return rc;}
 platform_set_drvdata(pdev,g);return 0;
}
static int g3_remove(struct platform_device *pdev)
{
 struct g3_device *g=platform_get_drvdata(pdev);
 if(g->pinned||g->live_bos||atomic_read(&g->opened))return -EBUSY;
 misc_deregister(&g->misc);destroy_workqueue(g->wq);idr_destroy(&g->handles);return 0;
}
static const struct of_device_id g3_match[]={{.compatible="pcb,graphics-3.0"},{}};
MODULE_DEVICE_TABLE(of,g3_match);
static struct platform_driver g3_driver={.probe=g3_probe,.remove=g3_remove,
 .driver={.name="pcb-gfx3",.of_match_table=g3_match,.suppress_bind_attrs=true}};
static int __init g3_init(void)
{
 int rc=platform_driver_register(&g3_driver);if(rc)return rc;
 if(memory_only){test_device=platform_device_register_simple("pcb-gfx3",-1,NULL,0);
  if(IS_ERR(test_device)){rc=PTR_ERR(test_device);platform_driver_unregister(&g3_driver);return rc;}}
 return 0;
}
static void __exit g3_exit(void)
{if(memory_only)platform_device_unregister(test_device);platform_driver_unregister(&g3_driver);}
module_init(g3_init);module_exit(g3_exit);
MODULE_LICENSE("GPL");MODULE_DESCRIPTION("PCB graphics ABI3 typed DMA and async renderer");
