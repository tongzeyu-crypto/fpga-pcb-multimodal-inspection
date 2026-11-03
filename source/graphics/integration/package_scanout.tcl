set_property top g3_scanout_axi [current_fileset]
ipx::package_project -root_dir packaged_scanout -vendor pcb.local -library graphics -taxonomy /UserIP -import_files -set_current true
set core [ipx::current_core]
set_property name scanout3 $core
set_property version 3.0 $core
set_property display_name {Compact 720p source / 1080p scanout} $core
ipx::infer_bus_interfaces xilinx.com:interface:aximm_rtl:1.0 $core
ipx::infer_bus_interfaces xilinx.com:signal:clock_rtl:1.0 $core
ipx::infer_bus_interfaces xilinx.com:signal:reset_rtl:1.0 $core
ipx::associate_bus_interfaces -busif m_axi -clock clk $core
ipx::create_xgui_files $core
ipx::update_checksums $core
ipx::check_integrity -quiet $core
ipx::save_core $core
