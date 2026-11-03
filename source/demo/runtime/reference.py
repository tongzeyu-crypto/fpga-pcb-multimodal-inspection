"""Pixel specifications and the current PDP2 spectrum specification."""
import math

def twiddles():
    return ([round(math.cos(2*math.pi*i/64)*16384) for i in range(64)],
            [round(-math.sin(2*math.pi*i/64)*16384) for i in range(64)])

def spectrum(samples):
    from .fixed_reference import spectrum as fixed_spectrum
    return fixed_spectrum(samples)[0]

def thermal(values,threshold_mc=40000):
    temperatures=[v*125//2-273150 for v in values]
    maximum=max(temperatures)
    return temperatures,dict(min_mc=min(temperatures),max_mc=maximum,
        max_index=temperatures.index(maximum),hot_count=sum(v>=threshold_mc for v in temperatures))

def preprocess(values,mode=0,base=4370,shift=2):
    if mode in (0,2):return [((77*((v>>16)&255)+150*((v>>8)&255)+29*(v&255))>>8)-(128 if mode==0 else 0) for v in values]
    return [max(0,min(255,(v-base)>>shift))-128 for v in values]
