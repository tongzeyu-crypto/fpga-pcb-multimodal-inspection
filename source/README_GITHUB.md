# 最终程序源码

当前版本：**PDP3-report2-audit-fixes-r6**。本目录按用户本次提供的最终ZIP提取，收录的原包文件均保持逐字节一致。

- [修复核对](docs/修复核对.md)
- [原包README](README.md)
- [处理链与接口](docs/处理链与接口.md)
- [构建与运行](docs/构建与运行.md)
- [报告实现对照](docs/报告实现对照.md)
- [完整代码包与硬件下载](https://github.com/tongzeyu-crypto/fpga-pcb-multimodal-inspection/releases/tag/code-20261103-final)

原包共1230个文件，完整性清单1227项核验通过。ZIP SHA-256：`9a8e675adc020fbec6e05893b87b7221a60d5d86f12d43cea6b0e1cd4485b1db`。单独提供的《修复核对.md》与ZIP内文件相同。

Git提供源码、模型、配置、修复记录及验证摘要。原始ADC/相机数据、可执行程序、位流/HDF、板端标准库及详细构建日志通过Release提供，具体列表见[UPSTREAM_LAYOUT.json](UPSTREAM_LAYOUT.json)。运行完整程序时下载Release并在完整包目录执行原说明中的命令。

本仓库根目录的 `python tools/verify_source_snapshot.py` 核对源码快照；完整包中的 `python tools/verify_delivery.py` 核对交付文件。当前程序分工以本版处理链文档为准，旧版包与历史截图按各自版本保留。
