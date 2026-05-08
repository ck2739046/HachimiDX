# <img src="src/resources/icon.ico" width="60px"> HachimiDX-Convert 🐱

🔗 [**Project URL**](https://github.com/ck2739046/HachimiDX-Convert)
&nbsp;•&nbsp;
📖 [**中文 README**](readme_zh_cn.md)



A tool designed for the rhythm game `maimai`. Accepts chart confirmation videos and automatically outputs simai-format charts (`maidata.txt`).



## ✨ Highlights

- **Fully automatic chart conversion**
    - Supports recognition and duration inference for all note types: tap, slide, touch, hold, and touch-hold.
    - Supports variant classification for ex-note, break-note, and ex-break-note.
    - Supports automatic syntax inference for all slide notations.

- **Custom vision models**
    - Optimized specifically for maimai, with stronger robustness in complex scenes.

- **GUI-first design**
    - Everything is done through a visual interface.

- **Built-in editors**
    - Integrates [`MajdataEdit`](https://github.com/LingFeng-bbben/MajdataView) and [`MajdataView`](https://github.com/TeamMajdata/MajdataView/tree/431-NC-TH) so convertion results can be previewed and modified in one place.

- **Flexible inference backends**
    - Supports PyTorch / NVIDIA TensorRT / DirectML inference backends for compatibility with a range of hardware.

- **Handy multimedia tools**
    - Trim videos, sync audio, convert formats, adjust arcade timing, etc.





## 🎯 Model Training Data

All training data was gathered in-house:

- **Automated labeling**
    - A [Mod](archive/yolo-train/mod_dump_notes/Dump_Notes.cs) captures raw game data. A [script](archive/yolo-train/label_notes.py) turns it into annotations automatically. Coordinates and categories are highly accurate. This makes dataset construction efficient and convenient, and it can quickly produce large amounts of high-quality samples on demand.

- **Task-specific training**
    - Each of the three models uses a dedicated dataset and is optimized for its own task.
    - `train_detect` — identifies note positions
    - `train_obb` — identifies slide rotation angles
    - `train_classify` — determines variants such as ex and break




## 🧩 Technical Architecture

Code lives in `src/`, organized in three layers:

- **UI layer (`src/app`)**
    - Built with Qt.
    - Each feature has its own page.
    - Shared widget library ensures a consistent visual style and user experience.
- **Middle layer (`src/services`)**
    - Manages task queues, controls concurrency, and distribute status.
    - Subtasks run in separate QProcess instances, managed by a process manager.
    - Uses pydantic to validate params and build commands.
    - Services are modular, each with a clear role.
    - Exposes a unified API for frontend. 
- **Core layer (`src/core`)**
    - OpenCV for frame processing.
    - YOLO for visual recognition.
    - Elements path tracking.
    - Filters, converts, and processes data.
    - Infers note position, timing, and duration.
    - Converts to simai syntax.
    - Performs audio matching, synchronization, and arcade timing inference.




## 🚧 Known Issues

- **Touch / Touch-Hold**
    - Overlapping notes at the same spot are not supported.
    - Fireworks effects (`f`) are not supported.

 - Fake jumps (`` ` ``) are not supported.

- Songs are assumed to have a fixed BPM throughout and do not support BPM changes.

- Camera-captured footage (off-screen recordings) may suffer from angle, color cast, or exposure issues. This hurts accuracy for ex/break classification.



## 🏃 Running from Source

The release package ships with an embedded Python 3.13 interpreter, so no pre-installed Python is required. To run from source, there are two approaches:

1. Extract [`embedded_python`](src/resources/for_release_only/python%20portable/py3.13.11.zip) to the project root directory, then use `./python/python.exe` to run scripts.
2. Install Python and create a virtual environment (venv).

After setting up the Python environment, run `install/script/install.py` to install project dependencies, then run `main.py` to launch the application.

**Minimum supported version:** Python 3.10, 3.11, and 3.12 may work, but this is only a rough guess and has not been verified.

> **Note (2026.05.09):**<br>
> NVIDIA TensorRT currently does not support Python 3.14. When using `DirectML` or `PyTorch` inference, Python 3.14 works fine. For `TensorRT`, Python 3.13 is the highest supported version.
