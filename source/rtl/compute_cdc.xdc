set_false_path -to [get_pins -hier -regexp {.*req_sync_reg\[0\]/D}]
set_false_path -to [get_pins -hier -regexp {.*rst_sync_reg\[0\]/D}]
set_false_path -to [get_pins -hier -regexp {.*done_sync_reg\[0\]/D}]
