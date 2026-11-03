"""Independent integer specifications for the fixed technical-document contract."""
import math

def psd_q40(power,n,energy,frames,fs):
    return [(int(p)*n*n*(1<<36))//(fs*energy*frames) for p in power]

def band_rms_q16(psd,n,fs,bands):
    return [math.isqrt((sum(psd[lo:hi])*fs)>>(n.bit_length()-1+8)) for lo,hi in bands]

def jet(value):
    v=max(0,min(255,int(value)));components=[max(0,min(255,383-abs(4*v-c))) for c in (765,510,255)]
    return 0xff000000|(components[0]<<16)|(components[1]<<8)|components[2]

def image_words(task,words,mode=0,normalizer=1,low=0,high=100000,threshold=30):
    out=[]
    if task==6:
        if len(words)%5:raise ValueError('resize tuple')
        for k in range(0,len(words),5):
            a,b,c,d,f=words[k:k+5];fx=f&4095;fy=(f>>16)&4095
            h0=(a*(4096-fx)+b*fx+2048)>>12;h1=(c*(4096-fx)+d*fx+2048)>>12
            out.append((h0*(4096-fy)+h1*fy+2048)>>12)
    elif task==7:
        size=25 if mode>=4 else 9
        if len(words)%size:raise ValueError('neighborhood tuple')
        for k in range(0,len(words),size):
            v=words[k:k+size]
            if mode==0:out.append((sum(x*w for x,w in zip(v,[1,2,1,2,4,2,1,2,1]))+8)>>4)
            elif mode==1:
                gx=sum(x*w for x,w in zip(v,[-1,0,1,-2,0,2,-1,0,1]));gy=sum(x*w for x,w in zip(v,[-1,-2,-1,0,0,0,1,2,1]));out.append(math.isqrt(gx*gx+gy*gy))
            else:out.append(max(v) if mode&1 else min(v))
    elif task==8:
        if normalizer<=0 or min(words)<0:raise ValueError('normalization')
        out=[min(127,(v*128+normalizer//2)//normalizer) for v in words]
    elif task==9:
        if len(words)%3:raise ValueError('difference tuple')
        out=[255 if valid and abs(a-b)>threshold else 0 for a,b,valid in zip(words[::3],words[1::3],words[2::3])]
    elif task==10:
        if high<low:raise ValueError('color range')
        out=[jet(0 if high==low or v<=low else 255 if v>=high else ((v-low)*255+(high-low)//2)//(high-low)) for v in words]
        out=[v-(1<<32) if v>=1<<31 else v for v in out]
    else:raise ValueError('image task')
    return out

def decode_adc_words(words):
    if len(words)!=16384:raise ValueError('raw frame size')
    out=[];previous=None;counts=[0]*4
    for w in words:
        hb=(w>>20)&4095;phase=(w>>15)&3;v=w&16383
        if not ((w>>19)&1) or (previous is not None and hb!=((previous+1)&4095)):raise ValueError('raw transport')
        previous=hb;counts[phase]+=1
        if phase in (1,3):
            if w&(1<<14) or (w>>17)&3 or v in (8191,8192):raise ValueError('raw sample')
            value=v-16384 if v>=8192 else v;out.append(0x10000|((phase==3)<<17)|(value&65535))
        else:out.append(0)
    if counts!=[4096]*4:raise ValueError('raw phase counts')
    return out
