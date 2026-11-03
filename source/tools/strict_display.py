"""Remove fixture data synthesis and cross-board fallback in submission renderer."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=ROOT/'runtime/display/driver/full_scene.h';s=p.read_text(encoding='utf8')
    s=s.replace('FullAoi aoi;','FullAoi aoi;\n unsigned available_modalities=0;std::string capture_identity;')
    a=s.index('  dcdc_fixture=bool(');b=s.index('  heights.resize(',a)
    s=s[:a]+'''  std::ifstream state(root+"/capture-state.txt");
  if(!(state>>available_modalities>>capture_identity))throw std::runtime_error("source-verified capture-state required");
  dcdc_fixture=bool(std::ifstream(root+"/dcdc.flag"));
  std::ifstream frequency(root+"/frequency.txt");if(frequency.good())frequency>>df>>frequency_max;
  auto h=full_read<uint32_t>(root+"/full.meta");if(h.size()!=12||h[0]!=0x48444631)throw std::runtime_error("full scene identity");std::copy(h.begin(),h.end(),meta);
  auto gs=full_read<FullGlyph>(root+"/glyphs.bin");for(const auto &g:gs)glyphs[g.code]=g;
  model=full_read<gfx_command>(root+"/model.bin");flat=full_read<gfx_command>(root+"/flat.bin");
  points=full_read<FullPoint>(root+"/points.f32");psd=full_read<float>(root+"/psd.f32");
  if(points.empty()||meta[4]<2||psd.size()!=2*points.size()*meta[4])throw std::runtime_error("verified scene shapes");
  std::ifstream layout(root+"/raw-layout.txt");for(auto &r:raw_rects)for(double &q:r)if(!(layout>>q))throw std::runtime_error("raw atlas layout");
  if(available_modalities&4){
   raw_dc_frequency=full_read<float>(root+"/raw-dcdc-frequency.f32");raw_dc_psd=full_read<float>(root+"/raw-dcdc-psd.f32");
   auto xy=full_read<float>(root+"/raw-dcdc-coordinates.f32");
   if(raw_dc_frequency.size()!=meta[4]||raw_dc_psd.size()!=points.size()*meta[4]||xy.size()!=points.size()*2)throw std::runtime_error("raw spectrum dimensions");
   for(size_t i=0;i<points.size();i++){raw_dc_x.push_back(xy[i*2]);raw_dc_y.push_back(xy[i*2+1]);}
   std::sort(raw_dc_x.begin(),raw_dc_x.end());raw_dc_x.erase(std::unique(raw_dc_x.begin(),raw_dc_x.end()),raw_dc_x.end());
   std::sort(raw_dc_y.begin(),raw_dc_y.end());raw_dc_y.erase(std::unique(raw_dc_y.begin(),raw_dc_y.end()),raw_dc_y.end());
   for(double y:raw_dc_y)for(double x:raw_dc_x){int found=-1;for(size_t i=0;i<points.size();i++)if(xy[i*2]==x&&xy[i*2+1]==y){if(found!=-1)throw std::runtime_error("duplicate coordinate");found=i;}if(found<0)throw std::runtime_error("missing coordinate");raw_dc_grid.push_back(found);}
  }
  for(const auto &point:points){xs.push_back(point.x);ys.push_back(point.y);}
  std::sort(xs.begin(),xs.end());xs.erase(std::unique(xs.begin(),xs.end()),xs.end());std::sort(ys.begin(),ys.end());ys.erase(std::unique(ys.begin(),ys.end()),ys.end());
  // wx/wz are explicit mechanical coordinates. No stretching to the RGB board.
''' +s[b:]
    a=s.index(' double base(');b=s.index(' template<class V>void refresh(',a)
    s=s[:a]+''' double base(int p,int k,int)const{if(!(available_modalities&4))throw std::runtime_error("ADC missing");return psd.at(size_t(p)*meta[4]+k);}
''' +s[b:]
    a=s.index(' void make_sequence(');b=s.index(' template<class V>',a)
    s=s[:a]+''' void make_sequence(int,int){throw std::runtime_error("No real time sequence in capture; synthetic sequence disabled");}
''' +s[b:]
    needle='  if(v.mode>=13){FullDraw d(glyphs);raw_view(d,v);'
    guard='''  unsigned needed=(v.mode==0||v.mode==1)?11:(v.mode==3||v.mode==6||v.mode==15)?4:v.mode==13?1:v.mode==14?2:0;
  if((available_modalities&needed)!=needed||(v.mode==12&&!aoi.available)||v.mode==8||v.mode==9){
   FullDraw d(glyphs);d.rect(0,0,1280,720,0xff0d1722);d.rect(0,0,1280,54,0xff14242f);
   d.text("桌面PCB多模态检测系统",18,10,26);d.text("等待板端原始采集或正常参考",300,290,24);
   d.text("缺少输入或标定，当前页面已禁用",300,330,20);
   if(include_hud){sidebar(d,v);board_control(d,v);}d.commands.push_back(gfx_command{});return d.commands;
  }
'''
    if needle not in s:raise ValueError('build anchor')
    s=s.replace(needle,guard+needle)
    # Rendering 3D RGB/thermal is allowed; EMI association awaits mechanical model calibration.
    s=s.replace('if(v.emi&&v.mode!=10&&v.mode!=11){','if(v.emi&&v.mode!=0&&v.mode!=1&&v.mode!=10&&v.mode!=11){')
    s=s.replace('  refresh(v);FullDraw','  if(available_modalities&4)refresh(v);FullDraw')
    s=s.replace('if(v.mode!=10&&v.mode!=11)for(size_t i=0;i<points.size();i++)','if((available_modalities&4)&&v.mode!=0&&v.mode!=1&&v.mode!=10&&v.mode!=11)for(size_t i=0;i<points.size();i++)')
    p.write_text(s,encoding='utf8',newline='\n')
    p=ROOT/'runtime/display/driver/full_state.h';s=p.read_text(encoding='utf8');s=s.replace('n==5||n==10||n==11','n==2||n==4||n==5||n==7||n==8||n==9||n==10||n==11');s=s.replace('if(n<0||n>2)return false;v.scenario=n;','if(n!=0)return false;v.scenario=0;');p.write_text(s,encoding='utf8',newline='\n')
    p=ROOT/'runtime/display/driver/full_raw.h';s=p.read_text(encoding='utf8').replace('raw_image(d,v,0,v.raw_board?2:0','raw_image(d,v,0,0');p.write_text(s,encoding='utf8',newline='\n')
    p=ROOT/'runtime/display/driver/gfx3_runtime.cpp';s=p.read_text(encoding='utf8');s=s.replace('return full_scenes[board?1:0]?full_scenes[board?1:0]:full_scene;','if(!full_scenes[board?1:0])throw std::runtime_error("selected board has no scene");return full_scenes[board?1:0];')
    s=s.replace('"/tmp/pcb-aoi-bridge-v4i"','root+"/aoi-display"')
    s=s.replace('<<"{\\"synthetic\\":"<<(v.raw_board?"false":"true")','<<"{\\"synthetic\\":false"')
    # Depth is requested only when the matching candidate advertises support.
    s=s.replace('objects[3],thumbs[3];','objects[3],thumbs[3],depths[3];')
    s=s.replace('thumbs[k]=allocate(GFX3_PREVIEW,640*360*4);','thumbs[k]=allocate(GFX3_PREVIEW,640*360*4);if(caps.features&GFX3_FEAT_DEPTH)depths[k]=allocate(GFX3_DEPTH,1280*720*2);')
    needle='j.thumbnail=thumbs['
    # The opt-in depth API is used by the standalone frame pipeline; GUI adapter
    # integration status is reported separately instead of pretending completion.
    p.write_text(s,encoding='utf8',newline='\n')
if __name__=='__main__':main()
