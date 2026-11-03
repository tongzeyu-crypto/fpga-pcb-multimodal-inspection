#ifndef PCB_GFX3_UAPI_H
#define PCB_GFX3_UAPI_H
#include <linux/types.h>
#include <linux/ioctl.h>
#define GFX3_ABI 3U
#define GFX3_BUILD_ID 0x47584633U
#define GFX3_QUOTA (192U*1024U*1024U)
#define GFX3_KERNEL_QUOTA (16U*1024U*1024U)
#define GFX3_MAX_TRIANGLES 16384U
#define GFX3_INITIAL_REFS 1048576U
#define GFX3_MAX_REFS 4194304U
enum gfx3_bo_kind {GFX3_CONTROL=1,GFX3_COMMANDS,GFX3_TEXTURE,GFX3_FRAME,
 GFX3_OBJECTS,GFX3_GEOMETRY,GFX3_BINS,GFX3_PREVIEW,GFX3_DEPTH};
enum gfx3_flags {GFX3_PRESENT=1,GFX3_THUMBNAIL=2,GFX3_NATIVE_DISPLAY=4,GFX3_LAYER_JOB=8,GFX3_DEPTH_JOB=16};
enum gfx3_counter {GFX3_TOTAL,GFX3_GEOMETRY_CYCLES,GFX3_BIN_CYCLES,
 GFX3_RASTER_CYCLES,GFX3_CACHE_MISS,GFX3_CACHE_WAIT,GFX3_BANK_STALL,GFX3_DDR_STALL,
 GFX3_MIX_WAIT,GFX3_READ_BYTES,GFX3_WRITE_BYTES,GFX3_FRAGMENTS,
 GFX3_TILES,GFX3_DISPLAY_READ_BYTES,GFX3_DISPLAY_UNDERFLOWS,GFX3_COUNTER_COUNT};
struct gfx3_caps {
 __u32 abi,build_id,width,height,max_texture,max_triangles,max_refs,queue_depth;
 __u32 quota_bytes,allocated_bytes,kernel_mapped_bytes,faulted;
 /* reserved[0]: hardware source identity; reserved[1]: last accepted sequence.
  * The next process must continue it, including across a retained display. */
 __u32 clock_hz,features,reserved[2];
};
/* mmap offset = handle << PAGE_SHIFT. Driver never accepts a physical address. */
struct gfx3_bo {__u32 handle,kind;__u64 bytes;__u32 flags,reserved;};
struct gfx3_texture {__u32 handle,width,height,levels;};
struct gfx3_job {
 __u64 sequence,input_sequence,source_generation;
 __u32 commands,command_count,geometry,bins,refs_capacity;
 __u32 frame,objects,thumbnail,width,height,stride,flags;
 struct gfx3_texture rgb,ground,thermal;
 __s32 matrix[12];
 /* With capability LAYER and flag LAYER_JOB, reserved[0] is a read-only UI FRAME handle. */
 __u32 alpha,background,reserved[2];
};
struct gfx3_result {
 __u64 sequence,timeout_ns,input_sequence,source_generation;
 __u64 submit_ns,render_done_ns,present_ns;
 __u64 counters[GFX3_COUNTER_COUNT];
 __s32 error;
 __u32 rendered,presented,frame,objects,thumbnail,reserved;
};
struct gfx3_quiet {__u32 enable,active;__u64 timeout_ns;};
/* A private validated snapshot is made once. The upload mapping stays separate. */
struct gfx3_seal {__u32 handle,command_count,expanded_triangles,reserved;};
#define GFX3_CAPS _IOR('V',0,struct gfx3_caps)
#define GFX3_ALLOC _IOWR('V',1,struct gfx3_bo)
#define GFX3_FREE _IOW('V',2,struct gfx3_bo)
#define GFX3_SUBMIT _IOW('V',3,struct gfx3_job)
#define GFX3_WAIT _IOWR('V',4,struct gfx3_result)
#define GFX3_QUIET _IOWR('V',5,struct gfx3_quiet)
#define GFX3_SEAL _IOWR('V',6,struct gfx3_seal)
/* Optional extensions, discovered via caps.features; existing ABI 3 structures unchanged. */
#define GFX3_FEAT_DEPTH 4096U
/* With DEPTH_JOB, job.reserved[1] is a typed uint16 depth-plane BO.
 * Size and existing ABI3 structs stay unchanged; clear capability => reject. */
#define GFX3_FEAT_DIAGNOSTIC 2048U
#define GFX3_FEAT_TILE8X4 256U
#define GFX3_FEAT_CURSOR 512U
#define GFX3_FEAT_LAYER 1024U
struct gfx3_cursor {__s32 x,y;__u32 visible,active_xy;__u64 sequence;};
/* flags=0 query, flags=1 set (handle=0 disables). Active/pending BOs remain pinned. */
struct gfx3_layer {__u32 handle,flags,active_handle,pending_handle;};
#define GFX3_CURSOR _IOWR('V',9,struct gfx3_cursor)
#define GFX3_LAYER _IOWR('V',10,struct gfx3_layer)
/* Per-frame counters may overlap; never sum them as frame elapsed time. */
struct gfx3_diagnostic {__u64 sequence,value[6];};
#define GFX3_DIAGNOSTIC _IOWR('V',11,struct gfx3_diagnostic)
#endif
