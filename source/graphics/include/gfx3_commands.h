#ifndef GFX3_COMMANDS_H
#define GFX3_COMMANDS_H
#include <cstdint>
typedef uint32_t gfx_u32;typedef int32_t gfx_s32;
enum gfx_opcode { GFX_END=0,GFX_TRIANGLE=1,GFX_SCREEN_TRIANGLE=2,GFX_SPRITE=3 };
enum gfx_flags { GFX_TEXTURED=1<<8,GFX_THERMAL=1<<9,GFX_CULL_BACK=1<<10,GFX_GROUND=1<<14 };
// World XYZ = signed Q16.16; UV = UNORM16, image origin at upper-left.
// SCREEN_TRIANGLE: X/Y are Q16.16 pixels; Z is uint16 in the low word.
// SPRITE: vertex 0 is world center; vertex 1 X/Y are pixel width/height Q16.16.
struct gfx_vertex_word { gfx_s32 x,y,z;gfx_u32 uv; };
struct gfx_command { gfx_u32 opcode_flags,argb,object_id,reserved;struct gfx_vertex_word v[3]; };
#ifdef __cplusplus
static_assert(sizeof(gfx_command)==64,"GPU command ABI must stay 64 bytes");
#endif

#endif
