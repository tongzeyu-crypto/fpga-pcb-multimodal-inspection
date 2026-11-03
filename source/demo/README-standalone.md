# PDP2 完整数据功能演示

本目录提供真实RTL、ARM客户端、数值参考、历史原始输入和PS扫描状态机，已经与上层主程序和原界面连接。规格为4096点Hann FFT与三帧功率累积、256×192整帧温度解码与统计，以及共享RGB灰度/INT8和热像量化。

主程序入口见根目录README；完整PS/PL分工、PDP2寄存器和重现步骤见 `../docs/处理链与接口.md`。`inputs/full-inputs.json`为当前界面输入，`inputs/demo-inputs.json`保留64点和16×16辅助边界夹具；不能据后者把完整实现误读为只处理小网格。

`python run_demo.py`运行标准库离线调度和结果图。此模式明确回放实际XSim AXI回读值，不访问开发板。板端主程序默认通过 `../runtime/compute_backend.py`调用 `/dev/pcb_demo`；身份必须为PDP2 `0x50445032`，旧PDP1不匹配。

此目录的PDP2回归示例使用真实DC-DC历史输入与模拟位置；六测点、18帧均为4096点，全部49152个温度像素参与计算。图像阈值为40°C，没有达到阈值的像素就返回0。该子目录测试范围与当前PDP3整机验收分开记录；提交方提供的2026年11月4日《对照分析报告》记录了当前版本的板端验证。

重现：`tools/verify_full_pipeline.py`完成99项实际AXI任务与216430个输出元素对照；`tools/implement_demo.py`完成独立核布线；`python -m unittest discover -s tests`检查状态机拒绝陈旧/未到点状态。当前PDP3整机位流、板端状态与逐项范围见上层版本、`docs/验收记录.md` 和 `docs/修复核对.md`。
