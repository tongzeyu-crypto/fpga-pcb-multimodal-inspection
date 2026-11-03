#!/bin/sh
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
task_lib=/tmp/pcb-board-python37
mkdir -p "$task_lib"
tar xzf "$task_root/resources/board/python-stdlib-3.7.6.tar.gz" -C "$task_lib"
export PYTHONPATH="$task_lib/pythonlib:$task_root"
cd "$task_root"
exec python3 -m runtime.run_board --board-demo "$@"
