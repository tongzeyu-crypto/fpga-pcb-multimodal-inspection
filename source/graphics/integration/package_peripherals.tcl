# Static catalog IP avoids the legacy module-reference GUI interpreter.
foreach kind {dvi adc} {
 create_project ${kind}_package ${kind}_package_project -part xc7z020clg400-1 -force
 if {$kind eq "dvi"} {
  set phy vendor_7020_1g/FPGA_PL/hdmi_colorbar/hdmi_colorbar.srcs/sources_1/new
  foreach name {asyn_rst_syn dvi_encoder serializer_10_to_1 dvi_transmitter_top} {read_verilog $phy/$name.v}
  set_property top dvi_transmitter_top [current_fileset]
 } else {
  read_verilog adc_verified/adc_bringup.v
  create_ip -name ila -vendor xilinx.com -library ip -module_name adc_ila
  set_property -dict [list CONFIG.C_NUM_OF_PROBES {1} CONFIG.C_PROBE0_WIDTH {32} CONFIG.C_DATA_DEPTH {1024} CONFIG.C_INPUT_PIPE_STAGES {2}] [get_ips adc_ila]
  create_ip -name vio -vendor xilinx.com -library ip -module_name adc_vio
  set_property -dict [list CONFIG.C_NUM_PROBE_IN {0} CONFIG.C_NUM_PROBE_OUT {1} CONFIG.C_PROBE_OUT0_WIDTH {1} CONFIG.C_PROBE_OUT0_INIT_VAL {0x0}] [get_ips adc_vio]
  generate_target all [get_ips {adc_ila adc_vio}]
  set_property generate_synth_checkpoint false [get_files {*/adc_ila.xci */adc_vio.xci}]
  set_property top adc_bringup [current_fileset]
 }
 update_compile_order -fileset sources_1
 ipx::package_project -root_dir packaged_${kind} -vendor pcb.local -library graphics -taxonomy /UserIP -import_files -set_current true
 set core [ipx::current_core]
 set_property name ${kind}3 $core
 set_property version 3.0 $core
 ipx::infer_bus_interfaces xilinx.com:signal:clock_rtl:1.0 $core
 ipx::infer_bus_interfaces xilinx.com:signal:reset_rtl:1.0 $core
 foreach {port frequency} {pclk 74250000 pclk_x5 371250000 board_clk 25000000} {
  set bus [ipx::get_bus_interfaces $port -of_objects $core]
  if {[llength $bus]} {
   set parameter [ipx::get_bus_parameters FREQ_HZ -of_objects $bus]
   if {![llength $parameter]} {set parameter [ipx::add_bus_parameter FREQ_HZ $bus]}
   set_property value $frequency $parameter
  }
 }
 ipx::create_xgui_files $core
 ipx::update_checksums $core
 ipx::check_integrity -quiet $core
 ipx::save_core $core
 close_project
}
