# PDP2 完整数据功能演示

本目录提供真实RTL、ARM客户端、数值参考、历史原始输入和PS扫描状态机，已经与上层主程序和原界面连接。规格为4096点Hann FFT与三帧功率累积、256×192整帧温度解码与统计，以及共享RGB灰度/INT8和热像量化。

主程序入口见根目录README；完整PS/PL分工、PDP2寄存器和重现步骤见 `../docs/处理链与接口.md`。`inputs/full-inputs.json`为当前界面输入，`inputs/demo-inputs.json`保留64点和16×16辅助边界夹具；不能据后者把完整实现误读为只处理小网格。

`python run_demo.py`运行标准库离线调度和结果图。此模式明确回放实际XSim AXI回读值，不访问开发板。板端主程序默认通过 `../runtime/compute_backend.py`调用 `/dev/pcb_demo`；身份必须为PDP2 `0x50445032`，旧PDP1不匹配。

输入来自真实DC-DC历史记录，运动使用模拟位置。当前六测点、18帧均为4096点；全部49152个温度像素参与计算。当前图像阈值40°C，没有达到阈值的像素就返回0，不增加演示热点。此处不包含新的物理扫描、同步采集或测温标定。

重现：`tools/verify_full_pipeline.py`完成99项实际AXI任务与216430个输出元素对照；`tools/implement_demo.py`完成独立核布线；`python -m unittest discover -s tests`检查状态机拒绝陈旧/未到点状态。整机位流和实板状态分别见上层版本及验收记录。
