"""Board-side/replay numerical processing, no precomputed PSD inputs."""
import csv
from pathlib import Path
import numpy as np
FS=50_000_000
def thermal_decode(raw):
    if len(raw)!=196608:raise ValueError('thermal dual-plane length')
    p=np.frombuffer(raw,'<u2').reshape(2,192,256)
    if np.ptp(p[0])==0 or np.ptp(p[1])==0:raise ValueError('invalid thermal plane')
    return p[0],p[1].astype(np.float32)/16-273.15
def read_adc(path):
    path=Path(path)
    if path.suffix=='.u32':return np.frombuffer(path.read_bytes(),'<u4').copy()
    with path.open(encoding='utf-8-sig',newline='') as f:
        r=csv.reader(f);header=next(r);col=next(i for i,n in enumerate(header) if 'capture_word' in n)
        return np.array([int(row[col],16) for row in r if row and row[0].isdigit()],np.uint32)
def adc_decode(words):
    if len(words)!=16384:raise ValueError('ADC raw frame length')
    ph=(words>>15)&3;hb=(words>>20)&4095
    if np.any(((words>>19)&1)!=1) or np.any((np.diff(hb.astype(np.int64))&4095)!=1):raise ValueError('ADC transport integrity')
    if any(np.count_nonzero(ph==i)!=4096 for i in range(4)):raise ValueError('ADC phase count')
    channels=[]
    for phase in [1,3]:
        w=words[ph==phase]
        if np.any((w>>14)&1) or np.any((w>>17)&3):raise ValueError('ADC overrange/ground monitor')
        x=(w&16383).astype(np.int32);x=np.where(x>=8192,x-16384,x)
        if np.any((x==-8192)|(x==8191)):raise ValueError('ADC endpoint')
        channels.append(x)
    return np.array(channels)
def periodogram(x):
    x=np.asarray(x,np.float64);n=x.shape[-1]
    if n!=4096:raise ValueError('4096 channel samples required')
    x=x-x.mean(-1,keepdims=True);window=.5-.5*np.cos(2*np.pi*np.arange(n)/n)
    p=np.abs(np.fft.rfft(x*window,axis=-1))**2/(FS*np.sum(window**2));p[...,1:-1]*=2
    if not np.allclose(p.sum(-1)*FS/n,((x*window)**2).sum(-1)/(window**2).sum(),rtol=1e-10):raise ValueError('Parseval')
    return p
def spectrum_three(paths):
    if len(paths)!=3:raise ValueError('exactly three frames per mechanical point')
    return np.mean([periodogram(adc_decode(read_adc(p))) for p in paths],axis=0)
def bands(p):
    f=np.fft.rfftfreq(4096,1/FS)
    return {f'{lo:g}-{hi:g}Hz':np.sqrt(p[...,(f>=lo)&(f<hi)].sum(-1)*FS/4096).tolist() for lo,hi in [(2e5,3e6),(3e6,10e6),(10e6,20e6),(20e6,25e6),(2e5,25e6)]}
