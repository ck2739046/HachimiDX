[**English**](readme.md) | **中文**

<div align="center">

<h1>
  <img src="src/resources/icon.ico" width="110" alt="logo">
  <br>HachimiDX
</h1>

<h3>🐱 舞萌自动抄谱工具 🐱</h3>

<br>

**小团体不拉我，拿不到最新最热，所以自己抄谱** 😡😡😡😭😭😭🤔🤔🤔😋😋😋

为音乐游戏 **maimai** 设计的工具，自动将谱面确认视频转换为 simai 格式 (`maidata.txt`)。

<br>

![](https://img.shields.io/github/stars/ck2739046/HachimiDX?label=Stars)
![](https://img.shields.io/github/downloads/ck2739046/HachimiDX/total?label=下载次数)

🔗 [**项目地址**](https://github.com/ck2739046/HachimiDX)
&nbsp;•&nbsp;
📥︎ [**软件下载**](https://github.com/ck2739046/HachimiDX/releases/latest)
&nbsp;•&nbsp;
▶️ [**教程视频**](https://www.bilibili.com/video/BV1Rz5c6vEQH)

</div>

> <img src="src/resources/doc/images/qq_icon.svg" width="14px" style="vertical-align: middle;"> 如果在使用中遇到问题、需要帮助、想反馈 Bug 或提出建议，亦或参与开发讨论，欢迎加入 QQ 交流群 **`868888361`**。

<br>



## ✨ 主要亮点

- **强大的抄谱能力**
    - 支持 `tap` `slide` `touch` `hold` `touch-hold` 全种类音符识别与时值推理。
    - 支持 `ex` `break` `ex-break` 全子类音符变体分类。
    - 支持所有 simai 星星轨迹语法: `-` `V` `><` `pq` `ppqq` `sz` `v`。

- **定制视觉模型**
    - 专门针对游戏画面优化，能够适应复杂场景，识别更稳健。

- **可视化图形界面**
    - 全程通过可视化界面操作，无需输入命令行。

- **内置谱面编辑器**
    - 内嵌 [`MajdataEdit`](https://github.com/LingFeng-bbben/MajdataView) 和 [`MajdataView`](https://github.com/TeamMajdata/MajdataView/tree/431-NC-TH)，抄谱结果一站式预览与修改。

- **内置 BPM 测速工具**
    - 集成 [`Bpm-Measurer`](https://github.com/ck2739046/Bpm-Measurer)，一款实用的歌曲 BPM 测量工具。

- **多后台推理支持**
    - 支持 PyTorch / NVIDIA TensorRT / DirectML 多种深度学习推理后端，兼容各类硬件。

- **便捷的多媒体处理**
    - 内置多个实用工具：视频裁剪、音频匹配、格式转换，街机延迟调整等。





## 💻 硬件 / 运行环境要求

- **操作系统**：仅支持 Windows 10 / 11 (x64)
- **显卡显存**：至少 3 GB（如使用纯 CPU 推理则无显存要求）
- **内存**：至少 4 GB 可用
- **硬盘**：至少 7 GB 可用空间




## 🚧 已知问题

- 不支持识别 Touch/Touch-Hold 烟花特效 (`f`)

- 不支持伪双押 (`` ` ``)

- 相机实拍屏幕的视频可能存在拍摄角度、色偏、曝光等问题，抄谱准确性可能会下降。

- 轨迹有部分重叠的并行 slide 音符，可能会遗漏其中个别音符（例如 `1v6[8:1]/3v6[8:1]`）。



## 🎯 关于模型训练数据

模型训练数据均为自行采集：

- **全自动标注**
    - 用 [Mod](archive/yolo-train/mod_dump_notes/Dump_Notes.cs) 捕获游戏内部原始数据，配合 [脚本](archive/yolo-train/label_notes.py) 自动生成标注，坐标和类别高度准确。整个数据集构建过程便捷高效，能够快速按需获取海量优质样本。

- **分任务训练**
    - 各个模型各自使用专门的数据集，针对性优化。
    - `train_detect` — 识别音符位置
    - `train_detect_touch_hold` — 识别 touch-hold 位置与进度
    - `train_obb` — 识别 slide 旋转角度
    - `train_classify` — 判断 ex、break 等变体类型




## 🧩 技术架构

代码集中在 `src` 目录，分三层。中间层通过 **子进程 worker** 驱动核心算法，将重计算隔离在 GUI 之外，保证界面流畅。

- **UI 层 (`src/app`)** — 基于 **PyQt6** 的图形界面
    - `QSharedMemory` 单实例
    - 功能分页：Majdata 编辑、自动抄谱、任务队列、多媒体工具、软件设置
    - 统一 Widget 组件库（`src/app/widgets`），视觉与操作风格一致
    - 内嵌视频播放器，与谱面编辑器联动预览
    - 支持 UI 缩放与多语言（`i18n`，中/英切换）
- **中间层 (`src/services`)** — 服务生命周期与任务调度
    - **两阶段初始化**：统一管理服务：路径 → 设置 → i18n → 同步服务 → 初始化各管线
    - **任务调度器**：管理任务队列，按类型控制并发并向 UI 推送状态快照
    - **进程管理器**：统一托管 `QProcess`，为子任务分配 runner_id、合并输出并定时刷新
    - **独立管线**（`AutoRechartPipeline` / `MediaPipeline`）：用 **pydantic** 校验参数、组装 CLI 指令并提交调度器
    - 子任务以独立 **worker 子进程** 运行（抄谱 / 音频对齐 / 模型转换 / 硬件检测等），由进程管理器统一调度
    - **视频同步服务**：通过 UDP 与 MajdataEdit / MajdataView 双向联动（播放 / 暂停 / 跳转），内置时间容差与防抖
    - **看门狗**：子进程在退出时清理残留 Majdata 进程；
    - 内置 GitHub Releases 版本更新检查
- **核心算法层 (`src/core`)** — 抄谱按 `standardize → detect → analyze` 三阶段运行：
    - **视频规范化**
        - **OpenCV** 检测外屏圆 + 透视矫正
        - **FFmpeg** 执行裁剪 / 分辨率统一 / 重编码
    - **检测与追踪**：
        - **目标检测**：**YOLO**（ultralytics）多进程流式并行推理 `detect` 与 `obb` 模型
        - **变体分类**：ex / break 采用生产者-消费者管线（解码线程 + GPU 推理，双缓冲）实现 CPU/GPU 重叠
        - **路径追踪**：融合 **BOTSORT** + 自定义 **OCSort**，可选 re-id 重识别
    - **音符分析**：按 tap / touch / hold / touch-hold / slide 分别做预处理 → 速度估计 → 时差 / 时值推演 → slide 移动模式分析
    - **simai 语法转换**：输出 `maidata.txt`
    - **音频处理**：**librosa + scipy** 互相关做匹配同步、确认点击起点检测、街机延时 (arcade timing) 推演
    - **BPM 测量**：对接外部 `Bpm-Measurer`
    - **数据模型**：**pydantic** 定义配置与数据模型
    - **错误处理**：类 **Rust** 风格 `OpResult`（`ok` / `err`），统一封装每次操作结果




## 🏃 从源码运行

### 1. 配置 Python 环境

- 方式一：参考这个 [`指南`](src/resources/for_release_only/python_portable/用conda创建py环境.md) 在项目根目录创建 `python/` 文件夹，用 `./python/python.exe` 运行脚本。
- 方式二：自行安装 Python 并创建虚拟环境 (venv)。
  > 本项目使用 **Python 3.11.15**；Python 3.10+ 应该都能运行，但未经实际验证。

### 2. 解压资源文件

- 将 [`models/`](src/resources/for_release_only/models/) 下的所有 `.zip` 解压到 `data/models/`。
- 将 [`ffmpeg`](src/resources/for_release_only/ffmpeg-8.0.1-essentials_build.7z) 解压到 `src/resources/ffmpeg/`。
- （可选）自行编译 [`启动器`](src/resources/for_release_only/launcher) 并放到项目根目录。

### 3. 获取 Majdata 编辑器与查看器

编译 [MajdataEdit](https://github.com/ck2739046/MajdataEdit/tree/v4.3.1) & [MajdataView](https://github.com/ck2739046/MajdataView/tree/431-NC-TH)，将编译输出放入 `src/resources/majdata`：

> *请自行从其他渠道获取 `SFX` 和 `Skin`，放入文件夹中。*

### 4. 获取 BPM 测量工具

编译 [Bpm-Measurer](https://github.com/ck2739046/Bpm-Measurer)，将编译输出放入 `src/resources/Bpm Measurer/`。

### 5. 安装并启动

运行 `install/script/install.py` 安装依赖。<br>
运行 `src/main.py` 启动程序。
