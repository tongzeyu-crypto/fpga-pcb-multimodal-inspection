# GitHub源码快照说明

本目录来自用户提供的 `submission_zynq_20261103_正式提交版.zip`。所有收录的原包文件均逐字节保留，没有修改算法、权重、RTL、启动脚本或验证记录。原包SHA-256：

`b1b3f12d203dd6df59de4ba400810d7b4dfcdb31c761e651647ea156cae33cd1`

Git中提供源码、训练权重、小型模型/界面资源、文档和验证摘要，共306个原包文件。完整1077文件交付包见[正式代码Release](https://github.com/tongzeyu-crypto/fpga-pcb-multimodal-inspection/releases/tag/code-20261103)。为避免重复保存大批数据和构建产物，原始ADC/相机数据、ARM/Windows二进制、位流/HDF及板端Python标准库压缩包仅放在Release。具体文件分配见[UPSTREAM_LAYOUT.json](UPSTREAM_LAYOUT.json)。

直接浏览本目录即可审阅源码。要运行完整演示、重建工程或执行原包的完整核验，请下载Release ZIP并解压，在**完整包根目录**执行其README中的命令；本Git源码快照不是完整运行包，不能直接把缺失的Release资源视为丢失文件。

原 `FILE_MANIFEST.json`、`SOURCE_SHA256.json` 和 `tools/verify_delivery.py` 均保持原样，它们描述完整交付包。核对本Git快照可在仓库根目录运行 `python tools/verify_source_snapshot.py`。原包完整核验已通过：1074个清单文件无不一致项，ZIP CRC通过。原包实际共1077个文件，另有清单自身等元文件。

额外补入了本说明、布局表、Git忽略例外，以及从原包Python标准库压缩包提取的许可证全文。原包文档包含早期离线阶段文字，当前实板范围以[2026年11月3日实板记录](docs/实板演示记录-20261103.md)为准。
