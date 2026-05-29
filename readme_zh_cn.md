# <img src="src/resources/icon.ico" width="60px"> HachimiDX-Convert 🐱

🔗 [**项目地址**](https://github.com/ck2739046/HachimiDX-Convert)
&nbsp;•&nbsp;
📖 [**English README**](readme.md)
&nbsp;•&nbsp;
🎥 [**演示视频**](https://www.bilibili.com/video/BV1VND1B5EfQ)



**小团体不拉我，拿不到最新最热，所以自己抄谱😡😡😡😭😭😭🤔🤔🤔😋😋😋**

专门为音乐游戏 `maimai`设计的工具，将谱面确认视频一键转换为 simai 格式谱面 (`maidata.txt`) 。



## ✨ 主要亮点

- **强大的全自动谱面识别**
    - 支持 tap, slide, touch, hold, touch-hold 全种类音符识别与时值推理。
    - 支持 ex-note, break-note, ex-break-note 多子类音符变体分类。
    - 支持从轨迹反推所有 slide 语法格式。

- **定制视觉模型**
    - 专门针对游戏画面优化，能够适应复杂场景，识别更稳健。

- **可视化操作界面**
    - 全程使用可视化图形界面。

- **内置谱面编辑器**
    - 内嵌 [`MajdataEdit`](https://github.com/LingFeng-bbben/MajdataView) 和 [`MajdataView`](https://github.com/TeamMajdata/MajdataView/tree/431-NC-TH)，识别结果一站式预览与修改。

- **多后台推理支持**
    - 支持 PyTorch / NVIDIA TensorRT / DirectML 多种深度学习推理后端，兼容各类硬件。

- **便捷的多媒体处理**
    - 内置多个实用工具：视频裁剪、音频匹配、格式转换，街机延迟调整等。





## 🎯 关于模型训练数据

模型的训练数据全部自己采集：

- **全自动标注**
    - 用 [Mod](archive/yolo-train/mod_dump_notes/Dump_Notes.cs) 捕获游戏内部原始数据，配合 [脚本](archive/yolo-train/label_notes.py) 自动生成标注，坐标和类别高度准确。整个数据集构建过程便捷高效，能够快速按需获取海量优质样本。

- **分任务训练**
    - 三个模型各自使用专门的数据集，针对性优化。
    - `train_detect` — 识别音符位置
    - `train_obb` — 识别 slide 旋转角度
    - `train_classify` — 判断 ex、break 等变体类型




## 🧩 技术架构

代码主要在 `src` 目录下，分三层：

- **UI 层 (`src/app`)**
    - 基于 Qt 构建图形化界面
    - 每个功能都有独立的页面
    - 定制了一套统一的 Widget 组件库，所有页面共用，视觉风格和操作体验高度一致
- **中间层 (`src/services`)**
    - 管理核心任务队列，控制并发，分发任务状态。
    - 子任务使用 QProcess 独立运行，由专门的进程管理器统一调度。
    - 使用 pydantic 校验参数并组装指令。
    - 各项基础服务使用独立的组件，职责清晰。
    - 提供统一的 API，前端只需简单调用，由中间层统一调度核心算法。
- **核心算法层 (`src/core`)**
    - 使用 OpenCV 处理画面
    - 使用 YOLO 视觉模型识别画面
    - 元素路径追踪
    - 数据过滤，转换，处理
    - 音符方位推演、时差推演、时值推演
    - simai 语法转换
    - 音频匹配、同步、街机延时 (arcade timing) 推演




## 🚧 已知问题

- **Touch/Touch-Hold**
    - 不支持在同一位置重叠出现
    - 不支持烟花特效识别 (`f`)
    
- 不支持伪双押 (`` ` ``)

- 歌曲全程保持固定 BPM，不支持 BPM 变速曲目。

- 相机实拍屏幕的视频可能存在拍摄角度、色偏、曝光等问题，此时 ex/break 等音符变体的分类准确率会下降。



## 🏃 从源码运行

### 1. 配置 Python 环境

- 方式一：将 [`嵌入式 Python`](src/resources/for_release_only/python%20portable/py3.13.11.zip) 解压到项目根目录，用 `./python/python.exe` 运行脚本。
- 方式二：自行安装 Python 并创建虚拟环境 (venv)。
  > 本项目使用 **Python 3.13.11**；Python 3.10+ 似乎大概都可以运行，仅猜测，未经实际验证。

  > **注意 (2026.05.09):**<br>
  > NVIDIA TensorRT 目前不支持 Python 3.14。使用 `DirectML` 或 `PyTorch` 推理时，Python 3.14 可用；使用 `TensorRT` 时，最高支持到 Python 3.13。

### 2. 解压资源文件

- 将 [`models/`](src/resources/for_release_only/models/) 下的所有 `.zip` 解压到 `data/models/`。
- 将 [`ffmpeg`](src/resources/for_release_only/ffmpeg-8.0.1-essentials_build.7z) 解压到 `src/resources/ffmpeg/`。
- （可选）自行编译 [`启动器`](src/resources/for_release_only/launcher) 并放到项目根目录。

### 3. 获取 Majdata 编辑器与查看器

从以下仓库编译，编译后放入 `src/resources/majdata`：

- [MajdataEdit](https://github.com/ck2739046/MajdataEdit/tree/v4.3.1) & [MajdataView](https://github.com/ck2739046/MajdataView/tree/431-NC-TH)

请自行从其他渠道获取 `SFX` 和 `Skin`，放入文件夹中。

### 4. 安装并启动

运行 `install/script/install.py` 安装依赖。<br>
运行 `src/main.py` 启动程序。
