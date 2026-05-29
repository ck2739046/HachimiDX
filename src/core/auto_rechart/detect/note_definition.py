from dataclasses import dataclass
import time
from dataclasses import dataclass
from enum import Enum


class NoteVariant(Enum):
    NORMAL = "normal"
    BREAK = "break"
    EX = "ex"
    BREAK_EX = "break_ex"


class NoteType(Enum):
    TAP = "tap"
    SLIDE = "slide"
    TOUCH = "touch"
    HOLD = "hold"
    TOUCH_HOLD = "touch_hold"


@dataclass(slots=True)
class Note_Geometry:

    frame: int
    note_type: NoteType
    note_variant: NoteVariant
    conf: float

    x1: float
    y1: float
    x2: float
    y2: float
    x3: float
    y3: float
    x4: float
    y4: float

    cx: float
    cy: float
    w: float
    h: float
    r: float


def map_model_class_to_note_type(model_type, index) -> NoteType:
    if model_type == 'obb':
        if index == 0: return NoteType.HOLD
    else: # detect
        if index == 0: return NoteType.TAP
        if index == 1: return NoteType.SLIDE
        if index == 2: return NoteType.TOUCH
        if index == 3: return NoteType.TOUCH_HOLD


def map_note_type_to_class_id(note_type: NoteType) -> int:
    if note_type == NoteType.TAP:
        return 0
    if note_type == NoteType.SLIDE:
        return 1
    if note_type == NoteType.TOUCH:
        return 2
    if note_type == NoteType.HOLD:
        return 3
    if note_type == NoteType.TOUCH_HOLD:
        return 4
    return 0 # 不应该发生


def is_obb(note_type: NoteType) -> bool:
    return note_type == NoteType.HOLD


def need_cls(note_type: NoteType) -> bool:
    return note_type in [NoteType.TAP, NoteType.SLIDE, NoteType.HOLD]
    

def get_imgsz(model_name: str) -> int:
    if model_name in ('detect', 'obb'):
        return 960
    elif "touch_hold" in model_name:
        return 224
    else:
        # cls-ex, cls-break
        return 224


def print_progress(name, speed_unit, counter, total, last_time, last_counter):
    # 计算即时fps
    current_time = time.time()
    elapsed_time = current_time - last_time + 1e-6
    elapsed_counter = counter - last_counter
    speed = elapsed_counter / elapsed_time
    # 打印进度
    progress = (counter / total) * 100
    print(f"{name} progress: {counter}/{total} ({progress:.1f}%), {speed:.1f}{speed_unit}  ", end="\r", flush=True)
    return current_time, counter
