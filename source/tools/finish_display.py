from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=ROOT/'runtime/display/driver/gfx3_runtime.cpp';s=p.read_text(encoding='utf8')
    s=s.replace('for(int mode:{0,1,2,3,4,6,7,8,9,12,13,14,15})','for(int mode:{0,1,3,6,12,13,14,15})')
    s=s.replace('\\"modes\\":13','\\"modes\\":8').replace('\\"native_bins\\":4097','\\"native_bins\\":'+ '"<<scene.meta[4]<<"')
    s=s.replace('historical RGB/thermal, measured DC-DC EMI with retained cutoff, estimated heights','source-verified raw recomputation; separate acquisition batches; prior geometry')
    s=s.replace('historical RGB/thermal, synthetic STM32 EMI, estimated heights','STM32 inputs unavailable; waiting state')
    s=s.replace('j.width=1280;j.height=720;j.stride=5120;j.flags=', 'j.width=1280;j.height=720;j.stride=5120;j.flags=')
    s=s.replace('if(layers)j.reserved[0]=f.layer->u.handle;','if(layers)j.reserved[0]=f.layer->u.handle;if(depths[frame]){j.flags|=GFX3_DEPTH_JOB;j.reserved[1]=depths[frame]->u.handle;}')
    anchor='   std::ostringstream s;s<<std::setprecision(8)<<"{\\"synthetic\\":false"'
    s=s.replace(anchor,'   if(!(full_for(v.raw_board)->available_modalities&4)){status=503;body="{\\"state\\":\\"waiting for Zynq ADC\\"}";}else{\n'+anchor)
    s=s.replace('s<<"]}";body=s.str();\n  }else if(request.compare(0,9,"POST /app")','s<<"]}";body=s.str();}\n  }else if(request.compare(0,9,"POST /app")')
    p.write_text(s,encoding='utf8',newline='\n')
    p=ROOT/'runtime/display/driver/full_scene.h';s=p.read_text(encoding='utf8').replace('等待板端原始采集或正常参考','WAITING FOR ZYNQ RAW / REFERENCE').replace('缺少输入或标定，当前页面已禁用','INPUT OR CALIBRATION MISSING');p.write_text(s,encoding='utf8',newline='\n')
if __name__=='__main__':main()
