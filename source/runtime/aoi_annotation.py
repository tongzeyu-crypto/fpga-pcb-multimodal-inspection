"""PS component/lead topology interpretation after the shared PL operators.

Coordinates originate in source-bound annotations, never guessed from a test
image. Findings describe visible candidates and retain inverse native maps.
"""
from pathlib import Path
import hashlib,json
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[1]

def load_annotations(raw):
    sha=hashlib.sha256(raw).hexdigest()
    candidates=[]
    for path in (ROOT/'resources/annotations').glob('*.json'):
        value=json.loads(path.read_text(encoding='utf8'))
        if value['source_rgb_sha256']==sha:return value
        candidates.append(value)
    for value in candidates:
        try:return adapt_annotations(raw,value)
        except (ValueError,OSError):continue
    return None

def adapt_annotations(raw,annotation):
    """Transfer a known board's annotation by a measured image homography."""
    annotation=json.loads(json.dumps(annotation));sha=hashlib.sha256(raw).hexdigest()
    if annotation['source_rgb_sha256']==sha:return annotation
    relative=Path(annotation.get('reference_image',''))
    if relative.is_absolute() or '..' in relative.parts:raise ValueError('annotation reference path')
    canonical=(ROOT/relative).read_bytes()
    if hashlib.sha256(canonical).hexdigest()!=annotation['source_rgb_sha256']:raise ValueError('canonical annotation source changed')
    a=cv2.imdecode(np.frombuffer(canonical,np.uint8),cv2.IMREAD_GRAYSCALE);b=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_GRAYSCALE)
    if a is None or b is None:raise ValueError('annotation image decode')
    if a.shape==b.shape and cv2.norm(a,b,cv2.NORM_INF)==0:
        matrix=np.eye(3);evidence={'method':'identical decoded pixel geometry','maximum_luma_difference':0}
    else:
        def features(image):
            scale=min(1.,1600/max(image.shape));small=cv2.resize(image,None,fx=scale,fy=scale)
            key,desc=cv2.SIFT_create(nfeatures=5000).detectAndCompute(small,None)
            return key,desc,scale
        ka,da,sa=features(a);kb,db,sb=features(b)
        if da is None or db is None:raise ValueError('annotation features')
        good=[pair[0] for pair in cv2.BFMatcher().knnMatch(db,da,k=2) if len(pair)==2 and pair[0].distance<.7*pair[1].distance]
        if len(good)<24:raise ValueError('not enough annotation correspondences')
        src=np.float32([kb[m.queryIdx].pt for m in good]);dst=np.float32([ka[m.trainIdx].pt for m in good])
        h,inliers=cv2.findHomography(src,dst,cv2.RANSAC,2)
        if h is None or inliers.sum()<20 or inliers.mean()<.6:raise ValueError('annotation transfer rejected')
        matrix=np.diag([1/sa,1/sa,1])@h@np.diag([sb,sb,1])
        evidence={'method':'SIFT/RANSAC annotation transfer','matches':len(good),'inliers':int(inliers.sum())}
    annotation['canonical_rgb_sha256']=annotation['source_rgb_sha256'];annotation['source_rgb_sha256']=sha
    annotation['native_to_board']=(np.asarray(annotation['native_to_board'],float)@matrix).tolist();annotation['transfer']=evidence
    return annotation

def transform(poly,matrix):return cv2.perspectiveTransform(np.float32(poly).reshape(-1,1,2),np.asarray(matrix,np.float64)).reshape(-1,2)

