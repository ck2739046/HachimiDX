import cv2
import torch
import torch.utils.data

from ...schemas.op_result import OpResult, ok, err



class Decoder:
    """
    api:
    - __init__(std_video_path, imgsz, batch_size)
    - get_next_batch() -> OpResult[List[(frame_idx, frame)]]
                          ok(value=None) 表示 eof 解码完毕
    - close()
    """

    _TIMEOUT = 5.0  # timeout for collecting a batch from workers

    def __init__(self, std_video_path: str, imgsz: int, batch_size: int):

        dataset = _VideoFrameDataset(std_video_path, imgsz)

        self._loader = torch.utils.data.DataLoader(
            dataset,
            batch_size=batch_size,
            num_workers=1,
            collate_fn=_to_list,
            persistent_workers=False,
            timeout=self._TIMEOUT,
        )

        self._iter = iter(self._loader)  # 预热: 尽早启动 worker

        self._eof = False                # 正常解码完毕后为 True
        self._failed = False             # 报错时为 True
        self._force_closed = False       # 仅在用户主动关闭解码器时为 True



    def get_next_batch(self) -> OpResult:
        """取下一个 batch, 返回 OpResult"""
        
        if self._force_closed:
            return err("[decoder] get_next_batch: decoder already force closed.")
        if self._failed:
            return err("[decoder] get_next_batch: decoder already failed.")
        if self._eof:
            return ok(value=None)

        try:
            # 获取下一个 batch
            batch = next(self._iter)
        except StopIteration:
            # 视频解码完毕
            self._eof = True
            return ok(value=None)
        except Exception as e:
            # cv2 解码失败 / worker 死亡 / timeout 等
            self._failed = True
            return err(f"[decoder] get_next_batch: decoder error: {e}", error_raw=e)

        return ok(value=batch)  # 成功拿到 batch



    def close(self):
        if self._force_closed:
            return
        self._force_closed = True
        self._eof = True
        self._failed = True
        _shutdown_loader(self._loader)



def _to_list(batch):
    return list(batch)



def _shutdown_loader(loader):
    """强制关闭 dataloader worker"""

    # 通过销毁 iterator 触发 dataloader 内部 _shutdown_workers 实现
    try:
        it = getattr(loader, "_iterator", None)
        if it is not None:
            shutdown = getattr(it, "_shutdown_workers", None)
            if shutdown is not None:
                shutdown()
            loader._iterator = None
    except Exception as e:
        print(f"[decoder] _shutdown_loader failed: {e}")



class _VideoFrameDataset(torch.utils.data.IterableDataset):

    def __init__(self, std_video_path: str, imgsz: int):
        super().__init__()
        self._std_video_path = std_video_path
        self._imgsz = (imgsz, imgsz)

    def __iter__(self):
        cap = cv2.VideoCapture(self._std_video_path)
        if not cap.isOpened():
            raise RuntimeError(f"Failed to open video file: {self._std_video_path}")
        try:
            frame_idx = 0
            while True:
                # 读取视频帧
                ret, frame = cap.read()
                if not ret:
                    break  # 触发 StopIteration

                # 此处提前 resize 好可以避免在推理内部 resize 从而加快推理速度
                # 目前 detect/obb imgsz 相同所以能这么干
                frame = cv2.resize(frame, self._imgsz, interpolation=cv2.INTER_LINEAR)

                yield (frame_idx, frame)
                frame_idx += 1

        # 不需要显式 except Exception
        # DataLoader 会自动捕获异常并由 next(self._iter) 处理
        finally:
            cap.release()
