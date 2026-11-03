"""Bit-exact PDP2 numerical specification, also used in explicit offline mode.

This is an oracle, not a substitute selected when a PL device is missing.
All FFT inputs are signed ADC14. Rounding uses arithmetic right shifts.
"""
import math

def spectrum(samples, hann=True):
    n=len(samples)
    if n not in (64,128,256,512,1024,2048,4096) or any(x < -8192 or x > 8191 for x in samples):
        raise ValueError('64..4096 power-of-two ADC14 samples required')
    logn=n.bit_length()-1
    c=[round(16384*math.cos(2*math.pi*k/4096)) for k in range(4096)]
    s=[round(-16384*math.sin(2*math.pi*k/4096)) for k in range(4096)]
    window=[(16384-c[k*4096//n])>>1 if hann else 16384 for k in range(n)]
    mean=(sum(samples)<<16)>>logn
    a=[(((x<<16)-mean)*w>>14,0) for x,w in zip(samples,window)]
    half=n//2;step=4096//n
    while half:
        for start in range(0,n,2*half):
            for j in range(half):
                ar,ai=a[start+j];br,bi=a[start+j+half]
                dr=(ar-br)>>1;di=(ai-bi)>>1;p=j*step
                a[start+j]=((ar+br)>>1,(ai+bi)>>1)
                a[start+j+half]=((dr*c[p]-di*s[p])>>14,(dr*s[p]+di*c[p])>>14)
        half//=2;step*=2
    power=[]
    for k in range(n//2+1):
        address=int(f'{k:0{logn}b}'[::-1],2);ar,ai=a[address]
        power.append((ar*ar+ai*ai)*(1 if k in (0,n//2) else 2))
    return power,sum(w*w for w in window)

def psd(power,n,window_energy,frames,sample_rate):
    if frames<1 or window_energy<1 or sample_rate<=0:raise ValueError('invalid PSD metadata')
    scale=n*n*(1<<28)/((1<<32)*sample_rate*window_energy*frames)
    return [v*scale for v in power]
