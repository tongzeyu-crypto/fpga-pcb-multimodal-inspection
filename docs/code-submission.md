# 正式代码提交与运行说明

本次发布原样保留用户提供的 `submission_zynq_20261103_正式提交版.zip`，74,041,875字节，SHA-256为 `b1b3f12d203dd6df59de4ba400810d7b4dfcdb31c761e651647ea156cae33cd1`。其中1074个清单文件核验通过、没有不一致项，ZIP CRC通过，70个Python源码文件语法解析通过。这些检查不代表新做了一轮板端验收。

## 获取与核对

[下载完整正式代码包](https://github.com/tongzeyu-crypto/fpga-pcb-multimodal-inspection/releases/tag/code-20261103)。完整ZIP包含1077个文件，包含原始数据、预建模型、训练权重、ARM/Windows程序、位流/HDF、驱动及标准库资源。解压到英文路径后，在包根目录运行：

```text
python tools/verify_delivery.py
```

Git内的[source/](../source/README_GITHUB.md)提供源码、模型和证据浏览，完整数据及构建二进制通过Release提供。Git根目录可运行 `python tools/verify_source_snapshot.py` 核对每个源码快照文件与原包清单的一致性。

## 电脑演示

原包要求Python 3.10+。在完整包根目录安装 `runtime/requirements.txt` 中的依赖后，执行：

```text
python -m pip install -r runtime/requirements.txt
python -m runtime.run_board --demo
```

入口为 `http://127.0.0.1:8698/`。Windows也提供 `start_demo.cmd`，其中有开发机Conda和依赖目录的可选优先路径；其他电脑应先安装自己的Python与依赖，或直接采用上面的Python入口。扫描演示为模拟运动和历史记录回放，电脑画面不能作为FPGA速度指标。

## 板端与构建

配套硬件、驱动、显示素材和启动参数见[实板记录](../source/docs/实板演示记录-20261103.md)及[构建与运行](../source/docs/构建与运行.md)。本轮只发布已有交付，不运行这些硬件操作。原自启动镜像保留；新包的实板记录属于RAM临时加载。

完整 `--bundle` 复算路径需要板端兼容的NumPy/OpenCV等环境，当前精简根文件系统尚未完成这一步。原包的验证文档有早期“未上板”段落，应同时阅读11月3日较新实板记录；两项PL推理的一致性不等于实时采集、机械闭环或检测精度验收。
