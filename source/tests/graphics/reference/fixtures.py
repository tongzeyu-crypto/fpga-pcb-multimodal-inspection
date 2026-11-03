from pathlib import Path
import json,sys
import numpy as np
from scene import setup,render,pack_texture,premultiply,bins

def generate(out,large_texture=False):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    commands=[]
    def tri(points,flags=2|256|512,rgba=0xffffffff,obj=1):
        c=np.zeros(16,dtype='<u4');c[:3]=[flags,rgba,obj]
        for k,(x,y,z,u,v) in enumerate(points):c[4+k*4:8+k*4]=[int(x*65536)&0xffffffff,int(y*65536)&0xffffffff,z,u|(v<<16)]
        commands.append(c)
    tri([(0,0,50000,0,0),(64,0,50000,65535,0),(0,64,50000,0,65535)])
    tri([(64,0,50000,65535,0),(64,64,50000,65535,65535),(0,64,50000,0,65535)])
    tri([(16,16,10000,0,0),(40,16,10000,65535,0),(16,40,10000,0,65535)],flags=258,obj=2)
    tri([(40,16,10000,65535,0),(40,40,10000,65535,65535),(16,40,10000,0,65535)],flags=258,obj=2)
    tri([(8,8,60000,0,0),(56,8,60000,65535,0),(8,56,60000,0,65535)],flags=2,rgba=0xffff0000,obj=99)
    tri([(-10,50,12000,0,0),(14,50,12000,65535,0),(0,70,12000,0,65535)],flags=1,rgba=0xff22aa99,obj=7)
    tri([(48,44,8000,0,0),(62,44,8000,65535,0),(48,60,8000,0,65535)],flags=2,rgba=0x8060c020,obj=8)
    tri([(12,12,1000,0,0),(12,12,1000,0,0),(12,12,1000,0,0)],flags=2,rgba=0xffffffff,obj=90)
    tri([(12,12,1000,0,0),(12,30,1000,0,65535),(30,12,1000,65535,0)],flags=2|1024,rgba=0xffffffff,obj=91)
    c=np.zeros(16,dtype='<u4');c[:3]=[3,0x80ff5500,100];c[4:7]=[32*65536,32*65536,5000];c[8:10]=[24*65536,24*65536];commands.append(c)
    commands.append(np.zeros(16,dtype='<u4'))
    matrix=np.array([52429,-19661,0,393216,19661,52429,0,65536,0,0,65536,0],dtype='<i4')
    (out/'matrix.mem').write_text('\n'.join(f'{int(v)&0xffffffff:08x}' for v in matrix)+'\n')
    descriptors=[]
    for c in commands[:-1]:
        descriptors.append(setup(c,matrix,64,64))
        if c[0]&255==3:descriptors.append(setup(c,matrix,64,64,1))
    y,x=np.mgrid[:16,:16];rgb=np.stack([x*12+20,y*10+30,np.full_like(x,100),np.full_like(x,255)],-1).astype(np.uint8)
    rgb[0,0,3]=0
    y,x=np.mgrid[:8,:8];heat=np.stack([np.full_like(x,200),x*25,y*25,np.full_like(x,180)],-1).astype(np.uint8)
    images={'rgb':rgb,'ground':rgb,'thermal':heat}
    raw={};meta={}
    for name,im in images.items():raw[name],meta[name]=pack_texture(im)
    levels=None
    if large_texture:
        # Each valid test mip has a unique colour: selecting the wrong level or
        # truncating 2048 cannot accidentally pass with a constant texture.
        levels={};regions=[]
        for name,dim,base in [('rgb',2048,0x1000000),('thermal',1024,0x4000000)]:
            chain=[];offset=0;level=0
            while True:
                yy,xx=np.ogrid[:dim,:dim]
                image=np.empty((dim,dim,4),np.uint8)
                image[...,0]=(40+level*9+(xx*3+yy*5)%128)%256
                image[...,1]=(80+level*5+(xx*7+yy*3)%96)%256
                image[...,2]=(180-level*7+(xx+yy*11)%64)%256
                image[...,3]=255 if name=='rgb' else 180
                chain.append(premultiply(image))
                size=(((dim+1)//2*2)**2*4+127)&~127
                regions.append((base+offset,base+offset+size,dim,level,255 if name=='rgb' else 180))
                if dim==1:break
                offset+=size;dim=max(1,dim>>1);level+=1
            levels[name]=chain
        levels['ground']=levels['rgb']
        code='function automatic [31:0] texture_word(input logic [31:0] address);\n integer q,x,y,b,g,r,a;\n begin texture_word=0;\n'
        for start,end,dim,level,alpha in regions:
            code+=f" if(address>=32'h{start:08x}&&address<32'h{end:08x})begin q=address-32'h{start:08x}; x=((q>>7)%{(dim+7)//8})*8+((q>>4)&3)*2+((q>>2)&1);y=((q>>7)/{(dim+7)//8})*4+((q>>6)&1)*2+((q>>3)&1);if(x>{dim-1})x={dim-1};if(y>{dim-1})y={dim-1};a={alpha};b=({40+level*9}+(x*3+y*5)%128)%256;g=({80+level*5}+(x*7+y*3)%96)%256;r=({180-level*7}+(x+y*11)%64)%256;b=(b*a+127)/255;g=(g*a+127)/255;r=(r*a+127)/255;texture_word={{a[7:0],r[7:0],g[7:0],b[7:0]}};end\n"
        code+=' end\nendfunction\n';(out/'texture_read.svh').write_text(code)
    frame,z,ids=render(descriptors,64,64,{n:premultiply(im) for n,im in images.items()},mip_levels=levels)
    memory=np.zeros(32768,dtype='<u8')
    def put(address,data):
        b=memory.view(np.uint8);b[address:address+len(data)]=np.frombuffer(data,np.uint8)
    put(0x1000,np.asarray(commands,dtype='<u4').tobytes())
    for name,addr in [('rgb',0x30000),('ground',0x32000),('thermal',0x34000)]:put(addr,raw[name])
    (out/'memory.mem').write_text('\n'.join(f'{int(v):016x}' for v in memory)+'\n')
    (out/'expected.mem').write_text('\n'.join(f'{int(v):08x}' for v in frame.ravel())+'\n')
    (out/'expected-id.mem').write_text('\n'.join(f'{int(v):04x}' for v in ids.ravel())+'\n')
    (out/'expected-depth.mem').write_text('\n'.join(f'{int(v):04x}' for v in z.ravel())+'\n')
    np.asarray(descriptors,dtype='<i4').tofile(out/'expected-geometry.bin')
    headers,refs=bins(descriptors,64,64);headers.tofile(out/'expected-headers.bin');refs.tofile(out/'expected-refs.bin')
    (out/'fixture.json').write_text(json.dumps({'commands':len(commands),'triangles':len(descriptors),'refs':len(refs),'textures':meta},indent=2))
    return len(commands)

if __name__=='__main__':print(generate(sys.argv[1]))
