"""Visible-change rule screening, SIFT/RANSAC + local background correction."""
import cv2
import numpy as np
def detect(reference_bytes,test_bytes,gray=None,compute=None,annotations=None):
    if compute is not None:gray=compute.gray
    colors=[]
    def dec(b):
        x=cv2.imdecode(np.frombuffer(b,np.uint8),cv2.IMREAD_COLOR if gray else cv2.IMREAD_GRAYSCALE)
        if x is None or min(x.shape[:2])<480 or x.shape[0]*x.shape[1]>24_000_000:raise ValueError('RGB dimensions')
        scale=min(1,1600/max(x.shape[:2]))
        original=cv2.imdecode(np.frombuffer(b,np.uint8),cv2.IMREAD_COLOR)
        colors.append(cv2.resize(original,(round(original.shape[1]*scale),round(original.shape[0]*scale))))
        if compute is not None:
            x=gray(x[...,::-1]);x=compute.image('resize',x,out_width=round(x.shape[1]*scale),out_height=round(x.shape[0]*scale)).astype(np.uint8)
            return x,scale
        x=cv2.resize(x,None,fx=scale,fy=scale);return (gray(x[...,::-1]) if gray else x),scale
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
    if compute is not None:
        change=compute.image('difference',np.rint(a*256).astype(np.int32),second=np.rint(b*256).astype(np.int32),valid=valid,threshold=30*256)
        for operation,kernel in [('erode',3),('dilate',3),('dilate',5),('erode',5)]:change=compute.image(operation,change,kernel=kernel)
        change=change.astype(np.uint8)
    else:
        change=((np.abs(a-b)>30)&(valid>0)).astype(np.uint8)*255
        change=cv2.morphologyEx(change,cv2.MORPH_OPEN,np.ones((3,3),np.uint8));change=cv2.morphologyEx(change,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
    full=np.diag([1/rs,1/rs,1])@mat@np.diag([ts,ts,1])
    from .aoi_annotation import assess,load_annotations,adapt_annotations,transform
    annotations=adapt_annotations(reference_bytes,annotations) if annotations is not None else load_annotations(reference_bytes)
    findings,component_coverage,occupied=assess(ref,warped,valid,annotations,rs,full,compute)
    warped_color=cv2.warpPerspective(colors[1],mat,(ref.shape[1],ref.shape[0]));saturation=cv2.cvtColor(warped_color,cv2.COLOR_BGR2HSV)[...,1]
    count,_,stats,_=cv2.connectedComponentsWithStats(change,8);regions=list(findings)
    for x,y,w,h,area in stats[1:]:
        if area>=30:
            poly=np.array([[x,y],[x+w,y],[x+w,y+h],[x,y+h]],np.float32)/rs
            inverse=cv2.perspectiveTransform(poly.reshape(-1,1,2),np.linalg.inv(full)).reshape(-1,2)
            outside=occupied is not None and not np.any(occupied[y:y+h,x:x+w])
            material=(warped[y:y+h,x:x+w]>100)&(saturation[y:y+h,x:x+w]<100)
            metal=outside and float(material.mean())>.6
            board_quad=transform(poly,annotations['native_to_board']) if annotations else None
            regions.append({'reference_native_xywh':[float(x/rs),float(y/rs),float(w/rs),float(h/rs)],'quad_reference_native':poly.tolist(),'quad_test_native':inverse.tolist(),'quad_board':board_quad.tolist() if board_quad is not None else None,'board_xywh':list(cv2.boundingRect(board_quad.astype(np.float32))) if board_quad is not None else None,'area_scaled_pixels':int(area),'kind':'independent_metal_candidate' if metal else 'visible_structural_change_candidate'})
    return {'algorithm':'SIFT+RANSAC; PS local background correction and annotation topology; PL difference/threshold/morphology; PS connected components','test_native_to_reference':full.tolist(),'inliers':int(mask.sum()),'coverage':coverage,'regions':regions,'annotation_source_sha256':annotations['source_rgb_sha256'] if annotations else None,'annotation_transfer':annotations.get('transfer') if annotations else None,'component_appearance_checked':annotations is not None,'component_coverage':component_coverage,'electrical_continuity_tested':False,'internal_solder_joints_tested':False,'state':'annotation_required' if annotations is None else 'review_required' if regions else 'no_obvious_visible_change'}
