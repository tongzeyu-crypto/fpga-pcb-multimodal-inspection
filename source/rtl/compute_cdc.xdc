set_false_path -to [get_pins -hier -regexp {.*req_sync_reg\[0\]/D}]
set_false_path -to [get_pins -hier -regexp {.*stop_sync_reg\[0\]/D}]
set_false_path -to [get_pins -hier -regexp {.*ack_sync[01]_reg\[0\]/D}]
set_false_path -to [get_pins -hier -regexp {.*done_sync[01]_reg\[0\]/D}]
set_false_path -to [get_pins -hier -regexp {.*active_sync_reg\[0\]/D}]
set_false_path -to [get_pins -hier -regexp {.*continuous_sync_reg\[0\]/D}]
# Metadata buses are held by bank ownership. Completion crosses three host
# registers before the host snapshot and ready flag are published. Bound the
# bundled-data delay to two host periods (32 ns), less than that guard interval.
set_max_delay -datapath_only 32 -from [get_cells -hier -regexp {.*(bank_generation[01]|begin_tick[01]|end_tick[01])_reg.*}] -to [get_cells -hier -regexp {.*host_meta[01]_reg.*}]
set_false_path -to [get_pins -hier -regexp {.*rst_sync_reg\[0\]/D}]
