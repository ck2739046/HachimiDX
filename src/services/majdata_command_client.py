import json
import socket
import threading
from typing import Optional


class MajdataCommandClient:
    """
    HachimiDX -> Edit-Neo 的 UDP 指令发送器
    127.0.0.1:8015
    seq+ack+重试
    """

    EDIT_HOST = "127.0.0.1"
    EDIT_PORT = 8015
    RETRY_COUNT = 3
    ACK_TIMEOUT_SEC = 0.3

    _instance = None

    @classmethod
    def get_instance(cls) -> "MajdataCommandClient":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def shutdown_instance(cls) -> None:
        cls._instance = None

    def __init__(self):
        self._seq = 0
        self._seq_lock = threading.Lock()

    def _next_seq(self) -> int:
        with self._seq_lock:
            self._seq += 1
            return self._seq




    def _send_command(self, payload: dict) -> bool:
        """同步发送并等待 ack，带重试。成功返回 True"""
        seq = self._next_seq()
        msg = {"v": 1, "seq": seq, **payload}
        data = json.dumps(msg).encode("utf-8")

        for _ in range(self.RETRY_COUNT):
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind((self.EDIT_HOST, 0))
            s.settimeout(self.ACK_TIMEOUT_SEC)
            try:
                s.sendto(data, (self.EDIT_HOST, self.EDIT_PORT))
                resp, _ = s.recvfrom(65535)
                ack = json.loads(resp.decode("utf-8"))
                if ack.get("type") == "ack" and ack.get("seq") == seq:
                    status = ack.get("status")
                    if status != "ok":
                        print(f"[MajdataCmd] ack error: {ack.get('error')}")
                    return status == "ok"
            except socket.timeout:
                continue
            except OSError as e:
                print(f"[MajdataCmd] send failed: {e}")
                return False
            finally:
                s.close()

        print("[MajdataCmd] no ack after retries")
        return False



    def _send_command_bg(self, payload: dict) -> None:
        """后台线程发送，避免阻塞 UI"""
        threading.Thread(target=lambda: self._send_command(payload), daemon=True).start()







    # 公开 api

    def send_load(self,
                  folder: str,
                  maidata: str,
                  track: str,
                  pv: Optional[str] = None
                 ) -> None:
        payload = {"type": "load", "folder": folder, "maidata": maidata, "track": track}
        if pv:
            payload["pv"] = pv
        self._send_command_bg(payload)

    def send_reset(self) -> None:
        self._send_command_bg({"type": "reset"})

    def send_exit(self) -> None:
        self._send_command_bg({"type": "exit"})
