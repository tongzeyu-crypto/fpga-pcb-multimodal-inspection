"""Conservative, reference-driven AOI: grayscale structure and material topology.

No learned model. All thresholds are pixel/pitch/area ratios; no defect positions
or component IDs are embedded. Raw colour supplies an auxiliary material cue.
"""
import time
import cv2
import numpy as np
from aoi.engine import decode, digest, patch, points, polygon_mask, quality

VERSION='rgb-aoi-simple-v2'

def gray_structure(image, sigma=17.):
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim==3 else image
    base=cv2.GaussianBlur(gray.astype(np.float32),(0,0),sigma)
    return gray.astype(np.float32)-base

def gray_display(image):
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    light=cv2.GaussianBlur(gray.astype(np.float32),(0,0),31)
    corrected=np.clip(gray.astype(np.float32)*np.clip(65/np.maximum(light,12),.55,2.8),0,255).astype(np.uint8)
    return cv2.createCLAHE(1.5,(16,12)).apply(corrected)

def warm_body(image):
    hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    return (hsv[:,:,0]>=5)&(hsv[:,:,0]<=35)&(hsv[:,:,1]>=25)&(hsv[:,:,2]>=18)

def connected(binary):
    n,labels,stats,_=cv2.connectedComponentsWithStats(binary.astype(np.uint8))
    return labels,[(k,*map(int,stats[k])) for k in range(1,n)]

