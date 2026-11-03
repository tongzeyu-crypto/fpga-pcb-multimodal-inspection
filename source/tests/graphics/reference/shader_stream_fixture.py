"""Independent scalar shader oracle and mixed streaming/cache fixture."""
from pathlib import Path
import numpy as np
from scene import premultiply,pack_texture,bilinear

def generate(root):
 r=Path(root);rng=np.random.default_rng(4197)
 rgb=rng.integers(0,256,(128,256,4),dtype=np.uint8)
 heat=rng.integers(0,256,(32,64,4),dtype=np.uint8)
 raw=[pack_texture(a,False)[0] for a in (rgb,heat)]
 words=np.frombuffer(b"".join(raw),dtype="<u4")
 (r/'sim/stream-texture.mem').write_text("\n".join(f"{int(x):08x}" for x in words)+"\n")
 images=[premultiply(a) for a in (rgb,heat)];inputs=[];expected=[]
 def word(v):return sum(int(c)<<(8*k) for k,c in enumerate(v))
 for i in range(512):
  hot=i<128 or i>=384
  mask=3 if hot else int(rng.integers(0,4));tex=True if hot else i%5!=0;thermal=True if hot else i%3!=0;spr=False if hot else i%11==0
  u=[17000,17100] if hot else [int(x) for x in rng.integers(0,65536,2)]
  v=[24000,24100] if hot else [int(x) for x in rng.integers(0,65536,2)]
  z=[int(x) for x in rng.integers(0,65536,2)];old=[int(x) for x in rng.integers(0,2**63,2,dtype=np.uint64)]
  rgba=int(rng.integers(0,2**32));alpha=179 if hot else int(rng.integers(0,256));c=np.array([(rgba>>(8*k))&255 for k in range(4)],np.int64)
  fields=[(mask,2),(i,10)]+[(x,16) for x in z+u+v]+[(x,64) for x in old]+[(rgba,32),(int(tex),1),(int(thermal),1),(int(spr),1),(alpha,8)]
  packed=0;shift=0
  for value,bits in fields:packed|=value<<shift;shift+=bits
  inputs.append(packed);out=[]
  for a,b in zip(u,v):
   if tex and not spr:
    p=bilinear(images[0],a,b).astype(np.int64)
    if thermal:
     h=bilinear(images[1],a,b).astype(np.int64);ha=(int(h[3])*alpha+127)//255
     p[:3]=(p[:3]*(255-ha)+127)//255+(((h[:3]*alpha+127)//255)*int(p[3])+127)//255
   else:p=c.copy();p[:3]=(p[:3]*int(p[3])+127)//255
   if spr:
    distance=(a-32768)**2+(b-32768)**2;radial=0 if distance>=1073741824 else 255-((distance*255)>>30)
    p=(p*radial+127)//255
   out.append(word(p))
  expected.append(out[0]|(out[1]<<32))
 (r/'sim/stream-input.mem').write_text("\n".join(f"{x:070x}" for x in inputs)+"\n")
 (r/'sim/stream-expected.mem').write_text("\n".join(f"{x:016x}" for x in expected)+"\n")
