# New, independent Vivado 2018.3 design. Never opens/modifies the vendor project.
set_property XPM_LIBRARIES {XPM_FIFO} [current_project]
set vendor vendor_7020_1g/HZ_B2B_7z020/HZ_B2B_7z020.gen/sources_1/bd/system/hw_handoff/system_bd.tcl
set f [open $vendor];set original [read $f];close $f
set start [string first {  set processing_system7_0 [ create_bd_cell} $original]
set finish [string first { ] $processing_system7_0} $original $start]
if {$start<0||$finish<0} {error "Factory PS preset not found"}
set preset [string range $original $start [expr {$finish+24}]]
set f [open vendor_ps_source.tcl w];puts $f $preset;close $f
# DVI and ADC are unchanged static packaged IP.
create_bd_design board
eval $preset
set ps [get_bd_cells processing_system7_0]
# MIO, USB, UART, Ethernet, SD, QSPI and DDR are the factory preset. Unused
# EMIO/LCD/DVP IP is omitted; this design requires its own matching device tree.
set_property -dict [list CONFIG.PCW_EN_EMIO_GPIO {0} CONFIG.PCW_GPIO_EMIO_GPIO_ENABLE {0} CONFIG.PCW_I2C0_PERIPHERAL_ENABLE {0} CONFIG.PCW_I2C1_PERIPHERAL_ENABLE {0} CONFIG.PCW_EN_CLK1_PORT {1} CONFIG.PCW_FCLK1_PERIPHERAL_CLKSRC {IO PLL} CONFIG.PCW_FPGA1_PERIPHERAL_FREQMHZ {62.500} CONFIG.PCW_EN_CLK2_PORT {0} CONFIG.PCW_EN_CLK3_PORT {0} CONFIG.PCW_USE_S_AXI_HP2 {1} CONFIG.PCW_S_AXI_HP2_DATA_WIDTH {64} CONFIG.PCW_USE_S_AXI_HP0 {1} CONFIG.PCW_USE_S_AXI_HP1 {1} CONFIG.PCW_S_AXI_HP0_DATA_WIDTH {64} CONFIG.PCW_S_AXI_HP1_DATA_WIDTH {64}] $ps
# Demonstration profile: retain the original 100 MHz HDMI reference on FCLK0.
# All core/MMIO/HP AXI logic uses a separately configured 62.5 MHz FCLK1.
set core_mhz [get_property CONFIG.PCW_ACT_FPGA1_PERIPHERAL_FREQMHZ $ps]
if {abs($core_mhz-62.5)>0.001} {error "PS did not configure the requested demo clock: $core_mhz"}
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 -config {make_external "FIXED_IO, DDR" apply_board_preset "0" Master "Disable" Slave "Disable"} $ps
set gpu [create_bd_cell -type ip -vlnv pcb.local:graphics:graphics3:3.0 pcb_graphics]
set scan [create_bd_cell -type ip -vlnv pcb.local:graphics:scanout3:3.0 hdmi_scanout]
set dvi [create_bd_cell -type ip -vlnv pcb.local:graphics:dvi3:3.0 dvi]
set adc [create_bd_cell -type ip -vlnv pcb.local:graphics:adc3:3.0 adc]
set clock [create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz:6.0 hdmi_clock]
set_property -dict [list CONFIG.PRIM_IN_FREQ {100.000} CONFIG.NUM_OUT_CLKS {2} CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {74.250} CONFIG.CLKOUT2_USED {true} CONFIG.CLKOUT2_REQUESTED_OUT_FREQ {371.250} CONFIG.USE_RESET {false}] $clock
set rst [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 sys_reset]
set pixrst [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 pixel_reset]
# FCLK_RESET0_N is active low; unused aux_reset_in is tied to zero below.
# Specify both polarities instead of relying on generated core defaults.
# The explicit configuration passed simulation and the RAM boot. The older
# configuration did not independently reproduce the hang in reset simulation.
foreach reset_cell [list $rst $pixrst] {
 set_property -dict [list CONFIG.C_EXT_RESET_HIGH {0} CONFIG.C_AUX_RESET_HIGH {1}] $reset_cell
}
set c1 [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 one]
set_property CONFIG.CONST_VAL 1 $c1
set c0 [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 zero]
set_property CONFIG.CONST_VAL 0 $c0
connect_bd_net [get_bd_pins $ps/FCLK_CLK1] [get_bd_pins $ps/M_AXI_GP0_ACLK] [get_bd_pins $ps/S_AXI_HP0_ACLK] [get_bd_pins $ps/S_AXI_HP1_ACLK] [get_bd_pins $ps/S_AXI_HP2_ACLK] [get_bd_pins $gpu/clk] [get_bd_pins $scan/clk] [get_bd_pins $rst/slowest_sync_clk]
connect_bd_net [get_bd_pins $ps/FCLK_CLK0] [get_bd_pins $clock/clk_in1]
connect_bd_net [get_bd_pins $ps/FCLK_RESET0_N] [get_bd_pins $rst/ext_reset_in] [get_bd_pins $pixrst/ext_reset_in]
connect_bd_net [get_bd_pins $c1/dout] [get_bd_pins $rst/dcm_locked]
connect_bd_net [get_bd_pins $c0/dout] [get_bd_pins $rst/aux_reset_in] [get_bd_pins $rst/mb_debug_sys_rst] [get_bd_pins $pixrst/aux_reset_in] [get_bd_pins $pixrst/mb_debug_sys_rst]
connect_bd_net [get_bd_pins $rst/peripheral_aresetn] [get_bd_pins $gpu/rstn] [get_bd_pins $scan/rstn]
connect_bd_net [get_bd_pins $clock/clk_out1] [get_bd_pins $scan/pclk] [get_bd_pins $pixrst/slowest_sync_clk] [get_bd_pins $dvi/pclk]
connect_bd_net [get_bd_pins $clock/clk_out2] [get_bd_pins $dvi/pclk_x5]
connect_bd_net [get_bd_pins $clock/locked] [get_bd_pins $pixrst/dcm_locked]
connect_bd_net [get_bd_pins $pixrst/peripheral_aresetn] [get_bd_pins $scan/pixel_rstn] [get_bd_pins $dvi/reset_n]
connect_bd_net [get_bd_pins $scan/present_window] [get_bd_pins $gpu/vsync]
connect_bd_net [get_bd_pins $gpu/front_address] [get_bd_pins $scan/front_address]
connect_bd_net [get_bd_pins $gpu/native_view] [get_bd_pins $scan/native_view]
connect_bd_net [get_bd_pins $gpu/cursor_position] [get_bd_pins $scan/cursor_position]
connect_bd_net [get_bd_pins $gpu/layer_address] [get_bd_pins $scan/layer_address]
connect_bd_net [get_bd_pins $gpu/ui_quiet] [get_bd_pins $scan/ui_quiet]
connect_bd_net [get_bd_pins $scan/active_layer] [get_bd_pins $gpu/scan_active_layer]
connect_bd_net [get_bd_pins $scan/active_cursor] [get_bd_pins $gpu/scan_active_cursor]
connect_bd_net [get_bd_pins $scan/ui_drained] [get_bd_pins $gpu/scan_ui_drained]
connect_bd_net [get_bd_pins $scan/adopted] [get_bd_pins $gpu/scan_adopted]
connect_bd_net [get_bd_pins $scan/read_bytes] [get_bd_pins $gpu/scan_read_bytes]
connect_bd_net [get_bd_pins $scan/underflow_frames] [get_bd_pins $gpu/scan_underflows]
foreach p {video_rgb video_hsync video_vsync video_de} {
 set target $p;if {$p eq "video_rgb"} {set target video_din}
 connect_bd_net [get_bd_pins $scan/$p] [get_bd_pins $dvi/$target]
}
foreach p {tmds_clk_p tmds_clk_n tmds_data_p tmds_data_n} {make_bd_pins_external [get_bd_pins $dvi/$p]}
foreach p {board_clk adc_data adc_otr grounded_pads adc_clk adc_oeb adc_pwdn} {make_bd_pins_external [get_bd_pins $adc/$p]}
set gpio [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 scanout_status]
set_property -dict [list CONFIG.C_GPIO_WIDTH {32} CONFIG.C_ALL_INPUTS {1} CONFIG.C_IS_DUAL {1} CONFIG.C_GPIO2_WIDTH {32} CONFIG.C_ALL_INPUTS_2 {1}] $gpio
connect_bd_net [get_bd_pins $scan/underflow_frames] [get_bd_pins $gpio/gpio_io_i]
connect_bd_net [get_bd_pins $scan/displayed_address] [get_bd_pins $gpio/gpio2_io_i]
connect_bd_net [get_bd_pins $gpu/irq] [get_bd_pins $ps/IRQ_F2P]
proc mem_bridge {name master slave clock reset} {
 set ic [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 $name]
 set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {1}] $ic
 connect_bd_intf_net [get_bd_intf_pins $master] [get_bd_intf_pins $ic/S00_AXI]
 connect_bd_intf_net [get_bd_intf_pins $ic/M00_AXI] [get_bd_intf_pins $slave]
 foreach pin {ACLK S00_ACLK M00_ACLK} {connect_bd_net [get_bd_pins $clock] [get_bd_pins $ic/$pin]}
 foreach pin {ARESETN S00_ARESETN M00_ARESETN} {connect_bd_net [get_bd_pins $reset] [get_bd_pins $ic/$pin]}
}
mem_bridge gpu_reads $gpu/m_read_axi $ps/S_AXI_HP2 $ps/FCLK_CLK1 $rst/peripheral_aresetn
mem_bridge gpu_writes $gpu/m_write_axi $ps/S_AXI_HP0 $ps/FCLK_CLK1 $rst/peripheral_aresetn
mem_bridge display_memory $scan/m_axi $ps/S_AXI_HP1 $ps/FCLK_CLK1 $rst/peripheral_aresetn
set ctrl [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 control]
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {2}] $ctrl
connect_bd_intf_net [get_bd_intf_pins $ps/M_AXI_GP0] [get_bd_intf_pins $ctrl/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins $ctrl/M00_AXI] [get_bd_intf_pins $gpu/s_axi]
connect_bd_intf_net [get_bd_intf_pins $ctrl/M01_AXI] [get_bd_intf_pins $gpio/S_AXI]
foreach pin {ACLK S00_ACLK M00_ACLK M01_ACLK} {connect_bd_net [get_bd_pins $ps/FCLK_CLK1] [get_bd_pins $ctrl/$pin]}
foreach pin {ARESETN S00_ARESETN M00_ARESETN M01_ARESETN} {connect_bd_net [get_bd_pins $rst/peripheral_aresetn] [get_bd_pins $ctrl/$pin]}
connect_bd_net [get_bd_pins $ps/FCLK_CLK1] [get_bd_pins $gpio/s_axi_aclk]
connect_bd_net [get_bd_pins $rst/peripheral_aresetn] [get_bd_pins $gpio/s_axi_aresetn]
assign_bd_address
assign_bd_address -offset 0x43C00000 -range 0x10000 -target_address_space [get_bd_addr_spaces $ps/Data] [get_bd_addr_segs $gpu/s_axi/Reg]
assign_bd_address -offset 0x41200000 -range 0x10000 -target_address_space [get_bd_addr_spaces $ps/Data] [get_bd_addr_segs $gpio/S_AXI/Reg]
validate_bd_design
foreach reset_cell [list $rst $pixrst] {
 if {[get_property CONFIG.C_EXT_RESET_HIGH $reset_cell] != 0 || [get_property CONFIG.C_AUX_RESET_HIGH $reset_cell] != 1} {
  error "Reset polarity changed during propagation: $reset_cell"
 }
}
save_bd_design
write_bd_tcl -force board_recreate.tcl
set f [open address-map.txt w];foreach seg [get_bd_addr_segs] {puts $f "$seg [get_property OFFSET $seg] [get_property RANGE $seg]"};close $f
make_wrapper -files [get_files board.bd] -top
add_files -norecurse [glob project/integration.srcs/sources_1/bd/board/hdl/board_wrapper.v]
set_property top board_wrapper [current_fileset]
# External names are produced by make_bd_pins_external; normalize them in XDC.
set f [open board_pins.xdc w]
set adc_xdc [open adc_verified/adc_bringup.xdc];set text [read $adc_xdc];close $adc_xdc
foreach p {board_clk adc_data adc_otr grounded_pads adc_clk adc_oeb adc_pwdn} {regsub -all "\\m${p}\\M" $text ${p}_0 text}
puts $f $text
foreach {p pin} {tmds_clk_p J18 tmds_clk_n H18} {puts $f "set_property -dict {PACKAGE_PIN $pin IOSTANDARD TMDS_33} \[get_ports ${p}_0\]"}
foreach {p pin} {tmds_data_p_0[2] J20 tmds_data_n_0[2] H20 tmds_data_p_0[1] K19 tmds_data_n_0[1] J19 tmds_data_p_0[0] G19 tmds_data_n_0[0] G20} {puts $f "set_property -dict {PACKAGE_PIN $pin IOSTANDARD TMDS_33} \[get_ports {$p}\]"}
close $f
add_files -fileset constrs_1 board_pins.xdc
set f [open board_cdc.xdc w]
# Only the receiving first stage of each single-bit, three-flop synchronizer.
# Pixel data itself crosses through XPM's FIFO with its generated constraints.
puts $f {set_false_path -to [get_pins -hier -regexp {.*hdmi_scanout.*/vs_sync_reg\[0\]/D}]}
puts $f {set_false_path -to [get_pins -hier -regexp {.*hdmi_scanout.*/uf_sync_reg\[0\]/D}]}
# Gray buses are launched from source flops and cross via two-flop chains.
# They are not blanket false paths. Bound both inter-bit skew and latency.
foreach {gfx_gray_src gfx_gray_dst} {wgray wg0 rgray rg0} {
 # Expand here in ordinary Tcl: Vivado 2018.3 rejects foreach within XDC.
 puts $f [format {set_max_delay -datapath_only 10.000 -from [get_cells -hier -regexp {.*hdmi_scanout.*/%s_reg\[[0-9]+\]}] -to [get_pins -hier -regexp {.*hdmi_scanout.*/%s_reg\[[0-9]+\]/D}]} $gfx_gray_src $gfx_gray_dst]
 puts $f [format {set_bus_skew 10.000 -from [get_cells -hier -regexp {.*hdmi_scanout.*/%s_reg\[[0-9]+\]}] -to [get_pins -hier -regexp {.*hdmi_scanout.*/%s_reg\[[0-9]+\]/D}]} $gfx_gray_src $gfx_gray_dst]
}
puts $f {set_false_path -to [get_pins -hier -regexp {.*hdmi_scanout.*/mode_sync_reg\[0\]/D}]}
puts $f {set_false_path -to [get_pins -hier -regexp {.*hdmi_scanout.*/cursor_sync_reg\[0\]/D}]}
# Bundled payload is stable before the synchronized toggle and changes only in vertical blank.
puts $f {set_max_delay -datapath_only 20.000 -from [get_cells -hier -regexp {.*hdmi_scanout.*/active_cursor_reg\[[0-9]+\]}] -to [get_pins -hier -regexp {.*hdmi_scanout.*/pixel_cursor_reg\[[0-9]+\]/D}]}
close $f
add_files -fileset constrs_1 board_cdc.xdc
set_property synth_checkpoint_mode None [get_files board.bd]
generate_target all [get_files board.bd]
export_ip_user_files -of_objects [get_files board.bd] -no_script -sync -force -quiet
# The desktop's legacy Windows job launcher does not start cscript children.
# Run the same synthesis/implementation commands in this retained batch process.
update_compile_order -fileset sources_1
synth_design -top board_wrapper -part xc7z020clg400-1 -control_set_opt_threshold 16
set shader_instances [get_cells -hier -filter {REF_NAME == g3_shader}]
if {[llength $shader_instances] != 1} {error "Expected one shader checkpoint instance in the demonstration profile"}
foreach shader_cell $shader_instances {read_checkpoint -cell $shader_cell shader-synth.dcp}
# Independent OOC timing constraints must not cut the actual FCLK tree.
foreach shader_cell $shader_instances {
 set shader_clock [get_clocks -of_objects [get_pins $shader_cell/clk]]
 if {[llength $shader_clock] != 1 || [get_property NAME $shader_clock] ne "clk_fpga_1" || abs([get_property PERIOD $shader_clock]-16.0)>0.001} {error "Shader does not inherit the 62.5 MHz demo FCLK: $shader_cell $shader_clock"}
}
report_clocks -file board-clocks.rpt
set gfx_cdc_file [open board-gray-endpoints.txt w]
foreach {gfx_gray_src gfx_gray_dst} {wgray wg0 rgray rg0} {
 set gfx_from [get_cells -hier -regexp [format {.*hdmi_scanout.*/%s_reg\[[0-9]+\]} $gfx_gray_src]]
 set gfx_to [get_pins -hier -regexp [format {.*hdmi_scanout.*/%s_reg\[[0-9]+\]/D} $gfx_gray_dst]]
 if {[llength $gfx_from]!=4 || [llength $gfx_to]!=4} {error "Display Gray CDC endpoint identity mismatch"}
 puts $gfx_cdc_file "$gfx_gray_src: $gfx_from"
 puts $gfx_cdc_file "$gfx_gray_dst: $gfx_to"
}
close $gfx_cdc_file
report_utilization -hierarchical -file board-hierarchy-synth.rpt
report_utilization -file board-utilization-synth.rpt
write_checkpoint -force board-synth.dcp
write_hwdef -force -file board.hwdef
opt_design
place_design -directive Explore
phys_opt_design -directive AggressiveExplore
report_timing_summary -file board-timing-placed.rpt
report_timing -max_paths 40 -file board-paths-placed.rpt
report_utilization -file board-utilization-placed.rpt
write_checkpoint -force board-placed.dcp
route_design -directive Explore
phys_opt_design -directive AggressiveExplore
route_design
report_utilization -file board-utilization.rpt
report_timing_summary -report_unconstrained -file board-timing.rpt
report_cdc -details -file board-cdc.rpt
report_bus_skew -file board-bus-skew.rpt
report_drc -file board-drc.rpt
write_checkpoint -force board-routed.dcp
report_timing -max_paths 40 -file board-paths.rpt
if {[get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]<0} {error "Setup timing failed"}
if {[get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]<0} {error "Hold timing failed"}
write_bitstream -force board.bit
write_debug_probes -force board.ltx
write_sysdef -hwdef board.hwdef -bitfile board.bit -file board.hdf
puts {BOARD_G3_BUILT_NOT_PROGRAMMED}
