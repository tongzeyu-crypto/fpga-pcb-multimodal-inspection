# 板端USB采集原始样例

来源：`integrated-20261017-183310`，2026年10月17日板端采集记录。RGB和热像元数据均标记 `ZYNQ_USB_REAL`。原始文件与来源哈希见[资产清单](../../assets/manifest.json)。此组为当次参考采集记录，名称中的 reference 不是将外部待测照片伪装为板端照片。

|文件|格式与含义|
|---|---|
|reference-rgb.jpg|1280×720 JPEG，板端USB RGB采集；通用USB身份，传感器具体型号未核实|
|reference-thermal.raw|196608字节，256×384传输载荷，TINY1B_DUAL_U16LE，小端uint16|
|reference-thermal.npz|image_u16、temperature_codes 均为192×256 uint16；temperature_celsius 为192×256 float32，单位℃|
|reference-thermal.image.jpg|256×192热像强度显示图，不含温度矩阵数值|
|两个JSON|保留来源、分辨率、帧序号、设备时间戳、温度状态；去除电脑接收时刻字段|

热像样例来自Tiny1-B，传输使用YUYV承载双平面数据，不能按普通YUYV彩色图像解释整个raw。温度矩阵为设备码值换算结果，未独立校准测温精度；样例元数据范围约28.66–35.91℃。RGB与热像通过各自流取得，不声明硬件同步曝光。此组历史采集没有证明2026年10月30日独立显示版本已具备完整实时闭环。
