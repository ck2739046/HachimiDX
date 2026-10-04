[**English**](readme.md) | **中文**

<div align="center">

<h1>
  <img src="src/resources/icon.ico" width="110" alt="logo">
  <br>HachimiDX
</h1>

<h3>🐱 舞萌自动抄谱工具 🐱</h3>

<br>

**小团体不拉我，拿不到最新最热，所以自己抄谱** 😡😡😡😭😭😭🤔🤔🤔😋😋😋

本工具可将谱面确认视频转换为 simai 谱面 (`maidata.txt`)

<br>

![](https://img.shields.io/github/stars/ck2739046/HachimiDX?label=Stars)
![](https://img.shields.io/github/downloads/ck2739046/HachimiDX/total?label=下载次数)

⬇️ [**软件下载**](https://github.com/ck2739046/HachimiDX/releases/latest)
&nbsp;•&nbsp;
▶️ [**演示视频**](https://www.bilibili.com/video/BV1Rz5c6vEQH)

> 如果要反馈问题、分享建议，或参与开发讨论，<br>
> 欢迎加入 QQ 交流群 <img src="src/resources/doc/images/qq_icon.svg" width="14px" style="vertical-align: middle;"> **`868888361`**。

</div>
<br>





## ✨ 独特亮点

> 分为 **完整版** 与 **精简版** 两个版本 —— **精简版** 不含自动抄谱引擎。

| | | |
|:--:|---|:--:|
| 💪 | **强大的自动抄谱引擎** | 全部音符类型 ✅ <br> 全部音符变体 ✅ <br> 全部星星语法 ✅ |
| 🚀 | **定制 AI 模型** | 专门针对舞萌训练 |
| 🛠️ | **超多实用工具** | 覆盖完整工作流 |
| 🖥️ | **图形界面优先** | 简单直观 |
| 🌟 | **兼容各类硬件** | ONNX / TensorRT / NCNN |
| ✏️ | **内置谱面编辑器** | 内嵌 [`MajdataX`](https://github.com/re-poem/MajdataViewX) |
| 🎵 | **内置 BPM 测速工具** | 集成 [`BPM-Measurer`](https://github.com/ck2739046/BPM-Measurer) |





## 💻 最低系统要求

| | **操作系统** | **内存** | **硬盘** |
|:--:|:--:|:--:|:--:|
| **精简版** | Win10 x64 | 0.5 GB | 1.5 GB |
| **完整版** | Win10 x64 | 4 GB | 6 GB |





## 🎯 数据采集

模型训练数据均为自行采集：使用 [Mod](archive/yolo-train/mod_dump_notes/Dump_Notes.cs) 捕获游戏内部原始数据，配合 [脚本](archive/yolo-train/label_notes.py) 自动生成标注。标注的坐标与类别高度准确，数据集构建高效且易于扩展，可按需产出海量优质样本。





## 🧩 技术栈

- **Python / C#**: 开发语言
- **PyQt6**: 图形界面
- **pydantic**: 数据校验
- **python-i18n**: 多语言支持
- **OpenCV**: 图像处理、自动标注
- **FFmpeg / FFprobe**: 音视频处理
- **YOLO (ultralytics)**: 模型基座
- **PyTorch / ONNX / TensorRT / NCNN**: 模型推理
- **BOTSORT + 定制 OC-SORT**: 目标追踪
- **librosa**: 音频处理
- **Matplotlib**: 波形绘制
- **.NET**: 启动器、MajdataEdit
- **Unity (MelonLoader)**: 游戏 Mod、MajdataView





## 🚧 已知问题

- 不支持 Touch / Touch-Hold 烟花特效 (`f`)。

- 不支持伪双押 (`` ` ``)。

- 用相机实拍屏幕的视频可能存在画面歪斜、色彩偏移、曝光异常、残影等问题，抄谱准确性可能会下降。

- 多个 slide 同时存在，且部分轨迹发生重叠或交叉时，这些 slide 可能会无法识别（例如 `1v6[8:1]/3v6[8:1]`）。

- 不支持启动等待时间非标准的 slide 音符。





## 🏃 从源码运行

### 1. 配置 Python 环境

- 参考这个 [`指南`](src/resources/for_release_only/python_portable/创建py环境.md) 在项目根目录创建 `python/` 文件夹，用 `./python/python.exe` 运行脚本。

### 2. 解压资源文件

- 将 [`models/`](src/resources/for_release_only/models/) 下的所有 `.zip` 解压到 `data/models/`。
- 将 [`ffmpeg`](src/resources/for_release_only/ffmpeg-8.0.1-essentials_build.7z) 压缩包解压到 `src/resources/ffmpeg/`。
- （可选）编译 [`启动器`](src/resources/for_release_only/launcher) 并放到项目根目录。

### 3. 获取 MajdataX

编译 [MajdataEdit-Neo](https://github.com/ck2739046/MajdataEdit-Neo/tree/HachimiDX) 和 [MajdataViewX](https://github.com/ck2739046/MajdataViewX/tree/HachimiDX)，将编译输出放入 `src/resources/majdatax/`。

> *请自行从其他渠道获取 `SFX` 和 `Skin`，放入同一文件夹中。*

### 4. 获取 BPM-Measurer

编译 [BPM-Measurer](https://github.com/ck2739046/BPM-Measurer)，将编译输出放入 `src/resources/BPM-Measurer/`。

### 5. 安装并启动

运行 `install/script/main.py` 以安装依赖。<br>
运行 `src/main.py` 以启动程序。





## 💖 捐赠

如果这个项目对你有帮助，欢迎捐赠支持一下！❤️

<div align="center">

<img src="src/resources/doc/images/donate_wechat.png" width="130" alt="WeChat donation QR code">

</div>
