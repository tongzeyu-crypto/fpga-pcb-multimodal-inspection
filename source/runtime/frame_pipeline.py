import cv2
import numpy as np
from .frame_synthesis import reproject,FrameGate,pixel_fusion_candidates,fuse_pixels
from .pl_backend import infer
class Pipeline:
    """Caller owns real-render completion, depth convention and ID buffer.

    Output is display-only; the caller must retain real_render_id for picking.
    The neural output is an RGB fusion weight, never a frame confidence score.
    Missing depth or a rejected geometry gate returns None => real render.
    """
    def __init__(self):self.gate=FrameGate()
    def synthesize(self,rgb,depth,world,pose,*,key,mode,angle,real_render_id,offline_test=False):
        if rgb.shape!=(720,1280,3) or depth.shape!=(720,1280) or world.shape!=(720,1280,3):raise ValueError('1280x720 real-render planes required')
        warped,valid,projection=reproject(rgb,depth,world,pose)
        repair,x=pixel_fusion_candidates(warped,valid,projection)
        logits=infer('frame',x,offline_test=offline_test)[0];alpha=1/(1+np.exp(-np.clip(logits,-20,20)))
        region=depth>-1e8;fraction=float(valid[region].mean()) if region.any() else 0
        if not self.gate.allow(key,mode,angle,fraction,1. if np.isfinite(alpha).all() else 0.):return None
        generated=fuse_pixels(warped,repair,alpha)
        return {'display_rgb':generated,'valid':valid,'blend_weights':alpha,'network_changed_pixels':int(np.any(generated!=warped,axis=2).sum()),'picking_real_render_id':real_render_id,'measurement_input':False,'synthetic':True}
