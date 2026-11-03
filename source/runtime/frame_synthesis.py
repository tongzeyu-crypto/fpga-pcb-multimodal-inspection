"""Geometry-based reprojection, learned RGB fusion features, invalidation policy.

Full frames stay 1280x720. The CNN only predicts an 80x45 confidence grid.
The old confidence-training fixture remains explicitly named as legacy below.
"""
import json
import numpy as np
import cv2
W,H=1280,720
def project(world,yaw,pitch):
    cy,sy=np.cos(yaw),np.sin(yaw);cp,sp=np.cos(pitch),np.sin(pitch)
    r=np.array([[cy,0,sy],[sy*sp,cp,-cy*sp],[-sy*cp,sp,cy*cp]])
    p=world@r.T
    return np.stack([640+p[...,0]*.52,360-p[...,1]*.52,p[...,2]],-1),r
def render_prior(model,yaw,pitch):
    """Box approximation from explicitly imported component priors; z-buffered."""
    rgb=np.zeros((H,W,3),np.uint8)+22;depth=np.full((H,W),-1e9,np.float32);world=np.zeros((H,W,3),np.float32)
    size=model['board_geometry']['rectified_size_px'];sx,sz=size
    boxes=[(0,0,sx,sz,0,(30,92,142))]
    for i,c in enumerate(model['components']):
        x,z,w,h=c['bbox'];boxes.append((x,z,w,h,c['height']*6,((43+i*37)%180+40,(70+i*29)%180+30,(110+i*17)%140+60)))
    for bx,bz,bw,bh,ht,color in boxes:
        vv=np.array([[bx,0,bz],[bx+bw,0,bz],[bx+bw,0,bz+bh],[bx,0,bz+bh],[bx,ht,bz],[bx+bw,ht,bz],[bx+bw,ht,bz+bh],[bx,ht,bz+bh]],np.float32);vv[:,0]-=sx/2;vv[:,2]-=sz/2
        pp,_=project(vv,yaw,pitch)
        for inds in [(4,5,6),(4,6,7),(0,1,5),(0,5,4),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]:
            p=pp[list(inds)];v=vv[list(inds)];x0=max(0,int(np.floor(p[:,0].min())));x1=min(W,int(np.ceil(p[:,0].max()))+1);y0=max(0,int(np.floor(p[:,1].min())));y1=min(H,int(np.ceil(p[:,1].max()))+1)
            if x1<=x0 or y1<=y0:continue
            yy,xx=np.mgrid[y0:y1,x0:x1];den=(p[1,1]-p[2,1])*(p[0,0]-p[2,0])+(p[2,0]-p[1,0])*(p[0,1]-p[2,1])
            if abs(den)<1e-5:continue
            a=((p[1,1]-p[2,1])*(xx-p[2,0])+(p[2,0]-p[1,0])*(yy-p[2,1]))/den;b=((p[2,1]-p[0,1])*(xx-p[2,0])+(p[0,0]-p[2,0])*(yy-p[2,1]))/den;c=1-a-b
            zz=a*p[0,2]+b*p[1,2]+c*p[2,2];mask=(a>=0)&(b>=0)&(c>=0)&(zz>depth[y0:y1,x0:x1]);depth[y0:y1,x0:x1][mask]=zz[mask]
            world[y0:y1,x0:x1][mask]=(a[...,None]*v[0]+b[...,None]*v[1]+c[...,None]*v[2])[mask]
            rgb[y0:y1,x0:x1][mask]=color
    return rgb,depth,world
def reproject(rgb,depth,world,target_pose):
    pp,_=project(world,*target_pose);valid=depth>-1e8;yy,xx=np.indices((H,W));u=np.rint(pp[...,0]).astype(int);v=np.rint(pp[...,1]).astype(int)
    valid&=(u>=0)&(u<W)&(v>=0)&(v<H);src=np.flatnonzero(valid);dst=(v*W+u).ravel()[src]
    # Back-to-front stable scatter; nearest geometry wins the target depth test.
    order=np.argsort(pp[...,2].ravel()[src],kind='stable');src=src[order];dst=dst[order]
    out=np.zeros_like(rgb)+22;out.reshape(-1,3)[dst]=rgb.reshape(-1,3)[src]
    mask=np.zeros(H*W,np.float32);mask[dst]=1;mask=mask.reshape(H,W)
    flow=np.zeros((H*W,2),np.float32);flow[dst]=np.stack([u-xx,v-yy],-1).reshape(-1,2)[src]/32
    z=np.zeros(H*W,np.float32);z[dst]=pp[...,2].ravel()[src];z=z.reshape(H,W)
    edge=cv2.magnitude(cv2.Sobel(z,cv2.CV_32F,1,0),cv2.Sobel(z,cv2.CV_32F,0,1));edge=np.clip(edge/250,0,1)
    feature=np.concatenate([np.clip(flow.reshape(H,W,2),-1,1),edge[...,None],mask[...,None]],-1)
    feature=cv2.resize(feature,(80,45),interpolation=cv2.INTER_AREA).transpose(2,0,1)
    return out,mask,feature
