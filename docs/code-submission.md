# 正式代码提交与运行说明

R2已统一README、验收记录、构建说明和发布模板的版本文字，实板信息采用11月3日的运行记录。算法、RTL、模型权重、运行程序和原始采样保持交付版本。

## 获取与核对

[下载完整正式代码包](https://github.com/tongzeyu-crypto/fpga-pcb-multimodal-inspection/releases/tag/code-20261103-r2)。完整ZIP包含1078个文件，包含原始数据、预建模型、训练权重、ARM/Windows程序、位流/HDF、驱动及标准库资源。解压到英文路径后，在包根目录运行：

```text
python tools/verify_delivery.py
```

Git内的[source/](../source/README_GITHUB.md)提供源码、模型和证据浏览，完整数据及构建二进制通过Release提供。Git根目录可运行 `python tools/verify_source_snapshot.py` 核对每个源码快照文件与当前发布清单的一致性。

## 电脑演示

原包要求Python 3.10+。在完整包根目录安装 `runtime/requirements.txt` 中的依赖后，执行：

```text
python -m pip install -r runtime/requirements.txt
python -m runtime.run_board --demo
```

入口为 `http://127.0.0.1:8698/`。Windows也提供 `start_demo.cmd`，其中有开发机Conda和依赖目录的可选优先路径；其他电脑应先安装自己的Python与依赖，或直接采用上面的Python入口。扫描演示为模拟运动和历史记录回放，电脑画面不能作为FPGA速度指标。

## 板端与构建

配套硬件、驱动、显示素材和启动参数见[实板记录](../source/docs/实板演示记录-20261103.md)及[构建与运行](../source/docs/构建与运行.md)。原自启动镜像保留；新包的实板记录属于RAM临时加载。

完整 `--bundle` 复算路径使用板端兼容的NumPy/OpenCV等环境，具体依赖、输入条件和启动方法见随包构建文档。板端演示采用来源绑定显示素材与历史数据回放。
