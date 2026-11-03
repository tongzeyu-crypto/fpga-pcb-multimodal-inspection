"""Reference-based screening of gross, visible PCB changes at native resolution.

All boxes remain in the reference board coordinate system, with inverse maps to
both native photographs. Findings are review candidates, never IPC acceptance or
an electrical continuity decision. Hidden joints are explicitly excluded.
"""
from pathlib import Path
import hashlib
import io
import time
import cv2
import numpy as np
from PIL import Image
from scipy.signal import find_peaks

VERSION = 'rgb-aoi-simple-v2'

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def decode(raw):
    if not 100 <= len(raw) <= 24 * 1024 * 1024:
        raise ValueError('照片应为 24 MiB 以内的 JPEG 或 PNG')
    if not (raw.startswith(b'\xff\xd8') or raw.startswith(b'\x89PNG\r\n\x1a\n')):
        raise ValueError('只接受 JPEG／PNG 原图；HEIC 请先导出为 JPEG')
    try:
        with Image.open(io.BytesIO(raw)) as header:
            w, h = header.size
            if min(h, w) < 480 or h*w > 24_000_000:
                raise ValueError('照片过小或超过 2400 万像素，请选择高清原图')
    except (OSError, Image.DecompressionBombError) as e:
        raise ValueError('照片文件损坏或像素尺寸过大') from e
    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise ValueError('照片无法解码，请重新选择文件')
    h, w = image.shape[:2]
    if min(h, w) < 480 or h * w > 24_000_000:
        raise ValueError('照片过小或超过 2400 万像素，请选择高清原图')
    return image

def points(p, matrix):
    return cv2.perspectiveTransform(np.asarray(p, np.float64).reshape(-1, 1, 2), np.asarray(matrix, np.float64)).reshape(-1, 2)

def image_bytes(image, ext='.jpg'):
    ok, raw = cv2.imencode(ext, image, [cv2.IMWRITE_JPEG_QUALITY, 95] if ext == '.jpg' else [])
    if not ok:
        raise ValueError('图像导出失败')
    return raw.tobytes()

def polygon_mask(shape, poly):
    out = np.zeros(shape[:2], np.uint8)
    cv2.fillConvexPoly(out, np.round(poly).astype(np.int32), 255)
    return out

def patch(image, quad, size):
    w, h = size
    hmat = cv2.getPerspectiveTransform(np.float32(quad), np.float32([[0, 0], [w-1, 0], [w-1, h-1], [0, h-1]]))
    return cv2.warpPerspective(image, hmat, (w, h), flags=cv2.INTER_LINEAR), hmat

def quality(gray):
    return {'focus_laplacian': float(cv2.Laplacian(gray, cv2.CV_32F).var()),
            'contrast_10_90': float(np.percentile(gray, 90)-np.percentile(gray, 10)),
            'clipped_fraction': float(np.mean(gray >= 250))}

