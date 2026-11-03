# 最终程序源码

当前版本：**PDP3-report2-audit-fixes-r6**。本目录采用最终程序源码，当前对照分析报告按提交方指定文件更新；程序、模型、二进制与硬件产物保持原交付版本。

- [对照分析报告](docs/修复核对.md)
- [原包README](README.md)
- [处理链与接口](docs/处理链与接口.md)
- [构建与运行](docs/构建与运行.md)
- [报告实现对照](docs/报告实现对照.md)
- [完整代码包与硬件下载](https://github.com/tongzeyu-crypto/fpga-pcb-multimodal-inspection/releases/tag/code-20261104-status-aligned)

原包共1230个文件，完整性清单1227项核验通过。ZIP SHA-256：`0a3ba6a71c9503c25e29e27cb91c9c152c8297fec2badc931fa4467e761d80de`。当前对照分析报告与提交方指定文件逐字节一致，并同步至完整下载包。相关说明已按该报告统一，且随包校验清单同步更新。报告还记录2026年11月4日完成的本版板卡、采样、机械运动、HDMI、测温及自启动验证；随包原始单项测试记录保留各自生成日期与范围。

Git提供源码、模型、配置、修复记录及验证摘要。原始ADC/相机数据、可执行程序、位流/HDF、板端标准库及详细构建日志通过Release提供，具体列表见[UPSTREAM_LAYOUT.json](UPSTREAM_LAYOUT.json)。运行完整程序时下载Release并在完整包目录执行原说明中的命令。

本仓库根目录的 `python tools/verify_source_snapshot.py` 核对源码快照；完整包中的 `python tools/verify_delivery.py` 核对交付文件。对照分析报告为提交方提供的说明；程序接口以处理链文档和源码为准，旧版包与历史截图按各自版本保留。
