#ifndef GRBL_GUARD_H
#define GRBL_GUARD_H
#include <math.h>
#include <string.h>
typedef struct {int origin_valid,position_valid,units_known,configured,busy;double x,y,ox,oy,stamp;char status[24];int left_rear_frame;double limit_x,limit_y,scale_x,scale_y;} Guard;
/* Verified physical directions: controller +X rear, +Y left.
 * Left-rear scan frame: local +X right, local +Y front. */
static double scale_x(const Guard *g){return g->scale_x>0?g->scale_x:1;}
static double scale_y(const Guard *g){return g->scale_y>0?g->scale_y:1;}
static double local_x(const Guard *g){return (g->left_rear_frame?g->oy-g->y:g->x-g->ox)/scale_x(g);}
/* Frame 0: controller; 1: right/front; 2: right/rear. */
static double local_y(const Guard *g){return (g->left_rear_frame==2?g->x-g->ox:(g->left_rear_frame?g->ox-g->x:g->y-g->oy))/scale_y(g);}
static double envelope_x(const Guard *g){return g->limit_x>0?g->limit_x:10;}
static double envelope_y(const Guard *g){return g->limit_y>0?g->limit_y:10;}
static int inside_envelope(const Guard *g){return local_x(g)>=-.05&&local_x(g)<=envelope_x(g)+.05&&local_y(g)>=-.05&&local_y(g)<=envelope_y(g)+.05;}
static void invalidate(Guard *g){g->origin_valid=0;}
static const char *arm_origin(Guard *g,int confirmed,double now){
    if(!confirmed)return "clearance_not_confirmed";
    if(!g->configured||!g->units_known)return "configuration_not_ready";
    if(g->busy||strcmp(g->status,"Idle"))return "controller_not_idle";
    if(!g->position_valid||!isfinite(g->x)||!isfinite(g->y)||!isfinite(g->stamp)||!isfinite(now)||now-g->stamp>1.0||now<g->stamp)return "position_stale";
    g->ox=g->x;g->oy=g->y;g->origin_valid=1;return NULL;
}
static const char *check_move(Guard *g,double x,double y,double feed,double now){
    if(!g->origin_valid)return "origin_required";
    if(!g->configured||!g->units_known)return "configuration_not_ready";
    if(!isfinite(x)||!isfinite(y)||!isfinite(feed)||x<0||x>envelope_x(g)||y<0||y>envelope_y(g)||feed<1||feed>120)return "outside_test_envelope";
    if(g->busy||strcmp(g->status,"Idle"))return "controller_not_idle";
    if(!g->position_valid||!isfinite(g->x)||!isfinite(g->y)||!isfinite(g->ox)||!isfinite(g->oy)||!isfinite(g->stamp)||!isfinite(now)||now-g->stamp>1.0||now<g->stamp){invalidate(g);return "position_stale";}
    if(!inside_envelope(g)){invalidate(g);return "reported_position_outside_envelope";}
    return NULL;
}
#endif