class Reference:
    def __init__(self, raw, manifest, annotations):
        self.raw, self.sha = raw, digest(raw)
        self.native = decode(raw)
        labels = manifest['source_labels']
        if self.sha != labels['rgb_sha256'] or annotations['source_rgb_sha256'] != self.sha:
            raise ValueError('元件标注／板面映射与这张正常基准照片不匹配')
        self.mapping = labels['rectification']
        self.R = np.asarray(self.mapping['native_to_display'], np.float64)
        self.size = tuple(self.mapping['size'])
        self.board = cv2.warpPerspective(self.native, self.R, self.size)
        self.gray = cv2.cvtColor(self.board, cv2.COLOR_BGR2GRAY)
        self.board_quad = np.asarray(annotations['board_quad_px'], np.float64)
        self.mask = polygon_mask(self.gray.shape, self.board_quad)
        self.components = annotations['components']
        self.rows = self._rows()
        self._features = None

    def _rows(self):
        rows = []
        for component in self.components:
            family = component['family']
            if family not in ('qfp', 'soic'):
                continue
            q = np.asarray(component['quad_px'], np.float64)
            edges = list(range(4)) if family == 'qfp' else [1, 3]
            for edge in edges:
                a, b = q[edge], q[(edge+1) % 4]
                direction = b-a
                length = np.linalg.norm(direction)
                normal = np.array([-direction[1], direction[0]]) / length
                if normal @ ((a+b)*.5-q.mean(axis=0)) < 0:
                    normal = -normal
                along = direction/length
                margin = max(3., length*.025)
                a, b = a+along*margin, b-along*margin
                outer = min(88., max(38., length*.15))
                region = np.array([a-normal*3, b-normal*3, b+normal*outer, a+normal*outer])
                size = (round(length-2*margin), round(outer+3))
                rgb, hmat = patch(self.board, region, size)
                gray = cv2.cvtColor(rgb, cv2.COLOR_BGR2GRAY)
                hsv = cv2.cvtColor(rgb, cv2.COLOR_BGR2HSV)
                # Bright, weakly coloured material is a visual metal cue only.
                threshold = float(np.clip(np.percentile(gray, 60), 55, 160))
                metal = ((gray >= threshold) & (hsv[:, :, 1] < 125)).astype(np.uint8)
                y0, y1 = 4, max(8, int(size[1]*.82))
                profile = metal[y0:y1].mean(axis=0).astype(np.float32)
                profile = cv2.GaussianBlur(profile.reshape(1, -1), (0, 0), .9).ravel()
                prior = component.get('pins', {}).get('count_per_side', 0)
                estimate_pitch = size[0]/max(1, prior)
                peaks, _ = find_peaks(profile, distance=max(4, round(estimate_pitch*.65)), prominence=.075)
                peaks = peaks[(peaks > 3) & (peaks < size[0]-4)]
                measured_pitch = float(np.median(np.diff(peaks))) if len(peaks) > 2 else 0.
                regular = bool(len(peaks) >= max(3, int(prior*.65)) and measured_pitch >= 5 and
                               np.mean(np.abs(np.diff(peaks)-measured_pitch) <= measured_pitch*.4) >= .65)
                rows.append({'id': f"{component['id']}-edge-{edge+1}", 'component': component['id'],
                             'edge': edge+1, 'quad': region.tolist(), 'size': list(size), 'H': hmat,
                             'rgb': rgb, 'gray': gray, 'metal': metal, 'threshold': threshold,
                             'peaks': peaks, 'pitch': measured_pitch, 'regular': regular,
                             'quality': quality(gray), 'y0': y0, 'y1': y1,
                             'pin_count_basis': 'image peak locations; package annotation is a spacing prior'} )
        return rows

    def public_profile(self):
        return {'version': VERSION, 'reference_sha256': self.sha,
                'native_size': list(self.native.shape[1::-1]), 'board_size': list(self.size),
                'reference_confirmed_normal': True,
                'confirmation': 'User: 现在的是正常板，我来制造一些缺陷',
                'coordinate_basis': 'unchanged source-bound rectified board pixels',
                'native_to_board': self.R.tolist(),
                'components': [{'id': c['id'], 'family': c['family'], 'quad': c['quad_px'],
                                'scope': 'visible lead screening' if c['family'] in ('qfp', 'soic') else
                                'solder hidden; external appearance only' if 'header' in c['family'] or c['family']=='leadless' else 'external appearance only'} for c in self.components],
                'rows': [{k: row[k] for k in ('id', 'component', 'edge', 'quad', 'size', 'pitch', 'regular', 'quality')} |
                         {'visible_peaks': len(row['peaks'])} for row in self.rows],
                'excluded': ['排针背面焊点', '封装底部焊点', '虚焊／润湿内部状态', '电气通断', '轻微裂纹与细微少锡']}

    def align(self, image, sha):
        if sha == self.sha:
            return np.eye(3), {'method': 'identical source bytes', 'accepted': True, 'inliers': None,
                               'median_reprojection_px': 0., 'coverage': 1., 'same_source': True}
        # SIFT is run at a bounded working size, matrices are restored to native pixels.
        def features(img, mask=None):
            scale = min(1., 1800/max(img.shape[:2]))
            small = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            m = None if mask is None else cv2.resize(mask, gray.shape[::-1], interpolation=cv2.INTER_NEAREST)
            key, desc = cv2.SIFT_create(nfeatures=6500, contrastThreshold=.025).detectAndCompute(gray, m)
            return key, desc, scale
        if self._features is None:
            native_mask = cv2.warpPerspective(self.mask, np.linalg.inv(self.R), self.native.shape[1::-1])
            self._features = features(self.native, native_mask)
        kr, dr, sr = self._features
        kt, dt, st = features(image)
        if dr is None or dt is None:
            raise ValueError('待测照片缺少可匹配的板面结构，请检查取景和焦距')
        matches = cv2.BFMatcher(cv2.NORM_L2).knnMatch(dt, dr, k=2)
        good = [pair[0] for pair in matches if len(pair)==2 and pair[0].distance < .70*pair[1].distance]
        if len(good) < 24:
            raise ValueError('无法可靠对齐到这块正常板：有效匹配少于 24，请保持同一块板和接近的拍摄角度')
        src = np.float32([kt[m.queryIdx].pt for m in good])
        dst = np.float32([kr[m.trainIdx].pt for m in good])
        h, inliers = cv2.findHomography(src, dst, cv2.RANSAC, 2., maxIters=5000, confidence=.999)
        if h is None:
            raise ValueError('照片对齐失败，请重新拍摄完整板面')
        valid = inliers.ravel().astype(bool)
        errors = np.linalg.norm(points(src[valid], h)-dst[valid], axis=1)/sr
        board_native = points(self.board_quad, np.linalg.inv(self.R))
        coverage = cv2.contourArea(cv2.convexHull(dst[valid]/sr))/max(1., cv2.contourArea(board_native.astype(np.float32)))
        info = {'method': 'SIFT + RANSAC planar homography', 'inliers': int(valid.sum()),
                'matches': len(good), 'inlier_ratio': float(valid.mean()),
                'median_reprojection_px': float(np.median(errors)), 'p95_reprojection_px': float(np.percentile(errors, 95)),
                'coverage': float(coverage), 'same_source': False}
        if valid.sum() < 16 or valid.mean() < .40 or coverage < .18 or np.median(errors) > 2.5 or np.percentile(errors,95) > 6:
            raise ValueError('对齐质量不足，已停止缺陷判断。请用接近基准的角度、完整入镜并重新对焦')
        native_h = np.diag([1/sr, 1/sr, 1.]) @ h @ np.diag([st, st, 1.])
        projected = points(board_native, np.linalg.inv(native_h))
        ratio = cv2.contourArea(projected.astype(np.float32))/max(1, image.shape[0]*image.shape[1])
        if not np.isfinite(projected).all() or not cv2.isContourConvex(projected.astype(np.float32)) or not .04 < ratio < .98:
            raise ValueError('照片的板面投影退化，不能进行可靠对比')
        info['accepted'] = True
        return native_h, info

    def inspect(self, raw, sensitivity='normal'):
        from aoi.rules_v2 import inspect
        return inspect(self, raw, sensitivity)

    def inspect_legacy(self, raw, sensitivity='normal'):
        started = time.perf_counter()
        if sensitivity not in ('normal', 'sensitive'):
            raise ValueError('检测档位无效')
        image = decode(raw)
        h, registration = self.align(image, digest(raw))
        combined = self.R @ h
        board = cv2.warpPerspective(image, combined, self.size)
        support = cv2.warpPerspective(np.full(image.shape[:2], 255, np.uint8), combined, self.size)
        gray = cv2.cvtColor(board, cv2.COLOR_BGR2GRAY)
        sample = (self.mask > 0) & (support > 250)
        refq, testq = np.percentile(self.gray[sample], [15, 50, 85]), np.percentile(gray[sample], [15, 50, 85])
        gain = float(np.clip((refq[2]-refq[0])/max(testq[2]-testq[0], 1), .65, 1.5))
        offset = float(np.clip(refq[1]-gain*testq[1], -40, 40))
        normalized = np.clip(board.astype(np.float32)*gain+offset, 0, 255).astype(np.uint8)
        normalized_gray = cv2.cvtColor(normalized, cv2.COLOR_BGR2GRAY)
        findings, assessed, skipped = [], [], []
        delta_threshold = 35 if sensitivity == 'normal' else 27

        def finding(kind, component, poly, evidence, score):
            poly = np.asarray(poly, np.float64)
            bounds = cv2.boundingRect(poly.astype(np.float32))
            item = {'id': f'candidate-{len(findings)+1:03}', 'kind': kind, 'component': component,
                    'priority': '优先复核' if score >= .8 else '待复核', 'score_kind': 'rule strength; not defect probability',
                    'evidence': evidence, 'quad_board': poly.tolist(), 'bbox_board': list(bounds),
                    'quad_reference_native': points(poly, np.linalg.inv(self.R)).tolist(),
                    'quad_test_native': points(poly, np.linalg.inv(combined)).tolist(),
                    'review': 'unreviewed'}
            findings.append(item)

        for row in self.rows:
            current, _ = patch(normalized, row['quad'], tuple(row['size']))
            g = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
            valid, _ = patch(support, row['quad'], tuple(row['size']))
            q = quality(g)
            if not row['regular'] or np.mean(valid > 250) < .98 or q['focus_laplacian'] < max(12, row['quality']['focus_laplacian']*.18) or q['contrast_10_90'] < 20 or q['clipped_fraction'] > .18:
                skipped.append({'id': row['id'], 'reason': '引脚周期、清晰度、反光或完整视野不足', 'quality': q})
                continue
            assessed.append({'id': row['id'], 'visible_peaks': len(row['peaks']), 'pitch_px': row['pitch'], 'quality': q})
            hsv = cv2.cvtColor(current, cv2.COLOR_BGR2HSV)
            metal = (g >= row['threshold']) & (hsv[:, :, 1] < 125)
            refmetal = row['metal'].astype(bool)
            # One-pixel tolerance prevents small registration/edge resampling
            # differences being interpreted as newly deposited material.
            added = metal & ~cv2.dilate(row['metal'], np.ones((3, 3), np.uint8)).astype(bool) & ((g.astype(float)-row['gray']) > delta_threshold)
            inv = np.linalg.inv(row['H'])
            pitch = row['pitch']; y0, y1 = row['y0'], row['y1']
            for index, (a, b) in enumerate(zip(row['peaks'][:-1], row['peaks'][1:])):
                if not .6*pitch < b-a < 1.5*pitch:
                    continue
                x0, x1 = int(a+pitch*.22), int(b-pitch*.22)
                if x1-x0 < 3:
                    continue
                gap = added[y0:y1, x0:x1].astype(np.uint8)
                n, labels, stats, _ = cv2.connectedComponentsWithStats(gap)
                for k in range(1, n):
                    x, y, w, hh, area = [int(v) for v in stats[k]]
                    continuous = float(np.mean(metal[y+y0:y+y0+hh,x0:x1]))
                    if w >= (x1-x0)*.60 and hh >= 3 and area >= max(9, (x1-x0)*2) and continuous >= .85:
                        poly = points([[x0-3, y+y0-3], [x1+3, y+y0-3], [x1+3, y+y0+hh+3], [x0-3, y+y0+hh+3]], inv)
                        finding('疑似焊锡桥连', row['component'], poly,
                                {'row': row['id'], 'adjacent_positions': [index+1,index+2], 'added_bright_area_px': area,
                                 'basis': '新增低饱和亮区横跨原本分离的相邻引脚间隙；需人工确认导电连接'}, .86)
                        break
            for index, peak in enumerate(row['peaks']):
                x0, x1 = max(0, round(peak-pitch*.28)), min(g.shape[1], round(peak+pitch*.28)+1)
                rr = refmetal[y0:y1, x0:x1]
                reference_area = int(rr.sum())
                if reference_area < 20:
                    continue
                remaining = float(np.sum(metal[y0:y1,x0:x1] & rr))/reference_area
                changed = float(np.mean((row['gray'][y0:y1,x0:x1].astype(float)-g[y0:y1,x0:x1])[rr] > delta_threshold))
                if remaining < .32 and changed > .65:
                    poly = points([[x0, y0],[x1,y0],[x1,y1],[x0,y1]], inv)
                    finding('焊点／引脚外观缺失', row['component'], poly,
                            {'row':row['id'], 'position_in_row':index+1,'reference_metal_area_px':reference_area,
                             'remaining_fraction':remaining,'basis':'基准中可见的金属外观大幅减少；不能由照片确定虚焊或电气开路'}, .8)

        # Component appearance is compared only where a prior annotation exists;
        # unpopulated footprints are never inferred to be missing components.
        globally_unassessable = len(assessed) < max(1, len(self.rows)//2)
        for component in ([] if globally_unassessable else self.components):
            if 'header' in component['family']:
                continue
            poly = np.asarray(component['quad_px'], np.float64)
            x,y,w,hh = cv2.boundingRect(poly.astype(np.float32))
            x0,y0,x1,y1=max(0,x),max(0,y),min(self.size[0],x+w),min(self.size[1],y+hh)
            localmask = polygon_mask(self.gray.shape, poly)[y0:y1,x0:x1]>0
            localmask &= support[y0:y1,x0:x1]>250
            if localmask.sum() < 100:
                continue
            diff = cv2.absdiff(self.gray[y0:y1,x0:x1],normalized_gray[y0:y1,x0:x1])
            fraction=float(np.mean(diff[localmask]>delta_threshold))
            # Conservative gross-change gate; not fine solder grading.
            if fraction > .45 and float(np.mean(diff[localmask])) > 32:
                finding('元件外观明显变化', component['id'], poly,
                        {'changed_fraction':fraction,'basis':'已有元件区域相对正常基准出现大面积变化；可能为缺失、偏位、遮挡或反光，需复核'}, .72)

        # Avoid multiple overlapping body boxes and pin boxes being presented as
        # independent confirmations of the same physical defect.
        state = 'insufficient_coverage' if globally_unassessable and not findings else 'review_required' if findings else 'no_obvious_change'
        summary = ('照片清晰度、反光或可见范围不足，已停止整体外观判断；请重新拍摄' if state=='insufficient_coverage' else
                   '发现疑似变化，等待人工复核' if findings else '已检查区域未发现明显变化；不等同于焊接合格')
        result = {'version':'rgb-aoi-reference-v1', 'state':state,
                  'summary':summary,
                  'reference_sha256':self.sha,'test_sha256':digest(raw),
                  'test_native_size':list(image.shape[1::-1]),'board_size':list(self.size),
                  'test_native_to_board':combined.tolist(),'reference_native_to_board':self.R.tolist(),
                  'registration':registration,'photometric':{'gain':gain,'offset':offset},
                  'findings':findings,'assessed_rows':assessed,'skipped_rows':skipped,
                  'component_appearance_checked':not globally_unassessable,
                  'excluded':self.public_profile()['excluded'], 'sensitivity':sensitivity,
                  'coordinates':'reference rectified board pixels; native quads included for both source images',
                  'elapsed_ms':(time.perf_counter()-started)*1000,'electrical_continuity_tested':False,
                  'source':'uploaded RGB photograph; not enhanced fusion texture',
                  'real_defect_validation_complete':False}
        return result, board
