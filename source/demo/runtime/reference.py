"""Independent integer oracle for the small PL demo, not the production pipeline."""
import math

def twiddles():
    return ([round(math.cos(2*math.pi*i/64)*16384) for i in range(64)],
            [round(-math.sin(2*math.pi*i/64)*16384) for i in range(64)])

def spectrum(samples):
    if len(samples)!=64 or any(v < -8192 or v > 8191 for v in samples):raise ValueError('64 signed ADC14 samples required')
    mean=sum(samples)>>6;c,s=twiddles();out=[]
    for k in range(33):
        real=sum((x-mean)*c[(k*n)%64] for n,x in enumerate(samples))>>20
        imag=sum((x-mean)*s[(k*n)%64] for n,x in enumerate(samples))>>20
        out.append(real*real+imag*imag)
    return out

def thermal(values,threshold_mc=40000):
    temperatures=[v*125//2-273150 for v in values]
    maximum=max(temperatures)
    return temperatures,dict(min_mc=min(temperatures),max_mc=maximum,
        max_index=temperatures.index(maximum),hot_count=sum(v>=threshold_mc for v in temperatures))

def preprocess(values,mode=0,base=4370,shift=2):
    if mode==0:return [((77*((v>>16)&255)+150*((v>>8)&255)+29*(v&255))>>8)-128 for v in values]
    return [max(0,min(255,(v-base)>>shift))-128 for v in values]
