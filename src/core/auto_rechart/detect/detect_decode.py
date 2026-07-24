from ultralytics import YOLO
import cv2
import os
import time
import traceback
import torch
import torch.utils.data
import torch.multiprocessing as tmp
from queue import Empty, Full
from pathlib import Path
import numpy as np
from collections import defaultdict
from dataclasses import dataclass, field

from ...schemas.op_result import OpResult, ok, err
from .note_definition import *




def create_decoder(std_video_path: str, imgsz: int, batch_size: int) -> torch.utils.data.DataLoader:
    dataset = _VideoFrameDataset(std_video_path, imgsz)
    dataloader = torch.utils.data.DataLoader(
        dataset,
        batch_size=batch_size,
        num_workers=1,
        collate_fn=_to_list,
        persistent_workers=False,
        timeout=30,
    )
    return dataloader




def _to_list(batch):
    return list(batch)




class _VideoFrameDataset(torch.utils.data.IterableDataset):

    def __init__(self, std_video_path: str, imgsz: int):
        super().__init__()
        self._std_video_path = std_video_path
        self._imgsz = (imgsz, imgsz)

    def __iter__(self):
        cap = cv2.VideoCapture(self._std_video_path)
        try:
            while True:
                # 读取视频帧
                ret, frame = cap.read()
                if not ret:
                    break
                # 提前 resize 好
                frame = cv2.resize(frame, self._imgsz, interpolation=cv2.INTER_LINEAR)
                yield frame
        finally:
            cap.release()
