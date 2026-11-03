# GitHub源码与发布包

本目录提供正式提交版的程序、RTL、模型、训练与构建工具、文档及证据浏览。完整数据、二进制、位流/HDF与板端标准库位于[代码Release](https://github.com/tongzeyu-crypto/fpga-pcb-multimodal-inspection/releases/tag/code-20261103-r2)。

R2统一文档和打包模板的版本表述。算法、RTL、权重、运行程序及原始采样与原交付版一致；变更文件和来源见[PUBLICATION_REVISION.json](PUBLICATION_REVISION.json)。

运行完整演示或构建工程时，请下载Release并在完整包根目录执行README中的命令。Git快照核对：在仓库根目录运行 `python tools/verify_source_snapshot.py`。完整包核对：在包根目录运行 `python tools/verify_delivery.py`。
