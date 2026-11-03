set_property top g3_axi_device [current_fileset]
ipx::package_project -root_dir packaged_ip -vendor pcb.local -library graphics -taxonomy /UserIP -import_files -set_current true
set core [ipx::current_core]
set_property name graphics3 $core
set_property version 3.0 $core
set_property display_name {PCB graphics ABI3} $core
ipx::infer_bus_interfaces xilinx.com:interface:aximm_rtl:1.0 $core
ipx::infer_bus_interfaces xilinx.com:signal:clock_rtl:1.0 $core
ipx::infer_bus_interfaces xilinx.com:signal:reset_rtl:1.0 $core
foreach bus {s_axi m_read_axi m_write_axi} {ipx::associate_bus_interfaces -busif $bus -clock clk $core}
set map [ipx::get_memory_maps s_axi -of_objects $core]
if {[llength $map]==0} {set map [ipx::add_memory_map s_axi $core]}
set block [ipx::get_address_blocks Reg -of_objects $map]
if {[llength $block]==0} {set block [ipx::add_address_block Reg $map]}
foreach extra [ipx::get_address_blocks -of_objects $map] {if {[get_property name $extra] ne "Reg"} {ipx::remove_address_block [get_property name $extra] $map}}
set_property -dict {range 65536 width 32 usage register} $block
set_property slave_memory_map_ref s_axi [ipx::get_bus_interfaces s_axi -of_objects $core]
ipx::create_xgui_files $core
ipx::update_checksums $core
ipx::check_integrity -quiet $core
ipx::save_core $core
