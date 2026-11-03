"""One measurement-band order for the PL client, persisted data and UI."""
UI_BANDS_HZ=((200000,25000000),(200000,3000000),(3000000,10000000),(10000000,25000000),(450000,550000))
def band_key(lo,hi):return '%g-%gHz'%(lo,hi)
def band_bins(n=4096,fs=50000000):
    return [(min(n//2+1,(lo*n+fs-1)//fs),min(n//2+1,(hi*n+fs-1)//fs)) for lo,hi in UI_BANDS_HZ]
