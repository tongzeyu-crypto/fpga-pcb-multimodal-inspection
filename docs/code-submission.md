# 最终程序提交与运行

当前包版本为PDP3-report2-audit-fixes-r6。原ZIP共1230个文件，1227个清单文件核验通过、ZIP CRC通过，91个Python文件语法解析通过。单独提供的《修复核对.md》与包内文件逐字节一致。

原包SHA-256：`9a8e675adc020fbec6e05893b87b7221a60d5d86f12d43cea6b0e1cd4485b1db`。上传文件保持原包内容，公开附件名为 `submission-zynq-20261103-final.zip`。

## 获取与核对

[下载完整程序](https://github.com/tongzeyu-crypto/fpga-pcb-multimodal-inspection/releases/tag/code-20261103-final)，解压后在完整包根目录运行：

```text
python tools/verify_delivery.py
```

Git的[source目录](../source/README_GITHUB.md)用于源码、模型与记录浏览，原始数据、二进制和硬件产物由完整Release提供。核对Git源码快照时，在仓库根目录运行 `python tools/verify_source_snapshot.py`。

## 运行入口

电脑功能展示：`start_demo.cmd`，或 `python -m runtime.run_board --demo --no-browser`，默认地址 `http://127.0.0.1:8698/`。运行依赖见 `runtime/requirements.txt`。

板端计算接口为PDP3，身份 `0x50445033`，应使用本包配套位流、DTB、驱动与客户端。原始包入口、精简显示入口和真实扫描的显式选项见[构建与运行](../source/docs/构建与运行.md)。

修复项目、单位、输入条件、双缓冲与公式见[修复核对](../source/docs/修复核对.md)和[处理链与接口](../source/docs/处理链与接口.md)。本次上传保留最终包中的全部版本说明和验证记录。
