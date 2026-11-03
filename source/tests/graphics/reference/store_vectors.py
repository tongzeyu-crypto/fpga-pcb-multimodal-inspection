"""Independent integer reference for tile blend/depth/ID storage."""
from pathlib import Path
import random,json

def generate(root):
 root=Path(root);(root/'sim').mkdir(exist_ok=True);rng=random.Random(0x61a401)
 memory=[0x0000ffffff182838 for _ in range(2048)];commands=[]
 for n in range(4096):
  pair=(0 if n<64 else (last_pair if n%3 else rng.randrange(1024)));last_pair=pair
  page=pair//512;index=(pair%512)*2;mask=rng.randrange(4);sprite=int(n%7==0);ident=n+1
  zs=[];cs=[];old=memory[pair*2:pair*2+2]
  for lane in range(2):
   previous_z=(old[lane]>>32)&65535
   z=previous_z if n%5==0 else (max(0,previous_z-rng.randrange(200)) if n%4 else rng.randrange(65536))
   alpha=[0,1,127,128,254,255,rng.randrange(256)][n%7]
   color=(alpha<<24)|rng.randrange(1<<24);zs.append(z);cs.append(color)
   if (mask>>lane)&1 and alpha and z<=previous_z:
    rgb=0
    for k in range(3):
     a=(color>>(8*k))&255;b=(old[lane]>>(8*k))&255
     value=a+(b if sprite else (b*(255-alpha)+127)//255)
     rgb|=min(255,value)<<(8*k)
    high=(old[lane]>>32) if sprite else ((ident<<16)|z)
    memory[pair*2+lane]=(high<<32)|0xff000000|rgb
  row=[page,index,mask,sprite,ident,zs[0],zs[1],cs[0],cs[1],old[0]&0xffffffff,old[0]>>32,old[1]&0xffffffff,old[1]>>32]
  commands.extend(row)
 def save(name,words):(root/'sim'/name).write_text(''.join(f'{v:08x}\n' for v in words))
 save('store-input.mem',commands);save('store-expected.mem',[part for v in memory for part in (v&0xffffffff,v>>32)])
 (root/'fixture.json').write_text(json.dumps({'commands':4096,'pixels':2048,'seed':0x61a401,'independent_rounding':'(product+127)//255','includes':['same address hazards','both pages','different lanes','masked writes','equal and rejected depth','zero alpha','additive sprite saturation','component ID']},indent=2))