def assess(reference,test,valid,annotation,scale,native_test_to_ref,compute=None):
    if annotation is None:return [],[],None
    inv=np.linalg.inv(np.asarray(annotation['native_to_board'],float));to_scaled=np.diag([scale,scale,1])@inv
    occupied=np.zeros(reference.shape,np.uint8);findings=[];coverage=[]
    def warp(image,quad,width,height):
        mat=cv2.getPerspectiveTransform(np.float32(quad),np.float32([[0,0],[width-1,0],[width-1,height-1],[0,height-1]]))
        return cv2.warpPerspective(image,mat,(width,height))
    def threshold(image,value):
        if compute is not None:return compute.image('difference',image.astype(np.int32),second=np.zeros_like(image),valid=np.ones_like(image),threshold=int(value)).astype(np.uint8)
        return (image>value).astype(np.uint8)*255
    def add(kind,component,quad,evidence):
        native=np.asarray(quad,float)/scale;test_quad=transform(native,np.linalg.inv(native_test_to_ref))
        x,y,w,h=cv2.boundingRect(native.astype(np.float32))
        board_quad=transform(native,annotation['native_to_board']);bx,by,bw,bh=cv2.boundingRect(board_quad.astype(np.float32))
        findings.append(dict(kind=kind,component=component,quad_board=board_quad.tolist(),board_xywh=[bx,by,bw,bh],quad_reference_native=native.tolist(),quad_test_native=test_quad.tolist(),reference_native_xywh=[x,y,w,h],evidence=evidence))
    for component in annotation['components']:
        quad=transform(component['quad_px'],to_scaled);edges=np.linalg.norm(np.roll(quad,-1,axis=0)-quad,axis=1)
        width=max(12,min(1024,round(edges[[0,2]].mean())));height=max(12,min(1024,round(edges[[1,3]].mean())))
        cv2.fillConvexPoly(occupied,np.rint(quad).astype(np.int32),255)
        a=warp(reference,quad,width,height);b=warp(test,quad,width,height);support=warp(valid,quad,width,height)
        if np.mean(support>0)<.98:coverage.append(dict(component=component['id'],state='outside valid coverage'));continue
        # The PS owns local illumination correction and component decisions.
        sa=a.astype(float)-cv2.GaussianBlur(a.astype(float),(0,0),3);sb=b.astype(float)-cv2.GaussianBlur(b.astype(float),(0,0),3)
        if compute is not None:change=compute.image('difference',np.rint(sa*256).astype(np.int32),second=np.rint(sb*256).astype(np.int32),valid=np.ones_like(a),threshold=25*256)>0
        else:change=np.abs(sa-sb)>25
        if compute is not None:
            edge_a=float(compute.image('sobel',a).mean());edge_b=float(compute.image('sobel',b).mean())
        else:
            edge_a=float(np.mean(np.abs(cv2.Sobel(a,cv2.CV_32F,1,0)))+np.mean(np.abs(cv2.Sobel(a,cv2.CV_32F,0,1))))
            edge_b=float(np.mean(np.abs(cv2.Sobel(b,cv2.CV_32F,1,0)))+np.mean(np.abs(cv2.Sobel(b,cv2.CV_32F,0,1))))
        remaining=edge_b/max(edge_a,1);fraction=float(change.mean());coverage.append(dict(component=component['id'],state='assessed',remaining_structure=remaining,changed_fraction=fraction))
        if edge_a>15 and remaining<.3 and fraction>.25:add('component_presence_candidate',component['id'],quad,dict(remaining_structure=remaining,changed_fraction=fraction))
        family=component.get('family','');prior=component.get('pins',{}).get('count_per_side',0)
        if family=='powerchip':prior=component.get('pins',{}).get('total_visible',0)
        if family not in ('qfp','soic','powerchip') or not prior:continue
        center=quad.mean(0)
        explicit_rows=component.get('pins',{}).get('rows',[])
        for edge in (range(len(explicit_rows)) if explicit_rows else (1,3) if family=='soic' else range(4)):
            if explicit_rows:
                spec=explicit_rows[edge];row=transform(spec['quad_px'],to_scaled);length=np.linalg.norm(row[1]-row[0]);depth=np.linalg.norm(row[3]-row[0]);prior=spec['count']
                w=max(16,round(length));h=max(8,round(depth));aa=warp(reference,row,w,h);bb=warp(test,row,w,h)
            else:
                p,q=quad[edge],quad[(edge+1)%4];direction=q-p;length=np.linalg.norm(direction)
                if length<16:continue
                normal=np.array([-direction[1],direction[0]])/length
                if normal@((p+q)/2-center)<0:normal=-normal
                depth=max(8,min(60,length*.18));row=np.array([p+normal*3,q+normal*3,q+normal*depth,p+normal*depth])
                w=max(16,round(length));h=max(8,round(depth-3));aa=warp(reference,row,w,h);bb=warp(test,row,w,h)
            if np.mean(warp(valid,row,w,h)>0)<.98:continue
            cut=max(40,min(190,float(np.percentile(aa,65))+12));before=threshold(aa,cut);after=threshold(bb,cut)
            profile=(before>0).mean(0);pitch=w/max(prior,1);peaks=[]
            for x in np.argsort(profile)[::-1]:
                if profile[x]<.2:break
                if x>2 and x<w-3 and all(abs(int(x)-v)>max(3,pitch*.5) for v in peaks):peaks.append(int(x))
            peaks.sort()
            coverage.append(dict(component=component['id'],state='lead_row_assessed',edge=edge+1,visible_lead_peaks=peaks,annotated_lead_prior=prior))
            if len(peaks)<max(2,int(prior*.6)):continue
            count,labels,stats,_=cv2.connectedComponentsWithStats(after,8)
            for label in range(1,count):
                x,y,ww,hh,area=map(int,stats[label]);linked=[v for v in peaks if x<=v<x+ww]
                if len(linked)<2 or area<10:continue
                joined=(labels==label);new=int(np.count_nonzero(joined&(before==0)))
                if new<max(8,area*.15):continue
                # Reject connections already continuous in the normal image.
                old_count,old_labels,_,_=cv2.connectedComponentsWithStats(before,8)
                old_sets=[set(old_labels[:,max(0,v-1):v+2].ravel())-{0} for v in linked]
                if any(old_sets[i]&old_sets[j] for i in range(len(old_sets)) for j in range(i)):continue
                add('pin_bridge_candidate',component['id'],row,dict(edge=edge+1,connected_leads=linked,new_metal_pixels=new,area_pixels=area))
    return findings,coverage,occupied
