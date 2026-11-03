"""Visible-change rule screening, SIFT/RANSAC + local background correction."""
import cv2
import numpy as np
def detect(reference_bytes,test_bytes):
    def dec(b):
        x=cv2.imdecode(np.frombuffer(b,np.uint8),cv2.IMREAD_GRAYSCALE)
        if x is None or min(x.shape)<480 or x.size>24_000_000:raise ValueError('RGB dimensions')
        scale=min(1,1600/max(x.shape));return cv2.resize(x,None,fx=scale,fy=scale),scale
    ref,rs=dec(reference_bytes);test,ts=dec(test_bytes);sift=cv2.SIFT_create(nfeatures=3000)
    kr,dr=sift.detectAndCompute(ref,None);kt,dt=sift.detectAndCompute(test,None)
    if dr is None or dt is None:raise ValueError('insufficient RGB texture')
    pairs=cv2.BFMatcher().knnMatch(dt,dr,k=2);matches=[m for pair in pairs if len(pair)==2 for m,n in [pair] if m.distance<.72*n.distance]
    if len(matches)<16:raise ValueError('insufficient RGB correspondences')
    src=np.float32([kt[m.queryIdx].pt for m in matches]);dst=np.float32([kr[m.trainIdx].pt for m in matches]);mat,mask=cv2.findHomography(src,dst,cv2.RANSAC,3)
    if mat is None or mask.sum()<12 or mask.mean()<.45:raise ValueError('RGB registration rejected')
    warped=cv2.warpPerspective(test,mat,(ref.shape[1],ref.shape[0]));valid=cv2.warpPerspective(np.ones_like(test),mat,(ref.shape[1],ref.shape[0]))
    coverage=float(valid.mean())
    if coverage<.65:raise ValueError('RGB insufficient coverage')
    a=ref.astype(np.float32)-cv2.GaussianBlur(ref.astype(np.float32),(0,0),17);b=warped.astype(np.float32)-cv2.GaussianBlur(warped.astype(np.float32),(0,0),17)
    change=((np.abs(a-b)>30)&(valid>0)).astype(np.uint8)*255
    change=cv2.morphologyEx(change,cv2.MORPH_OPEN,np.ones((3,3),np.uint8));change=cv2.morphologyEx(change,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
    count,_,stats,_=cv2.connectedComponentsWithStats(change,8);regions=[]
    for x,y,w,h,area in stats[1:]:
        if area>=30:regions.append({'reference_native_xywh':[float(x/rs),float(y/rs),float(w/rs),float(h/rs)],'area_scaled_pixels':int(area),'kind':'visible structural change candidate'})
    full=np.diag([1/rs,1/rs,1])@mat@np.diag([ts,ts,1])
    return {'algorithm':'SIFT+RANSAC; local grayscale background subtraction; morphology; connected components','test_native_to_reference':full.tolist(),'inliers':int(mask.sum()),'coverage':coverage,'regions':regions,'electrical_continuity_tested':False,'internal_solder_joints_tested':False,'state':'review_required' if regions else 'no_obvious_visible_change'}
