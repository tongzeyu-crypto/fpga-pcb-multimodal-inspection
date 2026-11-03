// Included inside FullScene. Coordinates and scalar temperatures are queried
// from the same source-bound raw matrix used to build the displayed thermal map.
std::string data_root,scan_token;
std::vector<float> band_rms,thermal_matrix;
std::vector<uint16_t> thermal_raw;
double thermal_map[9]={},thermal_world_scale=1;int thermal_width=0,thermal_height=0,peak_x=0,peak_y=0,hot_pixels=0;
double min_temperature=0,max_temperature=0;bool thermal_query_available=false;
void load_capture_data(const std::string &root){
 data_root=root;
 if(available_modalities&4){band_rms=full_read<float>(root+"/band-rms.f32");if(band_rms.size()!=points.size()*5)throw std::runtime_error("PL band RMS dimensions");for(float v:band_rms)if(!std::isfinite(v)||v<0)throw std::runtime_error("PL band RMS value");}
 std::ifstream map(root+"/thermal-map.txt");std::string magic;
 if(map>>magic&&magic=="THERMAL_MAP1"&&map>>thermal_width>>thermal_height>>thermal_world_scale){
  for(double &v:thermal_map)if(!(map>>v)||!std::isfinite(v))throw std::runtime_error("thermal mapping");
  thermal_matrix=full_read<float>(root+"/temperature.f32");thermal_raw=full_read<uint16_t>(root+"/temperature-raw.u16");
  if(thermal_matrix.size()!=256*192||thermal_raw.size()!=256*192||thermal_world_scale<=0)throw std::runtime_error("source temperature dimensions");
  std::ifstream stats(root+"/thermal-stats.txt");if(!(stats>>peak_x>>peak_y>>min_temperature>>max_temperature>>hot_pixels)||peak_x<0||peak_x>255||peak_y<0||peak_y>191)throw std::runtime_error("thermal statistics");
  thermal_query_available=true;
 }
}
double band_value(size_t point,int band)const{
 if(point>=points.size()||band<0||band>=5||band_rms.size()!=points.size()*5)throw std::runtime_error("PL RMS lookup");
 return band_rms[point*5+band];
}
bool poll_scan(){
 std::ifstream pointer(data_root+"/scan-current.txt");std::string token;if(!(pointer>>token)||token==scan_token)return false;
 if(token.empty()||token.size()>80||token.find_first_not_of("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")!=std::string::npos)throw std::runtime_error("scan generation path");
 std::string root=data_root+"/scan-results/"+token;std::ifstream ready(root+"/ready.txt");std::string magic,id;size_t n,bins,nx,ny;
 if(!(ready>>magic>>id>>n>>bins>>nx>>ny)||magic!="SCAN1"||id!=token||!n||n>1024||bins!=2049||nx*ny!=n)throw std::runtime_error("scan publication metadata");
 auto new_points=full_read<FullPoint>(root+"/points.f32");auto new_psd=full_read<float>(root+"/psd.f32");auto new_rms=full_read<float>(root+"/band-rms.f32");
 auto new_raw=full_read<float>(root+"/raw-dcdc-psd.f32");auto frequency=full_read<float>(root+"/raw-dcdc-frequency.f32");
 if(new_points.size()!=n||new_psd.size()!=2*n*bins||new_rms.size()!=n*5||new_raw.size()!=n*bins||frequency.size()!=bins)throw std::runtime_error("scan publication dimensions");
 for(float v:new_psd)if(!std::isfinite(v)||v<0)throw std::runtime_error("scan PSD value");for(float v:new_rms)if(!std::isfinite(v)||v<0)throw std::runtime_error("scan RMS value");
 std::vector<double> xx,yy;for(auto&p:new_points){if(!std::isfinite(p.x)||!std::isfinite(p.y))throw std::runtime_error("scan coordinate");xx.push_back(p.x);yy.push_back(p.y);}
 std::sort(xx.begin(),xx.end());xx.erase(std::unique(xx.begin(),xx.end()),xx.end());std::sort(yy.begin(),yy.end());yy.erase(std::unique(yy.begin(),yy.end()),yy.end());
 if(xx.size()!=nx||yy.size()!=ny)throw std::runtime_error("scan grid");std::vector<int> grid;
 for(double y:yy)for(double x:xx){int found=-1;for(size_t i=0;i<n;i++)if(new_points[i].x==x&&new_points[i].y==y){if(found>=0)throw std::runtime_error("duplicate scan point");found=i;}if(found<0)throw std::runtime_error("missing scan point");grid.push_back(found);}
 points=std::move(new_points);psd=std::move(new_psd);band_rms=std::move(new_rms);raw_dc_psd=std::move(new_raw);raw_dc_frequency=std::move(frequency);
 xs=xx;ys=yy;raw_dc_x=xx;raw_dc_y=yy;raw_dc_grid=std::move(grid);heights.assign(n,.1);
 meta[3]=n;meta[4]=bins;meta[5]=nx;meta[6]=ny;df=50000000./4096;frequency_max=25;available_modalities|=4;
 field_band=field_scenario=time_point=-1;scan_token=token;capture_identity="scan-"+token;return true;
}
template<class V>bool temperature_raw_at(V &v,int x,int y)const{
 v.temperature_valid=false;if(!thermal_query_available||x<0||x>=256||y<0||y>=192)return false;
 v.temperature_x=x;v.temperature_y=y;v.temperature_kelvin16=thermal_raw[y*256+x];
 v.temperature_c=v.temperature_kelvin16/16.-273.15;v.temperature_pl_c=thermal_matrix[y*256+x];v.temperature_valid=true;return true;
}
template<class V>bool temperature_board_at(V &v,double x,double y)const{
 if(!thermal_query_available||x<0||y<0||x>=thermal_width||y>=thermal_height){v.temperature_valid=false;return false;}
 double z=thermal_map[6]*x+thermal_map[7]*y+thermal_map[8];if(!std::isfinite(z)||std::abs(z)<1e-12){v.temperature_valid=false;return false;}
 v.temperature_board_x=x;v.temperature_board_y=y;
 return temperature_raw_at(v,int(std::nearbyint((thermal_map[0]*x+thermal_map[1]*y+thermal_map[2])/z)),int(std::nearbyint((thermal_map[3]*x+thermal_map[4]*y+thermal_map[5])/z)));
}
template<class V>bool temperature_world_at(V &v,double x,double z)const{return temperature_board_at(v,x/thermal_world_scale+thermal_width/2.,z/thermal_world_scale+thermal_height/2.);}
template<class V>bool temperature_image_pick(V &v,int x,int y)const{
 if(x<348||x>=860||y<156||y>=540)return false;double zoom=v.raw_zoom[0],u0=std::max(0.,.5-v.raw_x[0]-.5/zoom),u1=std::min(1.,.5-v.raw_x[0]+.5/zoom),v0=std::max(0.,.5-v.raw_y[0]-.5/zoom),v1=std::min(1.,.5-v.raw_y[0]+.5/zoom);
 return temperature_raw_at(v,std::min(255,int((u0+(x-348)/512.*(u1-u0))*256)),std::min(191,int((v0+(y-156)/384.*(v1-v0))*192)));
}
