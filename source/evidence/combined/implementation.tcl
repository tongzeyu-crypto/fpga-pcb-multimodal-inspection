set_param general.maxThreads 2
set_param synth.maxThreads 1
package require msgcat
create_project integration project -part xc7z020clg400-1 -force
set_property ip_repo_paths [list [file normalize packaged_ip] [file normalize packaged_scanout] [file normalize packaged_dvi] [file normalize packaged_adc] [file normalize packaged_ai] [file normalize packaged_demo]] [current_project]
update_ip_catalog
source integration/board_hdmi.tcl
exit
