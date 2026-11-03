#ifndef PCB_GFX3_PROTOCOL_H
#define PCB_GFX3_PROTOCOL_H
#include "gfx3_uapi.h"
enum gfx3_reg {
 G3_CONTROL=0,G3_STATUS=4,G3_CMD=8,G3_COUNT=12,G3_GEOMETRY=16,G3_BINS=20,
 G3_REFS=24,G3_FRAME=28,G3_OBJECTS=32,G3_THUMB=36,G3_WH=40,G3_STRIDE=44,
 G3_RGB=48,G3_RGB_WH=52,G3_GROUND=56,G3_GROUND_WH=60,
 G3_THERMAL=64,G3_THERMAL_WH=68,G3_ALPHA=72,G3_BACKGROUND=76,
 G3_FRAME_ID=80,G3_FLAGS=84,G3_LEVELS=88,G3_GENERATION=92,G3_MATRIX=96,G3_RENDERED=144,
 G3_PRESENTED=148,G3_FRONT=152,G3_ERROR=156,G3_PERF=256,G3_CURSOR=380,G3_LAYER=384,G3_ACTIVE_LAYER=388,G3_ACTIVE_CURSOR=392,G3_UI_COMMIT=396,G3_FEATURES=496,G3_SOURCE=504,G3_ID=508
};
/* Bin allocation: 1024 16-byte headers, then packed uint32 indices.
 * Each header holds {offset,count,cursor,reserved}; offsets are index counts.
 * Geometry: 128-byte records. Only PL writes these after command validation.
 * Textures: capability-selected mip chain, 8x4 blocks of eight 2x2 parity quads.
 * Every level is padded to 8x4 dimensions and 128-byte alignment.
 */
#define GFX3_BIN_HEADER_BYTES 16384U
#define GFX3_GEOMETRY_STRIDE 128U
#define GFX3_CTL_START 1U
#define GFX3_CTL_ACK 2U
#define GFX3_CTL_QUIET 4U
#define GFX3_ST_BUSY 1U
#define GFX3_ST_FAULT 2U
#define GFX3_ST_IRQ 4U
#define GFX3_ST_QUIET 8U
enum gfx3_error {GFX3_OK=0,GFX3_BAD_CONFIG=1,GFX3_BUS_ERROR=2,
 GFX3_REF_OVERFLOW=3,GFX3_VERTEX_OVERFLOW=4};
#endif
