**English** | [**中文**](readme_zh_cn.md)

<div align="center">

<h1>
  <img src="src/resources/icon.ico" width="110" alt="logo">
  <br>HachimiDX
</h1>

<h3>🐱 Maimai auto rechart tool 🐱</h3>

<br>

A tool for the rhythm game **maimai** that converts chart confirmation videos into simai format (`maidata.txt`).

<br>

![](https://img.shields.io/github/stars/ck2739046/HachimiDX?label=Stars)
![](https://img.shields.io/github/downloads/ck2739046/HachimiDX/total?label=Downloads)

🔗 [**GitHub Repo**](https://github.com/ck2739046/HachimiDX)
&nbsp;•&nbsp;
📥︎ [**Download Release**](https://github.com/ck2739046/HachimiDX/releases/latest)
&nbsp;•&nbsp;
▶️ [**Tutorial Video**](https://www.bilibili.com/video/BV1Rz5c6vEQH)

</div>

> <img src="src/resources/doc/images/qq_icon.svg" width="14px" style="vertical-align: middle;"> Run into issues, want to report bugs, share suggestions, or talk development? Join our QQ group chat **`868888361`**.

<br>



## ✨ Highlights

- **Powerful recharting capabilities**
    - Supports recognition and duration inference for all note types: `tap` `slide` `touch` `hold` `touch-hold`.
    - Supports all note variants classification: `ex` `break` `ex-break`.
    - Supports all simai slide movement syntax: `-` `V` `><` `pq` `ppqq` `sz` `v`.

- **Custom vision models**
    - Optimized specifically for maimai gameplay, with robust performance in complex scenes.

- **GUI-first design**
    - Everything is done through a visual interface — no CLI commands required.

- **Built-in editors**
    - Integrates [`MajdataEdit`](https://github.com/LingFeng-bbben/MajdataView) and [`MajdataView`](https://github.com/TeamMajdata/MajdataView/tree/431-NC-TH) so rechart results can be previewed and modified in one place.

- **Built-in BPM measurement tool**
    - Integrates [`Bpm-Measurer`](https://github.com/ck2739046/Bpm-Measurer), a handy tool for measuring a song's BPM.

- **Flexible inference backends**
    - Supports PyTorch / NVIDIA TensorRT / DirectML inference backends for compatibility with a range of hardware.

- **Handy multimedia tools**
    - Trim videos, sync audio, convert formats, adjust arcade timing, etc.





## 💻 System Requirements

- **OS**: Windows 10 / 11 (x64) only
- **GPU VRAM**: at least 3 GB (no VRAM requirement if using CPU-only inference)
- **RAM**: at least 4 GB available
- **Disk**: at least 7 GB free




## 🚧 Known Issues

- Touch / Touch-Hold Fireworks effects (`f`) are not supported.

- Fake jumps (`` ` ``) are not supported.

- Camera-captured footage (off-screen recordings) may suffer from angle, color cast, or exposure issues. This may hurts accuracy of auto rechart.

- Parallel slide notes with partially overlapping trajectories may cause some to be missed (e.g., `1v6[8:1]/3v6[8:1]`).



## 🎯 Model Training Data

All training data was collected in-house:

- **Automated labeling**
    - A [Mod](archive/yolo-train/mod_dump_notes/Dump_Notes.cs) captures raw game data, and a [script](archive/yolo-train/label_notes.py) automatically generates annotations. Coordinates and categories are highly accurate. This makes dataset construction efficient and scalable, enabling large volumes of high-quality samples on demand.

- **Task-specific training**
    - Each model uses a dedicated dataset and is optimized for its own task.
    - `train_detect` — identifies note positions
    - `train_detect_touch_hold` — identifies touch-hold positions/progress.
    - `train_obb` — identifies slide rotation angles
    - `train_classify` — determines variants such as ex and break




## 🧩 Technical Architecture

Code lives in `src/`, organized in three layers. The middle layer drives the core algorithms via **subprocess workers**, isolating heavy computation from the GUI to keep it responsive.

- **UI layer (`src/app`)** — GUI built with **PyQt6**
    - `QSharedMemory` single-instance
    - Feature pages: Majdata editor, auto rechart, task queue, media tools, app settings
    - A shared widget library (`src/app/widgets`) keeps the visual style consistent across pages.
    - Embedded video player that syncs with the chart editor for preview.
    - UI scaling and multi-language (`i18n`, EN/ZH).
- **Middle layer (`src/services`)** — service lifecycle and task scheduling
    - **Two-phase initialization**: uniformly manages services: paths → settings → i18n → sync server → pipeline initialization.
    - **Task scheduler**: manages queues, controls per-type concurrency, and pushes task-status snapshots to the UI.
    - **Process manager**: owns all `QProcess` instances, assigns runner IDs, merges output, and flushes periodically.
    - **Standalone pipelines** (`AutoRechartPipeline` / `MediaPipeline`): validate params with **pydantic**, assemble CLI argv, and submit tasks to the scheduler.
    - Subtasks run as separate **worker subprocesses** (rechart, audio alignment, model conversion, hardware checks, etc), scheduled by the process manager.
    - **Video sync server**: bridges MajdataEdit / MajdataView over UDP (play / pause / seek) with time-tolerance and debounce handling.
    - **Watchdog**: a subprocess cleans up orphaned Majdata processes on exit.
    - Built-in GitHub Releases update checker.
- **Core layer (`src/core`)** — the auto-rechart pipeline runs in three stages, `standardize → detect → analyze`:
    - **Video standardization**
        - **OpenCV** detects the outer circle and computes perspective-correction params.
        - **FFmpeg** performs the crop, resolution normalization, and re-encoding.
    - **Detection & tracking**:
        - **Object Detection**: YOLO (ultralytics) runs `detect` and `obb` models as parallel multiprocess streaming workers.
        - **Variant classification**: ex / break classification uses a producer-consumer pipeline (decode thread + GPU inference, double-buffered) for CPU/GPU overlap.
        - **Path tracking**: fuses **BOTSORT** + a custom **OCSort**, with optional re-id.
    - **Note analysis**: per-type preprocess → speed estimation → timing/duration inference (tap / touch / hold / touch-hold / slide) → slide movement syntax analyze.
    - **simai conversion**: outputs `maidata.txt`.
    - **Audio processing**: librosa + scipy cross-correlation audio matching & sync, confirmation-click detection, arcade-timing inference.
    - **BPM measurement**: connects to the external `Bpm-Measurer`.
    - **Data models**: **pydantic** schemas for config and data models.
    - **Error handling**: Rust-style `OpResult` (`ok` / `err`) uniformly wraps every operation result.




## 🏃 Running from Source

### 1. Set up the Python environment

- Option A: Follow this [`guide`](src/resources/for_release_only/python_portable/用conda创建py环境.md) to create a `python/` folder in the project root, then use `./python/python.exe` to run scripts.
- Option B: Install Python and create a virtual environment (venv).
  > This project uses **Python 3.11.15**; Python 3.10+ may work, but this has not been verified.

### 2. Extract resource files

- Extract all `.zip` files from [`models/`](src/resources/for_release_only/models/) into `data/models/`.
- Extract [`ffmpeg`](src/resources/for_release_only/ffmpeg-8.0.1-essentials_build.7z) into `src/resources/ffmpeg/`.
- (Optional) Compile the [`launcher`](src/resources/for_release_only/launcher) and place it in the project root.

### 3. Obtain Majdata Editor & Viewer

Compile [MajdataEdit](https://github.com/ck2739046/MajdataEdit/tree/v4.3.1) & [MajdataView](https://github.com/ck2739046/MajdataView/tree/431-NC-TH) and place the outputs into `src/resources/majdata`.

> *Obtain `SFX` and `Skin` from other sources and put them in the folder.*

### 4. Obtain BPM Measurer

Compile [Bpm-Measurer](https://github.com/ck2739046/Bpm-Measurer) and place the output into `src/resources/Bpm Measurer/`.

### 5. Install & launch

Run `install/script/install.py` to install dependencies.<br>
Run `src/main.py` to launch the application.
