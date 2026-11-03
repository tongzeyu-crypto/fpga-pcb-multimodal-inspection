"""Integer ABI-3 reference. CPU timings are never reported as PL performance."""
from dataclasses import dataclass
from pathlib import Path
import numpy as np

def trunc_div(a,b):
    if not b:raise ValueError('zero area')
    return (abs(a)//abs(b))*(-1 if a<0 else 1)

def setup(command,matrix,width,height,half=0):
    c=np.asarray(command,dtype=np.uint32).reshape(16)
    op=int(c[0])&255
    if op not in (1,2,3):raise ValueError('opcode')
    points=[]
    for k in range(1 if op==3 else 3):
        w=[int(x) if x<0x80000000 else int(x)-0x100000000 for x in c[4+k*4:7+k*4]]
        if op==2:q=[w[0]>>12,w[1]>>12,w[2]&65535]
        else:
            q=[sum(int(matrix[r*4+j])*w[j] for j in range(3))+int(matrix[r*4+3])*65536 for r in range(3)]
            q=[q[0]>>28,q[1]>>28,max(0,min(65535,q[2]>>16))]
        if not all(-32768<=v<=32767 for v in q[:2]):raise OverflowError('vertex')
        points.append([*q,int(c[7+k*4])&65535,int(c[7+k*4])>>16])
    if op==3:
        cx,cy,z,*_=points[0]
        dx=int(c[8].view(np.int32))>>13;dy=int(c[9].view(np.int32))>>13
        quad=[[cx-dx,cy-dy,z,0,0],[cx+dx,cy-dy,z,65535,0],
              [cx+dx,cy+dy,z,65535,65535],[cx-dx,cy+dy,z,0,65535]]
        points=[quad[0],quad[2 if half else 1],quad[3 if half else 2]]
    p=points
    area=(p[1][0]-p[0][0])*(p[2][1]-p[0][1])-(p[1][1]-p[0][1])*(p[2][0]-p[0][0])
    d=np.zeros(32,dtype=np.int32);d[:3]=c[:3].view(np.int32)
    if not area or (area<0 and int(c[0])&1024):return d
    if area<0:p[1],p[2]=p[2],p[1];area=-area
    x0=max(0,min(q[0] for q in p)>>4);x1=min(width-1,max(q[0] for q in p)>>4)
    y0=max(0,min(q[1] for q in p)>>4);y1=min(height-1,max(q[1] for q in p)>>4)
    if x0>x1 or y0>y1:return d
    d[3]=1;d[4:10]=[v for q in p for v in q[:2]];d[10:13]=p[0][2:]
    dx1=p[1][0]-p[0][0];dx2=p[2][0]-p[0][0]
    dy1=p[1][1]-p[0][1];dy2=p[2][1]-p[0][1]
    for k in range(3):
        a=p[1][k+2]-p[0][k+2];b=p[2][k+2]-p[0][k+2]
        gradients=[trunc_div((a*dy2-b*dy1)*4096,area),trunc_div((dx1*b-dx2*a)*4096,area)]
        if any(v<-(1<<31) or v>=(1<<31) for v in gradients):raise OverflowError('gradient')
        d[13+k*2:15+k*2]=gradients
    d[19:23]=[x0,x1,y0,y1]
    return d

def bins(descriptors,width,height,capacity=1048576):
    nx=(width+31)//32;ny=(height+31)//32
    lists=[[] for _ in range(nx*ny)]
    for i,d in enumerate(descriptors):
        if not d[3]:continue
        for y in range(int(d[21])//32,int(d[22])//32+1):
            for x in range(int(d[19])//32,int(d[20])//32+1):lists[y*nx+x].append(i)
    n=sum(map(len,lists))
    if n>capacity:raise OverflowError('bin references')
    headers=np.zeros((1024,4),dtype='<u4');refs=[]
    for i,lst in enumerate(lists):headers[i]=[len(refs),len(lst),len(refs),0];refs.extend(lst)
    return headers,np.asarray(refs,dtype='<u4')

def premultiply(image):
    a=image[...,3:4].astype(np.uint32)
    out=image.copy();out[...,:3]=((image[...,:3].astype(np.uint32)*a+127)//255).astype(np.uint8)
    return out

def pack_texture(image,make_mips=True):
    """BGRA input, premultiplied BEFORE filtering; all levels 128B aligned."""
    im=premultiply(np.asarray(image,dtype=np.uint8));levels=[];data=bytearray()
    while True:
        h,w=im.shape[:2];data.extend(b'\0'*((-len(data))%128));offset=len(data)
        padded=np.pad(im,((0,h%2),(0,w%2),(0,0)),mode='edge')
        tile=np.pad(im,((0,(-h)%4),(0,(-w)%8),(0,0)),mode='edge')
        packed=tile.reshape((h+3)//4,2,2,(w+7)//8,4,2,4).transpose(0,3,1,4,2,5,6).copy()
        data.extend(packed.tobytes());levels.append(dict(width=w,height=h,offset=offset))
        if not make_mips or (w==1 and h==1):break
        # Native integer box filter; clamp odd dimensions before downsampling.
        im=((padded[0::2,0::2].astype(np.uint32)+padded[0::2,1::2]+
             padded[1::2,0::2]+padded[1::2,1::2]+2)//4).astype(np.uint8)
        im=im[:max(1,h//2),:max(1,w//2)]
    data.extend(b'\0'*((-len(data))%128))
    return bytes(data),levels

def texel_address(base,width,x,y):
    return base+((y//4)*((width+7)//8)+x//8)*128+((y//2)%2)*64+((x//2)%4)*16+(y%2)*8+(x%2)*4

def bilinear(image,u,v):
    h,w=image.shape[:2]
    fx=u*(w-1);fy=v*(h-1);x=fx>>16;y=fy>>16;ax=(fx>>8)&255;ay=(fy>>8)&255
    a=image[y,x].astype(np.int64);b=image[y,min(w-1,x+1)].astype(np.int64)
    c=image[min(h-1,y+1),x].astype(np.int64);d=image[min(h-1,y+1),min(w-1,x+1)].astype(np.int64)
    p=(a*(256-ax)+b*ax+128)>>8;q=(c*(256-ax)+d*ax+128)>>8
    return ((p*(256-ay)+q*ay+128)>>8).astype(np.uint8)

def render(descriptors,width,height,textures,alpha=179,background=0xff0d1722,mip_levels=None):
    frame=np.full((height,width),background,dtype=np.uint32)
    depth=np.full((height,width),65535,dtype=np.uint16);ids=np.zeros((height,width),dtype=np.uint16)
    for d in descriptors:
        if not d[3]:continue
        p=d[4:10].astype(np.int64).reshape(3,2);flags=int(d[0]);sprite=(flags&255)==3
        selected=textures
        if mip_levels is not None:
            selected={};derivative=max(abs(int(v)) for v in d[15:19])
            for name,pyramid in mip_levels.items():
                level=0;footprint=derivative*max(pyramid[0].shape[:2])
                while footprint>33554431 and level+1<len(pyramid) and max(pyramid[level].shape[:2])>1:
                    footprint>>=1;level+=1
                selected[name]=pyramid[level]
        yy,xx=np.mgrid[d[21]:d[22]+1,d[19]:d[20]+1];px=xx*16+8;py=yy*16+8
        inside=np.ones(xx.shape,bool)
        for k in range(3):
            a=p[(k+1)%3];b=p[(k+2)%3]
            e=(b[0]-a[0])*(py-a[1])-(b[1]-a[1])*(px-a[0])
            inc=b[1]<a[1] or (b[1]==a[1] and b[0]>a[0]);inside&=(e>=0 if inc else e>0)
        attrs=[]
        for k in range(3):
            val=(int(d[10+k])*256+((int(d[13+k*2])*(px-p[0,0])+int(d[14+k*2])*(py-p[0,1]))>>4))>>8
            attrs.append(np.clip(val,0,65535))
        for row,col in zip(*np.nonzero(inside)):
            x=int(xx[row,col]);y=int(yy[row,col]);z,u,v=(int(a[row,col]) for a in attrs)
            if z>depth[y,x]:continue
            word=int(d[1])&0xffffffff
            src=np.array([(word>>(8*c))&255 for c in range(4)],dtype=np.int64)
            if flags&256:
                src=bilinear(selected['ground' if flags&16384 else 'rgb'],u,v).astype(np.int64)
                if flags&512:
                    heat=bilinear(selected['thermal'],u,v).astype(np.int64)
                    a=(int(heat[3])*alpha+127)//255
                    src[:3]=(src[:3]*(255-a)+127)//255+(((heat[:3]*alpha+127)//255)*int(src[3])+127)//255
            else:src[:3]=(src[:3]*int(src[3])+127)//255
            if sprite:
                r=(u-32768)**2+(v-32768)**2
                radial=0 if r>=1073741824 else 255-((r*255)>>30)
                src=(src*radial+127)//255
            if not src[3]:continue
            dst=np.array([(int(frame[y,x])>>(8*c))&255 for c in range(3)],dtype=np.int64)
            rgb=np.minimum(255,src[:3]+(dst if sprite else (dst*(255-int(src[3]))+127)//255))
            frame[y,x]=0xff000000|sum(int(rgb[c])<<(8*c) for c in range(3))
            if not sprite:depth[y,x]=z;ids[y,x]=int(d[2])
    return frame,depth,ids
