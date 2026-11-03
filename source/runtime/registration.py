"""Fixed-rig residual correction with geometry and confidence rejection."""
import cv2
import numpy as np
from .pl_backend import infer
def structure(x):
    x=cv2.resize(x.astype(np.float32),(64,48));x=cv2.GaussianBlur(x,(3,3),0);a=cv2.magnitude(cv2.Sobel(x,cv2.CV_32F,1,0),cv2.Sobel(x,cv2.CV_32F,0,1));return np.clip(a/max(np.percentile(a,98),1e-5),0,1)
def correct(rgb_aligned,thermal_aligned,*,offline_test=False,compute=None):
    if not offline_test:
        if compute is None:raise RuntimeError('report production preprocessing requires PL compute')
        q=np.stack([compute.structure(rgb_aligned),compute.structure(thermal_aligned*1000)])
        from .pl_backend import infer_quantized
        y=infer_quantized('registration',q).reshape(9)
    else:
        x=np.stack([structure(rgb_aligned),structure(thermal_aligned)])
        y=infer('registration',x,offline_test=True).reshape(9)
    confidence=float(1/(1+np.exp(-np.clip(y[8],-20,20))))
    delta=y[:8].reshape(4,2)*4;corners=np.array([[0,0],[63,0],[63,47],[0,47]],np.float32);target=corners+delta
    # Strict gate: convex, no reflection, bounded displacement/area/condition.
    edges=np.roll(target,-1,axis=0)-target;cross=np.cross(edges,np.roll(edges,-1,axis=0));area=cv2.contourArea(target)
    if confidence<.8 or np.max(np.abs(delta))>6 or np.any(cross<=0) or not 2000<area<4000:raise ValueError('residual registration rejected')
    mat=cv2.getPerspectiveTransform(corners,target)
    if not np.isfinite(mat).all() or np.linalg.cond(mat)>100:raise ValueError('ill-conditioned residual')
    return mat,{'confidence':confidence,'corner_delta_grid_pixels':delta.tolist(),'status':'accepted fixed-rig augmentation model; absolute calibration unvalidated'}
def query_temperature(temp,thermal_to_display,display_xy):
    inv=np.linalg.inv(thermal_to_display);p=inv@np.r_[display_xy,1];p=p[:2]/p[2];x,y=np.rint(p).astype(int)
    if not 0<=x<temp.shape[1] or not 0<=y<temp.shape[0]:return None
    return {'temperature_c':float(temp[y,x]),'raw_thermal_xy':[int(x),int(y)],'absolute_accuracy_calibrated':False}
