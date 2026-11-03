set_param general.maxThreads 2
set_param synth.maxThreads 1
create_project graphics gp -part xc7z020clg400-1 -force
read_verilog -sv {C:/Users/admin/AppData/Local/Temp/p2hw-fix-r2/rtl/g3_pkg.sv}
read_verilog -sv {C:/Users/admin/AppData/Local/Temp/p2hw-fix-r2/rtl/g3_axi_device.sv}
read_verilog -sv {C:/Users/admin/AppData/Local/Temp/p2hw-fix-r2/rtl/g3_axi_fabric.sv}
read_verilog -sv {C:/Users/admin/AppData/Local/Temp/p2hw-fix-r2/rtl/g3_bin_reader.sv}
read_verilog -sv {C:/Users/admin/AppData/Local/Temp/p2hw-fix-r2/rtl/g3_binner.sv}
read_verilog -sv {C:/Users/admin/AppData/Local/Temp/p2hw-fix-r2/rtl/g3_device.sv}
read_verilog -sv {C:/Users/admin/AppData/Local/Temp/p2hw-fix-r2/rtl/g3_engine.sv}
read_verilog -sv {C:/Users/admin/AppData/Local/Temp/p2hw-fix-r2/rtl/g3_mul.sv}
read_verilog -sv {C:/Users/admin/AppData/Local/Temp/p2hw-fix-r2/rtl/g3_ram_sdp.sv}
read_verilog -sv {C:/Users/admin/AppData/Local/Temp/p2hw-fix-r2/rtl/g3_ram_tdp.sv}
read_verilog -sv {C:/Users/admin/AppData/Local/Temp/p2hw-fix-r2/rtl/g3_raster_pair.sv}
read_verilog -sv {C:/Users/admin/AppData/Local/Temp/p2hw-fix-r2/rtl/g3_resolve.sv}
read_verilog -sv {C:/Users/admin/AppData/Local/Temp/p2hw-fix-r2/rtl/g3_setup.sv}
read_verilog -sv {C:/Users/admin/AppData/Local/Temp/p2hw-fix-r2/rtl/g3_shader.sv}
read_verilog -sv {C:/Users/admin/AppData/Local/Temp/p2hw-fix-r2/rtl/g3_shader_math.sv}
read_verilog -sv {C:/Users/admin/AppData/Local/Temp/p2hw-fix-r2/rtl/g3_shader_pair.sv}
read_verilog -sv {C:/Users/admin/AppData/Local/Temp/p2hw-fix-r2/rtl/g3_tex_cache.sv}
read_verilog -sv {C:/Users/admin/AppData/Local/Temp/p2hw-fix-r2/rtl/g3_tile_store.sv}
read_verilog -sv {C:/Users/admin/AppData/Local/Temp/p2hw-fix-r2/rtl/gfx_div.sv}
read_verilog -sv {C:/Users/admin/AppData/Local/Temp/p2hw-fix-r2/rtl/gfx_vertex.sv}
set_property file_type Verilog [get_files *g3_axi_device.sv]
source integration/package_ip.tcl
close_project
create_project scan sp -part xc7z020clg400-1 -force
read_verilog -sv rtl/g3_cursor_rom.sv
read_verilog -sv rtl/g3_line_ram.sv
read_verilog -sv rtl/g3_scanout.sv
read_verilog integration/g3_scanout_axi.sv
set_property file_type Verilog [get_files *g3_scanout_axi.sv]
source integration/package_scanout.tcl
close_project
create_project dvi_pkg dvi_project -part xc7z020clg400-1 -force
read_verilog vendor_7020_1g/FPGA_PL/hdmi_colorbar/hdmi_colorbar.srcs/sources_1/new/asyn_rst_syn.v
read_verilog vendor_7020_1g/FPGA_PL/hdmi_colorbar/hdmi_colorbar.srcs/sources_1/new/dvi_encoder.v
read_verilog vendor_7020_1g/FPGA_PL/hdmi_colorbar/hdmi_colorbar.srcs/sources_1/new/serializer_10_to_1.v
read_verilog vendor_7020_1g/FPGA_PL/hdmi_colorbar/hdmi_colorbar.srcs/sources_1/new/dvi_transmitter_top.v
set_property top dvi_transmitter_top [current_fileset]
update_compile_order -fileset sources_1
ipx::package_project -root_dir packaged_dvi -vendor pcb.local -library graphics -taxonomy /UserIP -import_files -set_current true
set core [ipx::current_core]
set_property name dvi3 $core
set_property version 3.0 $core
ipx::infer_bus_interfaces xilinx.com:interface:aximm_rtl:1.0 $core
ipx::infer_bus_interfaces xilinx.com:signal:clock_rtl:1.0 $core
ipx::infer_bus_interfaces xilinx.com:signal:reset_rtl:1.0 $core
ipx::create_xgui_files $core
ipx::update_checksums $core
ipx::check_integrity -quiet $core
ipx::save_core $core
close_project
create_project adc_pkg adc_project -part xc7z020clg400-1 -force
read_verilog -sv compute/pcb_adc_capture.sv
read_verilog -sv compute/pcb_adc_axi.sv
set_property top pcb_adc_axi [current_fileset]
update_compile_order -fileset sources_1
ipx::package_project -root_dir packaged_adc -vendor pcb.local -library graphics -taxonomy /UserIP -import_files -set_current true
set core [ipx::current_core]
set_property name adc3 $core
set_property version 3.0 $core
ipx::infer_bus_interfaces xilinx.com:interface:aximm_rtl:1.0 $core
ipx::infer_bus_interfaces xilinx.com:signal:clock_rtl:1.0 $core
ipx::infer_bus_interfaces xilinx.com:signal:reset_rtl:1.0 $core
ipx::associate_bus_interfaces -busif s_axi -clock clk $core
set map [ipx::get_memory_maps s_axi -of_objects $core]
if {![llength $map]} {set map [ipx::add_memory_map s_axi $core]}
set block [ipx::get_address_blocks Reg -of_objects $map]
if {![llength $block]} {set block [ipx::add_address_block Reg $map]}
set_property -dict {range 131072 width 32 usage register} $block
set_property slave_memory_map_ref s_axi [ipx::get_bus_interfaces s_axi -of_objects $core]
ipx::create_xgui_files $core
ipx::update_checksums $core
ipx::check_integrity -quiet $core
ipx::save_core $core
close_project
create_project ai_pkg ai_project -part xc7z020clg400-1 -force
read_verilog -sv compute/pcb_ai_core.sv
read_verilog -sv compute/pcb_ai_axi.sv
set_property top pcb_ai_axi [current_fileset]
update_compile_order -fileset sources_1
ipx::package_project -root_dir packaged_ai -vendor pcb.local -library graphics -taxonomy /UserIP -import_files -set_current true
set core [ipx::current_core]
set_property name ai1 $core
set_property version 1.0 $core
ipx::infer_bus_interfaces xilinx.com:interface:aximm_rtl:1.0 $core
ipx::infer_bus_interfaces xilinx.com:signal:clock_rtl:1.0 $core
ipx::infer_bus_interfaces xilinx.com:signal:reset_rtl:1.0 $core
ipx::associate_bus_interfaces -busif s_axi -clock clk $core
set map [ipx::get_memory_maps s_axi -of_objects $core]
if {![llength $map]} {set map [ipx::add_memory_map s_axi $core]}
set block [ipx::get_address_blocks Reg -of_objects $map]
if {![llength $block]} {set block [ipx::add_address_block Reg $map]}
set_property -dict {range 262144 width 32 usage register} $block
set_property slave_memory_map_ref s_axi [ipx::get_bus_interfaces s_axi -of_objects $core]
ipx::create_xgui_files $core
ipx::update_checksums $core
ipx::check_integrity -quiet $core
ipx::save_core $core
close_project
create_project demo_pkg demo_project -part xc7z020clg400-1 -force
read_verilog -sv demo_compute/pcb_scalar.sv
read_verilog -sv demo_compute/pcb_demo_coeff.sv
read_verilog -sv demo_compute/pcb_demo_core.sv
read_verilog -sv demo_compute/pcb_demo_axi.sv
set_property top pcb_demo_axi [current_fileset]
update_compile_order -fileset sources_1
ipx::package_project -root_dir packaged_demo -vendor pcb.local -library graphics -taxonomy /UserIP -import_files -set_current true
set core [ipx::current_core]
set_property name demo1 $core
set_property version 1.0 $core
ipx::infer_bus_interfaces xilinx.com:interface:aximm_rtl:1.0 $core
ipx::infer_bus_interfaces xilinx.com:signal:clock_rtl:1.0 $core
ipx::infer_bus_interfaces xilinx.com:signal:reset_rtl:1.0 $core
ipx::associate_bus_interfaces -busif s_axi -clock clk $core
set map [ipx::get_memory_maps s_axi -of_objects $core]
if {![llength $map]} {set map [ipx::add_memory_map s_axi $core]}
set block [ipx::get_address_blocks Reg -of_objects $map]
if {![llength $block]} {set block [ipx::add_address_block Reg $map]}
set_property -dict {range 65536 width 32 usage register} $block
set_property slave_memory_map_ref s_axi [ipx::get_bus_interfaces s_axi -of_objects $core]
ipx::create_xgui_files $core
ipx::update_checksums $core
ipx::check_integrity -quiet $core
ipx::save_core $core
close_project
exit
