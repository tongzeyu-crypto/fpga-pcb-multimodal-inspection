# 版权与第三方来源

自2026年11月4日起，本项目原创软件及配套材料按根目录 [MIT License](LICENSE) 许可，版权标记为 `tongzeyu-crypto`。范围包括项目原创源代码、RTL、模型与权重、构建和运行工具、软件说明、图表、项目照片及项目采集数据。第三方文件、带独立版权或许可标识的材料、竞赛模板与标识不由本许可覆盖，仍按原许可或权利人授权使用；逐项来源见下表及[source第三方说明](source/docs/第三方与资源.md)。

|来源|在本项目中的角色|本批处理|
|---|---|---|
|AMD/Xilinx Zynq平台|开发板、工具链与技术参考|不转载工具、BSP、原厂固件备份；报告引用UG585|
|Analog Devices AD9248|采购ADC模块及器件说明|实物照片和数据；不转载厂商安装包或声称模块为自主设计|
|CoreXY采购套件、近场前端采购模块|机械与采样链路的集成部件|记录集成实物；未将供应商设计作为项目原创电路/机械设计发布；采购页面未完整归档|
|GRBL|运动控制协议及第三方固件|仅说明使用，未附固件；参考 https://github.com/gnea/grbl/wiki/Grbl-v1.1-Interface |
|OpenCV、SIFT及单应估计|历史外观分析方法|仅技术说明及结果图，未附第三方源代码；参考 https://docs.opencv.org/4.x/d1/de0/tutorial_py_feature_homography.html |
|XoFTR|历史PC配准及后续AI集成背景|11月3日包不含XoFTR/SwinFuSR或其权重，交付的两项小模型由项目训练工具生成|
|glTF与封装模型流程|模型组织与显示资源|本批只收录项目结果图，没有默认转载第三方模型库|
|参赛技术报告模板|12页报告框架和竞赛标识|保留原模板用于本项目参赛材料；不单独作为通用模板再授权|
|Windows界面光标|历史显示截图中的界面元素|不发布提取的光标ROM或独立资产|

没有收录厂商产品图、外部行业宣传片、候选海报或计算器项目ESP32-CAM/OV5640资料。照片可见模块丝印、品牌及商标归各自权利人所有。

11月3日源码快照按用户正式交付包保留了 `resources/factory` 最小PS预设与DVI RTL、公共Zynq设备树、libjpeg-turbo头文件及包内依赖许可证。这些来源不得视为项目自主设计。Python 3.7.6标准库仅随完整Release提供，其原包内许可证另提取到[source/resources/licenses](source/resources/licenses)。没有发布开发工具、整套Python环境或原厂固件备份。详细来源见[原包第三方说明](source/docs/第三方与资源.md)。