class FrameGate:
    def __init__(self):self.key=None;self.inserted=False
    def allow(self,key,mode,angle,valid_fraction,confidence):
        if key!=self.key:self.key=key;self.inserted=False;return False
        ok=mode in {0,3} and not self.inserted and abs(angle)<=.025 and valid_fraction>.94 and confidence>.9
        if ok:self.inserted=True
        return ok
    def real_frame(self,key):self.key=key;self.inserted=False
def pixel_fusion_candidates(warped,valid,projection_features):
    """Python prototype; the native C++ path supplies authoritative demo tensors."""
    known=valid>.5;repair=warped.copy();holes=~known;claimed=np.zeros_like(known)
    offsets=sorted([(dx*dx+dy*dy,dy,dx) for dy in range(-2,3) for dx in range(-2,3)])
    for _,dy,dx in offsets:
        shifted=np.roll(known,(-dy,-dx),(0,1));pixels=np.roll(warped,(-dy,-dx),(0,1))
        if dy<0:shifted[:-dy]=False
        if dy>0:shifted[-dy:]=False
        if dx<0:shifted[:,:-dx]=False
        if dx>0:shifted[:,-dx:]=False
        use=holes&~claimed&shifted;repair[use]=pixels[use];claimed|=use
    mass=cv2.resize(valid.astype(np.float32),(80,45),interpolation=cv2.INTER_AREA)
    difference=np.abs(repair.astype(float)-warped).mean(2)/255
    features=np.stack([1-mass,projection_features[2],cv2.resize(difference.astype(np.float32),(80,45),interpolation=cv2.INTER_AREA),np.hypot(projection_features[0],projection_features[1])/np.maximum(mass,1/256)])
    return repair,np.clip(features,0,1).astype(np.float32)


def fuse_pixels(warped,repair,alpha):
    weights=np.rint(np.clip(alpha,0,1)*255).astype(np.uint32).repeat(16,0).repeat(16,1)[...,None]
    return (((255-weights)*warped.astype(np.uint32)+weights*repair.astype(np.uint32)+127)//255).astype(np.uint8)


def make_legacy_confidence_training_frames(root,seed):
    model=json.loads((root/'resources/models/model-v3.json').read_text(encoding='utf8'));datasets=[];metrics=[]
    for split,count in [(0,48),(1,12)]:
        rng=np.random.default_rng(seed+split);xs=[];ys=[]
        for i in range(count):
            yaw=rng.uniform(-.3,.3);pitch=rng.uniform(.65,1.05);step=rng.uniform(-.028,.028)
            rgb,z,world=render_prior(model,yaw,pitch);truth,zt,_=render_prior(model,yaw+step,pitch)
            warp,valid,feat=reproject(rgb,z,world,(yaw+step,pitch));err=np.abs(warp.astype(float)-truth).mean(2)
            target=cv2.resize(((err<10)&(valid>.5)).astype(np.float32),(80,45),interpolation=cv2.INTER_AREA)
            xs.append(feat);ys.append(target[None]);mask=zt>-1e8
            metrics.append({'split':'train' if split==0 else 'validation','pose':[yaw,pitch],'step':step,'full_frame_mae':float(err.mean()),'geometry_region_mae':float(err[mask].mean()),'valid_fraction_geometry':float(valid[mask].mean())})
            if split==1 and i==0:
                d=root/'evidence/frame-preview';d.mkdir(exist_ok=True)
                for name,image in [('full-render',truth),('reprojected',warp),('error',np.clip(err*6,0,255).astype(np.uint8))]:
                    (d/(name+'.png')).write_bytes(cv2.imencode('.png',image)[1].tobytes())
        datasets.append((np.array(xs,np.float32),np.array(ys,np.float32)))
    (root/'evidence/frame-truth.json').write_text(json.dumps({'resolution':[W,H],'source':'software rendered component box prior, no physical acquisition or measured depth','cases':metrics,'bandwidth_bytes_per_real_frame':{'color':W*H*4,'depth':W*H*2,'ids':W*H*2,'sum':W*H*8},'confidence_grid_io_bytes':80*45*(4+1),'board_fps':None},indent=2))
    return *datasets[0],*datasets[1]
