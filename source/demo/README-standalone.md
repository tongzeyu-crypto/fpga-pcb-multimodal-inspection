# PL / PS 最小功能演示

本目录提供独立算子核和PS扫描调度演示。完整4096点FFT、热像解码和图像预处理由主工程PS软件执行；独立核配套RTL测试、OOC实现及XSim结果回放。整机运行记录见上级目录的实板文档。

## 演示范围

| 功能 | 最小实现 |
|---|---|
| PL 频谱 | 64 点实数 DFT、整数均值去除、33 个归一化功率格点；Q14 系数，矩形窗。不是原正式链路的 4096 点 Hann PSD。 |
| PL 热像 | Kelvin×16 转毫摄氏度；最小/最大温度、最大值位置、≥阈值像素数。演示输入为真实热像的 16×16 子采样格，没有连通域热点分割或绝对测温标定。 |
| PL 共享预处理 | 同一任务核分时处理 RGB888 灰度/INT8 量化与热像仿射裁剪/INT8 量化，共用控制和 RAM 通路。不含完整缩放、高斯、Sobel 流水。 |
| PS 扫描 | 蛇形路线 → 下发目标 → 等待 ack、Idle、最新回报坐标 → 独立停稳计时 → 每点三帧 → 点位/帧 ID/原始来源/时序关联。 |

`rtl/pcb_demo_core.sv` 实际计算这三类任务，`pcb_demo_axi.sv` 提供 AXI-Lite 接口。`runtime/scan_demo.py` 是可在 PS Python 上使用的调度逻辑；当前命令行只提供明确标识的模拟运动与原始数据回放，使用模拟GRBL控制器。

输入从原提交版真实 DC-DC 记录提取：六个原机械位置，每点三帧、每帧第一通道前 64 个样本；RGB/热像取 16×16 格。输入文件记录原文件 SHA256 和原采集时间。这些是历史记录，不是本轮新采集或硬件同步数据。

## 运行演示

```text
python run_demo.py
```

也可分别运行：

```text
python -m runtime.scan_demo --replay --output output/my_run
python tools/render_demo.py --run output/my_run
```

回放从 `evidence/rtl-results.json` 读取 **XSim 实际 AXI 回读并与整数参考校验的结果**。输入键或 RTL 源码哈希不匹配会报错，没有静默的软件计算替代。此入口读取离线生成的已核验结果。

输出包括 `demo-result.json`、逐步状态记录 `events.jsonl` 和 `demo-preview.png`。附带的 `output/example_run` 是一次已运行的示例。

## 重现验证

```text
python tools/verify_demo.py --vivado-bin <Vivado-bin> --work <new-ASCII-work-directory>
python -m unittest discover -s tests -p "test_*.py" -v
python tools/implement_demo.py --vivado-bin <Vivado-bin> --work <new-ASCII-OOC-directory>
```

`tools/prepare_inputs.py --source-root <prior-submission-folder>` 可从完整原始记录重新提取演示输入。需要 NumPy 和 Pillow；普通调度回放只需 Python 标准库。

独立OOC报告对应本目录的小型IP；整机位流及其运行记录由上级工程分别管理。

本次验证结果：27 组 RTL 任务、1480 个输出值逐一一致；5 项 PS 调度测试通过；示例完成 6 点、18 帧关联。小 IP 在 62.5 MHz 独立实现中 setup +4.546 ns、hold +0.156 ns，使用 895 LUT、611 FF、1 BRAM、4 DSP。ARM MMIO客户端交叉编译通过，使用独立演示IP标识。

`runtime/pl_demo.cpp` 提供可交叉编译的 ARM MMIO 客户端，要求显式指定设备，并检查独立演示 IP 的 PDP1 标识。它对应独立演示IP的寄存器接口。原整机 AI 设备的标识不同，客户端会拒绝向其提交这些任务。

## 寄存器摘要

控制/中止 `0x00`，状态 busy/done/error `0x04`，标识 PDP1 `0x08`；任务 `0x0c`，元素数 `0x10`，热点阈值 m°C `0x14`，预处理模式 `0x18`，热像基值 `0x1c`，移位 `0x20`；温度最小/最大/最大索引/热点数 `0x24–0x30`，完成代次 `0x34`。输入区 `0x1000`，输出区 `0x2000`，每元素 32 位；最多 256 元素。完成后必须检查错误、done 和代次再读取结果。

## 文档可采用的措辞

在功能演示原型中，补充了 PL 侧小点数频谱、热像温度转换与热点计数、RGB/热像共享灰度量化处理模块，并在 PS 侧实现路线遍历、回报到点确认、停稳等待和采样关联的调度流程。相关模块配套原始数据回放、RTL逐值对照和独立实现记录；主程序扫描页面调用已核验结果。

主工程的完整频谱和图像处理由PS软件执行，图形与共享CNN由整机PL执行。
