**English** | [**中文**](readme_zh_cn.md)

<div align="center">

<h1>
  <img src="src/resources/icon.ico" width="110" alt="logo">
  <br>HachimiDX
</h1>

<h3>🐱 Maimai auto rechart tool 🐱</h3>

<br>

A tool that converts chart confirmation videos into simai format (`maidata.txt`).

<br>

![](https://img.shields.io/github/stars/ck2739046/HachimiDX?label=Stars)
![](https://img.shields.io/github/downloads/ck2739046/HachimiDX/total?label=Downloads)

📥︎ [**App Download**](https://github.com/ck2739046/HachimiDX/releases/latest)
&nbsp;•&nbsp;
▶️ [**Demo Video**](https://www.bilibili.com/video/BV1Rz5c6vEQH)

</div>

> <img src="src/resources/doc/images/qq_icon.svg" width="14px" style="vertical-align: middle;"> Run into issues, share feedback, or discuss development? Join our QQ group chat **`868888361`**.

<br>



## ✨ Highlights

> Two editions: **Full** and **Lite**. **Lite** has no auto rechart.

- 💪 **Powerful rechart engine**
    - Supports all note types: `tap` `slide` `touch` `hold` `touch-hold`, with duration inference.
    - Supports all note variants: `ex` `break` `ex-break`.
    - Supports all slide syntax: `-` `V` `><` `pq` `ppqq` `sz` `v`.

- 🔍 **Custom AI vision models**
    - Trained specifically on maimai gameplay; robust in complex scenes.

- ⚙️ **Broad hardware support**
    - Supports the ONNX, NCNN and TensorRT inference backends.

- 🪄 **Lots of handy tools**
    - Media transcoding, audio alignment, chart merging, arcade timing analysis, and more.

- 🖥️ **GUI-first design**
    - Everything works through the GUI — no command line required.

- ✏️ **Built-in editor & viewer**
    - Integrates [`MajdataEdit-Neo`](https://github.com/re-poem/MajdataEdit-Neo) and [`MajdataViewX`](https://github.com/re-poem/MajdataViewX) so rechart results can be previewed and modified in one place.

- 🎵 **Built-in BPM measurement tool**
    - Integrates [`BPM-Measurer`](https://github.com/ck2739046/BPM-Measurer) for measuring a song's BPM.






## 💻 Minimum Hardware Requirements

| | **OS** | **Memory** | **Storage**
|---|---|---|---|
| **Lite** | Win10 x64 | 0.5 GB | 1.5 GB |
| **Full** | Win10 x64 | 4 GB | 6 GB |




## 🚧 Known Issues

- Touch/Touch-Hold fireworks effects (`f`) are not supported.

- Fake jumps (`` ` ``) are not supported.

- Footage filmed off the screen may suffer from skew, color shift, abnormal exposure, or ghosting, which can reduce recharting accuracy.

- When multiple slides exist simultaneously and some trajectories overlap or intersect, such slides may fail to be recognized (e.g., `1v6[8:1]/3v6[8:1]`).

- Slide notes with non-standard startup waiting time are not supported.



## 🎯 Data Collection

All training data was collected in-house: a [Mod](archive/yolo-train/mod_dump_notes/Dump_Notes.cs) captures raw game data, and a [script](archive/yolo-train/label_notes.py) automatically generates annotations. Coordinates and categories are highly accurate. This makes dataset construction efficient and scalable, enabling large volumes of high-quality samples on demand.



## 🧩 Tech Stack

- **Python / C#**: development languages
- **PyQt6**: GUI
- **pydantic**: data validation
- **python-i18n**: multi-language support
- **OpenCV**: image processing, auto labeling
- **FFmpeg / FFprobe**: audio/video processing
- **YOLO (ultralytics)**: base model
- **PyTorch / ONNX / TensorRT / NCNN**: model inference
- **BOTSORT + custom OC-SORT**: object tracking
- **librosa**: audio processing
- **Matplotlib**: waveform plotting
- **.NET**: launcher, MajdataEdit
- **Unity (MelonLoader)**: game mod, MajdataView




## 🏃 Running from Source

### 1. Set up the Python environment

- Follow this [`guide`](src/resources/for_release_only/python_portable/用conda创建py环境.md) to create a `python/` folder in the project root, then use `./python/python.exe` to run scripts.

### 2. Extract resource files

- Extract all `.zip` files from [`models/`](src/resources/for_release_only/models/) into `data/models/`.
- Extract [`ffmpeg`](src/resources/for_release_only/ffmpeg-8.0.1-essentials_build.7z) into `src/resources/ffmpeg/`.
- (Optional) Compile the [`launcher`](src/resources/for_release_only/launcher) and place it in the project root.

### 3. Obtain MajdataX

Compile [MajdataEdit-Neo](https://github.com/ck2739046/MajdataEdit-Neo/tree/HachimiDX) & [MajdataViewX](https://github.com/ck2739046/MajdataViewX/tree/HachimiDX) and place the outputs into `src/resources/majdatax`.

> *Obtain `SFX` and `Skin` from other sources and put them in the folder.*

### 4. Obtain BPM-Measurer

Compile [BPM-Measurer](https://github.com/ck2739046/BPM-Measurer) and place the output into `src/resources/BPM-Measurer/`.

### 5. Install & launch

Run `install/script/main.py` to install dependencies.<br>
Run `src/main.py` to launch the application.




## 💖 Donate

If this project helps you, feel free to support it with a donation! ❤️

<div align="center">

<img src="src/resources/doc/images/donate_wechat.png" width="130" alt="WeChat donation QR code">

</div>