def inspect(ref,raw,sensitivity):
    started=time.perf_counter()
    if sensitivity not in ('normal','sensitive'):raise ValueError('检测档位无效')
    native=decode(raw);h,registration=ref.align(native,digest(raw));transform=ref.R@h
    board=cv2.warpPerspective(native,transform,ref.size)
    support=cv2.warpPerspective(np.full(native.shape[:2],255,np.uint8),transform,ref.size)
    gray=cv2.cvtColor(board,cv2.COLOR_BGR2GRAY)
    findings=[];observations=[];assessed=[];skipped=[]
    rows=[]
    for row in ref.rows:
        rgb,_=patch(board,row['quad'],tuple(row['size']));g=cv2.cvtColor(rgb,cv2.COLOR_BGR2GRAY)
        valid,_=patch(support,row['quad'],tuple(row['size']))
        q=quality(g);ratio=q['focus_laplacian']/max(1,row['quality']['focus_laplacian'])
        rows.append((row,rgb,g,valid,q,ratio))
    ratios=sorted([r[-1] for r in rows])
    # Defects themselves may smooth a lead row. Judge global focus from the
    # sharper half of independent rows, not solely from the damaged solder.
    context_focus=float(np.median(ratios[len(ratios)//2:])) if ratios else 0.
    global_bad=context_focus<.12
    visible=(support>250)&(ref.mask>0)
    suppressed=0

    def add(kind,component,poly,evidence,priority='优先复核'):
        poly=np.asarray(poly,np.float64)
        findings.append({'id':'','kind':kind,'component':component,'priority':priority,
            'evidence':evidence,'quad_board':poly.tolist(),'bbox_board':list(cv2.boundingRect(poly.astype(np.float32))),
            'quad_reference_native':points(poly,np.linalg.inv(ref.R)).tolist(),
            'quad_test_native':points(poly,np.linalg.inv(transform)).tolist(),'review':'unreviewed',
            'score_kind':'conservative material/shape rule; not defect probability'})

    # Lead connections: require an actual connected region joining neighbouring
    # lead centres. Simple brightness changes or one shifted pin are insufficient.
    for row,rgb,g,valid,q,focus in rows:
        if global_bad or not row['regular'] or np.mean(valid>250)<.98 or q['contrast_10_90']<15:
            skipped.append({'id':row['id'],'reason':'独立清晰度、可见范围或引脚基准不足','quality':q});continue
        assessed.append({'id':row['id'],'visible_peaks':len(row['peaks']),'pitch_px':row['pitch'],'quality':q})
        hsv=cv2.cvtColor(rgb,cv2.COLOR_BGR2HSV);pitch=row['pitch'];y0,y1=row['y0'],row['y1']
        otsu=cv2.threshold(g,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)[0]
        threshold=max(70,min(155,max(float(otsu)+12,float(np.percentile(g,70))+8)))
        metal=((g>=threshold)&(hsv[:,:,1]<115)).astype(np.uint8)
        structure=gray_structure(g,12);ref_structure=gray_structure(row['gray'],12)
        added=metal.astype(bool)&~cv2.dilate(row['metal'],np.ones((3,3),np.uint8)).astype(bool)&((structure-ref_structure)>18)
        inv=np.linalg.inv(row['H']);row_candidates=[]
        profile=metal[y0:y1].mean(axis=0);current=[]
        for peak in row['peaks']:
            lo=max(0,int(peak-pitch*.25));hi=min(g.shape[1],int(peak+pitch*.25)+1)
            current.append(lo+int(np.argmax(profile[lo:hi])))
        # Large continuous solder masses remain visible even when local pin
        # texture has disappeared. Close only tiny holes, never a full pin gap.
        permissive_threshold=max(45,min(threshold,float(np.percentile(g,40))+8))
        permissive=((g>=permissive_threshold)&(hsv[:,:,1]<115)).astype(np.uint8)
        macro=permissive[y0:y1].copy()
        macro=cv2.morphologyEx(macro,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
        labels,regions=connected(macro)
        for label,x,y,w,hh,area in regions:
            seed=int(np.sum(added[y0:y1][labels==label]))
            crossed=[i for i,(a,b) in enumerate(zip(row['peaks'][:-1],row['peaks'][1:])) if x<a and x+w>b]
            gap_seed=np.zeros_like(added[y0:y1]);novel_gaps=[]
            for i in crossed:
                a,b=current[i:i+2]
                gx0,gx1=round(a+pitch*.27),round(b-pitch*.27)
                if gx1<=gx0:continue
                part=added[y0:y1,gx0:gx1] & (labels[:,gx0:gx1]==label)
                if int(part.sum())>=max(8,pitch*.6):
                    novel_gaps.append(i);gap_seed[:,gx0:gx1]|=part
            if w>=pitch*1.65 and hh>=4 and area>=pitch*5 and seed>=max(25,pitch*1.8) and len(novel_gaps)>=2:
                sy,sx=np.nonzero(gap_seed);mx0=max(x,float(sx.min())-pitch*.6);mx1=min(x+w,float(sx.max())+pitch*.6)
                my0=max(y,float(sy.min())-4);my1=min(y+hh,float(sy.max())+5)
                poly=points([[mx0-3,my0+y0-3],[mx1+3,my0+y0-3],[mx1+3,my1+y0+3],[mx0-3,my1+y0+3]],inv)
                row_candidates.append((poly,{'row':row['id'],'adjacent_gap_indices':[i+1 for i in crossed],
                    'connected_area_px':area,'new_structure_area_px':seed,'basis':'连续金属区域跨越多个原本分离的引脚；按一片区域合并'}))
        if focus>=.13:
            # Refine individual lead centres inside bounded neighbourhoods to
            # tolerate residual parallax without altering any image or matrix.
            for i,(a,b) in enumerate(zip(current[:-1],current[1:])):
                if not .6*pitch<b-a<1.5*pitch:continue
                x0=max(0,round(a-pitch*.15));x1=min(g.shape[1],round(b+pitch*.15)+1)
                local=metal[y0:y1,x0:x1];labs,regions=connected(local)
                for label,x,y,w,hh,area in regions:
                    left=(a-x0)-x;right=(b-x0)-x
                    if not (left>=-1 and right<=w and w>=(b-a)*.95 and hh>=3):continue
                    pixels=(labs==label);seed=int(np.sum(added[y0:y1,x0:x1]&pixels))
                    if seed<max(12,pitch*.9):continue
                    # Ignore a corresponding pre-existing connection.
                    old=row['metal'][y0:y1,x0:x1];old_labels,old_regions=connected(old)
                    existed=any(ox<=a-x0 and ox+ow>=b-x0 and oh>=3 for _,ox,oy,ow,oh,oa in old_regions)
                    if existed:continue
                    poly=points([[x+x0-3,y+y0-3],[x+x0+w+3,y+y0-3],[x+x0+w+3,y+y0+hh+3],[x+x0-3,y+y0+hh+3]],inv)
                    row_candidates.append((poly,{'row':row['id'],'adjacent_gap_indices':[i+1],
                        'new_structure_area_px':seed,'basis':'同一金属连通域连接相邻引脚，并有基准中不存在的结构'}));break
        # Merge touching boxes within one row. Internal gap evidence is retained.
        groups=[]
        for poly,evidence in row_candidates:
            x,y,w,hh=cv2.boundingRect(poly.astype(np.float32));merged=False
            for group in groups:
                gx,gy,gw,gh=group['box'];margin=pitch*.9
                if x<=gx+gw+margin and x+w>=gx-margin and y<=gy+gh+margin and y+hh>=gy-margin:
                    nx,ny=min(gx,x),min(gy,y);group['box']=[nx,ny,max(gx+gw,x+w)-nx,max(gy+gh,y+hh)-ny]
                    group['evidence'].append(evidence);group['polys'].append(poly);merged=True;break
            if not merged:groups.append({'box':[x,y,w,hh],'evidence':[evidence],'polys':[poly]})
        for group in groups:
            local_points=points(np.concatenate(group['polys']),row['H'])
            lo=local_points.min(axis=0);hi=local_points.max(axis=0)
            region=points([[lo[0],lo[1]],[hi[0],lo[1]],[hi[0],hi[1]],[lo[0],hi[1]]],inv)
            add('疑似连锡区域',row['component'],region,
                {'row':row['id'],'merged_candidates':len(group['evidence']),'parts':group['evidence'],
                 'basis':'同一连续区域只列一项；不按引脚间隙累计故障数量'})

    # Presence of the component body, not absolute brightness, is the criterion.
    # Warm dielectric is a reference-derived material class, not a component ID.
    body_over_solder=[];presence_coverage=[]
    if not global_bad:
        for component in ref.components:
            if 'header' in component['family']:continue
            q=np.asarray(component['quad_px'],np.float32);edges=np.linalg.norm(np.roll(q,-1,axis=0)-q,axis=1)
            w,hh=max(12,round(edges[[0,2]].mean())),max(12,round(edges[[1,3]].mean()))
            before,_=patch(ref.board,q,(w,hh));after,_=patch(board,q,(w,hh));valid,_=patch(support,q,(w,hh))
            if np.mean(valid>250)<.98:continue
            yy,xx=np.indices((hh,w))
            core=((xx>w*.15)&(xx<w*.85)&(yy>hh*.28)&(yy<hh*.72)) if hh>w else ((xx>w*.28)&(xx<w*.72)&(yy>hh*.15)&(yy<hh*.85))
            a=cv2.cvtColor(before,cv2.COLOR_BGR2GRAY);b=cv2.cvtColor(after,cv2.COLOR_BGR2GRAY)
            sa=gray_structure(a,5);sb=gray_structure(b,5)
            ncc=float(cv2.matchTemplate(sb,sa,cv2.TM_CCOEFF_NORMED)[0,0])
            warm_ref=float(warm_body(before)[core].mean());warm_test=float(warm_body(after)[core].mean())
            saturation=cv2.cvtColor(after,cv2.COLOR_BGR2HSV)[:,:,1]
            black=float(np.mean(b[core]<25));neutral=float(np.mean(saturation[core]<38))
            relative_gap=float(np.mean(b[core]<max(18,float(np.percentile(b,90))*.34)))
            core_range=float(np.percentile(b[core],80)-np.percentile(b[core],20))
            material_lost=component['family']=='passive' and warm_ref>.5 and warm_test<.18 and warm_test<warm_ref*.28
            # A neutral/dark body needs grayscale shape evidence. Lost writing
            # alone is insufficient: its body-side outline must disappear too.
            norm_a=cv2.normalize(a,None,0,255,cv2.NORM_MINMAX);norm_b=cv2.normalize(b,None,0,255,cv2.NORM_MINMAX)
            edge_a=cv2.Canny(norm_a,60,120)>0;edge_b=cv2.Canny(norm_b,60,120)>0
            body_zone=((xx>w*.08)&(xx<w*.92)&(yy>hh*.2)&(yy<hh*.8)) if hh>w else ((xx>w*.2)&(xx<w*.8)&(yy>hh*.08)&(yy<hh*.92))
            band=body_zone&~core;reference_side=edge_a&band
            distance=cv2.distanceTransform((~edge_b).astype(np.uint8),cv2.DIST_L2,3)
            side_coverage=float(np.mean(distance[reference_side]<=1.5)) if reference_side.sum()>=15 else 1.
            aa=sa[core];bb=sb[core]
            core_ncc=float(np.corrcoef(aa,bb)[0,1]) if aa.std()>1 and bb.std()>1 else 0.
            neutral_absent=warm_ref<=.5 and aa.std()>4 and reference_side.sum()>=15 and side_coverage<.18 and core_ncc<.12 and ncc<.15
            presence_coverage.append({'component':component['id'],'material_reference_available':warm_ref>.5,
                'shape_reference_available':bool(reference_side.sum()>=15 and aa.std()>4)})
            body_absent=black>.50 or (relative_gap>.28 and core_range>25)
            if (material_lost and body_absent) or neutral_absent:
                add('疑似缺件',component['id'],q,{'reference_body_fraction':warm_ref,'test_body_fraction':warm_test,
                    'exposed_dark_gap_fraction':relative_gap,'structure_ncc':ncc,'body_outline_remaining':side_coverage,'core_ncc':core_ncc,
                    'basis':'正常参考中的连续器件本体消失，出现裸露焊盘／暗间隙；不是仅比较变暗'},'优先复核')
            elif material_lost and neutral>.70 and not body_absent:
                body_over_solder.append(component['id'])
                add('疑似焊锡过量／覆盖',component['id'],q,{'reference_body_fraction':warm_ref,'test_body_fraction':warm_test,
                    'neutral_material_fraction':neutral,'structure_ncc':ncc,
                    'basis':'原器件本体被连续灰色中性材料替代；保留人工复核，不自动判定材料成分'})
            else:
                # Keep potential lighting-only differences for diagnostics, off
                # the default defect list rather than labelling them faulty.
                difference=float(np.mean(cv2.absdiff(a,b)>35))
                if difference>.4:
                    suppressed+=1;observations.append({'component':component['id'],'reason':'外观变化，缺少本体消失或多余焊锡的充分证据','structure_ncc':ncc})

    # Independent solder blobs anywhere on the board. Existing metal, silk,
    # headers and lead rows are excluded; this never renames a nearby blob as C4.
    if not global_bad:
        hsv=cv2.cvtColor(board,cv2.COLOR_BGR2HSV);rhsv=cv2.cvtColor(ref.board,cv2.COLOR_BGR2HSV)
        detail=gray_structure(gray,13);r_detail=gray_structure(ref.gray,13)
        old_metal=((ref.gray>50)&(rhsv[:,:,1]<100)&(ref.mask>0)).astype(np.uint8)
        exclusion=cv2.dilate(old_metal,np.ones((21,21),np.uint8)).astype(bool)
        allowed=visible.copy()
        # Large existing bright/metal structures (socket shells, shielding,
        # mounting rings and large silk marks) are not newly deposited solder.
        # Infer their envelopes from the reference instead of hardcoding ports.
        fixed=cv2.morphologyEx(old_metal,cv2.MORPH_CLOSE,np.ones((9,9),np.uint8))
        fixed_labels,fixed_regions=connected(fixed)
        existing_large=np.zeros_like(fixed)
        for label,x,y,w,hh,area in fixed_regions:
            if area>=1800 and min(w,hh)>=35 and area/(w*hh)>.55 and w*hh<ref.mask.size*.08:
                existing_large[fixed_labels==label]=1
        allowed&=cv2.dilate(existing_large,np.ones((51,51),np.uint8))==0
        for row in ref.rows:allowed&=polygon_mask(gray.shape,row['quad'])==0
        for c in ref.components:
            # Structural reference covers existing bodies; excess solder beyond
            # those bodies remains eligible as an independent board region.
            pm=polygon_mask(gray.shape,c['quad_px'])
            # Raised connector pins have much larger parallax than the board.
            # Their solder is on the back, so exclude the full connector margin.
            margin=121 if 'header' in c['family'] else 9
            allowed&=cv2.dilate(pm,np.ones((margin,margin),np.uint8))==0
        # Ignore mounting rings and the outer substrate boundary.
        allowed&=cv2.erode(ref.mask,np.ones((17,17),np.uint8))>0
        new_metal=(gray>80)&(hsv[:,:,1]<105)&allowed
        seed=new_metal&~exclusion&((detail-r_detail)>22)
        seed=cv2.morphologyEx(seed.astype(np.uint8),cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
        seed=cv2.morphologyEx(seed,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
        labs,regions=connected(seed)
        for label,x,y,w,hh,area in regions:
            if area<(150 if sensitivity=='normal' else 80) or min(w,hh)<9:continue
            mask=(labs[y:y+hh,x:x+w]==label).astype(np.uint8)
            thickness=float(cv2.distanceTransform(np.pad(mask,1),cv2.DIST_L2,3).max()*2)
            if thickness<(9 if sensitivity=='normal' else 6):continue
            # Unchanged local structure is evidence for a lighting difference.
            x0,y0=max(0,x-12),max(0,y-12);x1,y1=min(gray.shape[1],x+w+12),min(gray.shape[0],y+hh+12)
            aa=gray_structure(ref.gray[y0:y1,x0:x1],7);bb=gray_structure(gray[y0:y1,x0:x1],7)
            structure_ncc=float(cv2.matchTemplate(bb,aa,cv2.TM_CCOEFF_NORMED)[0,0])
            if structure_ncc>.62:continue
            # Raised parts may shift locally under planar registration. If the
            # same grayscale shape already exists nearby in the normal photo,
            # treat it as a view/reflection change, not a new solder object.
            cx0,cy0=max(0,x-4),max(0,y-4);cx1,cy1=min(gray.shape[1],x+w+4),min(gray.shape[0],y+hh+4)
            search=ref.gray[max(0,cy0-35):min(gray.shape[0],cy1+35),max(0,cx0-35):min(gray.shape[1],cx1+35)]
            candidate=gray[cy0:cy1,cx0:cx1]
            nearby_match=float(cv2.matchTemplate(search,candidate,cv2.TM_CCOEFF_NORMED).max())
            if nearby_match>.60:
                observations.append({'component':'板面区域','reason':'邻近位置存在正常灰度形状，按视差／反光变化忽略','nearby_shape_ncc':nearby_match});continue
            poly=[[x-4,y-4],[x+w+4,y-4],[x+w+4,y+hh+4],[x-4,y+hh+4]]
            add('疑似多余焊锡块','板面独立区域',poly,{'area_px':area,'minimum_solid_thickness_px':thickness,'structure_ncc':structure_ncc,
                'basis':'基准中不存在的成块低饱和金属亮区；位于已知器件本体外，不归为最近元件缺陷'})

    for i,f in enumerate(findings):f['id']=f'candidate-{i+1:03}'
    state='insufficient_coverage' if global_bad else 'review_required' if findings else 'no_obvious_change'
    summary='可见细节不足，已停止判断；请重新拍摄' if global_bad else '发现明显疑似区域，等待人工复核' if findings else '已检查区域未发现明显缺陷；不等同于焊接合格'
    return {'version':VERSION,'state':state,'summary':summary,'reference_sha256':ref.sha,'test_sha256':digest(raw),
        'test_native_size':list(native.shape[1::-1]),'board_size':list(ref.size),'test_native_to_board':transform.tolist(),
        'reference_native_to_board':ref.R.tolist(),'registration':registration,
        'photometric':{'method':'local grayscale background subtraction + structural/material confirmation','absolute_difference_alone_can_trigger':False},
        'findings':findings,'assessed_rows':assessed,'skipped_rows':skipped,'excluded':ref.public_profile()['excluded'],
        'observations':observations,'suppressed_brightness_regions':suppressed,'context_focus_ratio':context_focus,'presence_coverage':presence_coverage,
        'warnings':['本图多处新增亮区，可能受照明／视角影响；请结合原色与灰度复核，必要时重拍同机位基准'] if sum(f['kind']=='疑似多余焊锡块' for f in findings)>5 else [],
        'sensitivity':sensitivity,'coordinates':'source-bound rectified board pixels; native inverse coordinates included',
        'component_appearance_checked':not global_bad,'elapsed_ms':(time.perf_counter()-started)*1000,
        'electrical_continuity_tested':False,'source':'native RGB photograph; corrected grayscale structure is primary, colour is auxiliary',
        'real_defect_validation_complete':False,'model_type':'thresholds, morphology, connected components; no CNN'},board
