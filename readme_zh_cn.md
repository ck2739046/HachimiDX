# <img src="src/resources/icon.ico" width="60px"> HachimiDX-Convert 🐱

🔗 [**项目地址**](https://github.com/ck2739046/HachimiDX-Convert)
&nbsp;•&nbsp;
📖 [**English README**](readme.md)



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
    - 支持 CPU / NVIDIA TensorRT / DirectML 多种深度学习推理后端，兼容多种硬件。

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

