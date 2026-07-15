import json
import socket
import threading
import time
import traceback
from datetime import datetime, timedelta
from PyQt6.QtCore import QUrl


# 允许 start/continue 指令中的时间，与自身的 last_position 相差 60ms
# 如果超过 60ms 则执行 setPosition 以校正播放位置

# 这个误差来自于 majdataedit/majdataview 有各自的时间轴
# start/continue 指令从 majdataedit 发出
# pause 指令从 majdataview 发出
# 即使只是原地 pause 再 continue，也会有时间差
_TIME_TOLERANCE_SEC = 0.06

# 用户在 majdataedit 拖动音频条调整进度的时候会在短时间产生大量 setPosition 指令
# 设置防抖，超过此时间间隔没有收到新的 setPosition 指令时，才发送最后一个 setPosition 指令到 UI 线程
_DEBOUNCE_SEC = 0.06

# 本程序监听的 UDP 端口
_PORT = 8014

# .NET DateTime.Now.Ticks 的纪元起点
# MajdataEdit 发来的 startAt 是本地时间（DateTime.Now.Ticks），这里用本地 naive datetime 对齐
_DOTNET_EPOCH = datetime(1, 1, 1)




class VideoSyncServer:

    _instance = None

    @classmethod
    def get_instance(cls) -> "VideoSyncServer":
        if cls._instance is None:
            cls._instance = cls()
            cls._instance.start()
        return cls._instance

    @classmethod
    def shutdown_instance(cls) -> None:
        if cls._instance is not None:
            try:
                cls._instance.stop()
            finally:
                cls._instance = None



    def __init__(self):

        # 这两个后续会在 main_window 中设置
        self.media_player = None
        self.main_thread_callback = None

        self.listen_port = _PORT

        self.server_thread = None
        self.udp_socket = None
        self.running = False

        # Last applied state
        self.last_play_speed = None
        self.last_position = None

        # 防抖
        self._setpos_pending_position: float = None    # 待发送的位置
        self._setpos_last_received_time: float = None  # 最后接收时间
        self._setpos_last_sent_pos: float = None       # 上次发送的 setPosition 位置

        # 延迟播放调度：到 startAt 指定的未来时刻再播放，且可取消
        self._pending_play_timer = None   # threading.Timer 引用
        self._pending_play_token = 0      # 每次调度/取消自增，回调用它校验自己是否仍有效
        self._play_timer_lock = threading.Lock()



    def start(self) -> None:
        if self.running:
            return

        self.running = True

        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
        self.udp_socket.bind(("localhost", self.listen_port))
        self.udp_socket.settimeout(_DEBOUNCE_SEC + 0.001) # 设置 timeout 为防抖周期

        print(f"[VideoSync] Server started on port {self.listen_port}")

        def run_server():
            while self.running:
                try:
                    data, addr = self.udp_socket.recvfrom(65535)
                    message = json.loads(data.decode("utf-8"))

                    # Handle message directly
                    self.handle_control_message(message)

                except socket.timeout:
                    # 超时：超过一定时间没有收到新数据包
                    # 此时触发防抖处理，可以确保最后一个防抖周期内的 setPosition 被发送出去
                    self._process_scheduled_actions()
                    continue

                except Exception as e:
                    if self.running:
                        print(f"[VideoSync] Error: {e}")

        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()



    def stop(self) -> None:
        if not self.running:
            return

        self.running = False

        # Cancel pending setPosition debounce
        self._setpos_pending_position = None

        # 关闭 udp socket
        if self.udp_socket:
            try:
                self.udp_socket.close()
            except Exception:
                pass
            self.udp_socket = None

        # 多等一会儿让线程自然退出
        try:
            if self.server_thread and self.server_thread.is_alive():
                self.server_thread.join(timeout=_DEBOUNCE_SEC * 3)
        except Exception:
            pass

        print("[VideoSync] Server stopped")



    def set_media_player(self, media_player) -> None:
        self.media_player = media_player

    def set_main_thread_callback(self, callback) -> None:
        self.main_thread_callback = callback


    
    def _dispatch_ui(self, action) -> None:
        cb = self.main_thread_callback
        if cb is None:
            return
        try:
            cb(action)
        except Exception:
            pass








    def handle_control_message(self, data) -> None:

        control_value = data.get("control")
        try:
            if control_value in (0, 2, 4):  # Start / OpStart / Continue
                self._handle_play(data)
            elif control_value == 1:        # Stop
                self._handle_stop(data)
            elif control_value == 3:        # Pause
                self._handle_pause(data)
            elif control_value == 273:      # Set Position
                self._handle_set_position(data)
            elif control_value == 274:      # Unload video
                self._handle_unload_video(data)

        except Exception as e:
            control_map = {
                0: "Start",
                1: "Stop",
                2: "OpStart",
                3: "Pause",
                4: "Continue",
                5: "Record",
                273: "SetPosition",
                274: "UnloadVideo",
            }
            control_name = control_map.get(control_value, f"Unknown({control_value})")
            print(f"[VideoSync] Error handling {control_name}: {e}")
            traceback.print_exc()








    def _cancel_pending_play(self) -> None:
        """取消尚未触发的延迟播放（OpStart 倒计时期间收到 stop/pause/unload/setPosition 时调用）。"""
        with self._play_timer_lock:
            if self._pending_play_timer is not None:
                self._pending_play_timer.cancel()
                self._pending_play_timer = None
            self._pending_play_token += 1


    def _compute_play_delay(self, data) -> float:
        """从 data.startAt（.NET ticks，本地时间）换算距现在还需等待的秒数"""
        start_at_ticks = data.get("startAt")
        if start_at_ticks is None:
            return 0.0
        try:
            target_local = _DOTNET_EPOCH + timedelta(seconds=float(start_at_ticks) / 1e7)
            return max(0.0, (target_local - datetime.now()).total_seconds())
        except (TypeError, ValueError):
            return 0.0


    def _schedule_delayed_play(self, delay: float, play_action) -> None:
        """延迟播放：threading.Timer 到点 dispatch，期间可被取消/取代"""
        with self._play_timer_lock:
            if self._pending_play_timer is not None:
                self._pending_play_timer.cancel()
            self._pending_play_token += 1
            token = self._pending_play_token

        def fire():
            with self._play_timer_lock:
                if token != self._pending_play_token:
                    return  # 已被取消或被新的 play 取代
                self._pending_play_timer = None
            self._dispatch_ui(play_action)

        timer = threading.Timer(delay, fire)
        with self._play_timer_lock:
            if token != self._pending_play_token:
                # 加锁期间被并发取消/取代，丢弃本次调度
                timer.cancel()
                return
            self._pending_play_timer = timer

        timer.start()



    def _handle_play(self, data) -> None:

        start_time = float(data.get("startTime", 0.0))  # Audio position in seconds
        playback_speed = float(data.get("audioSpeed", 1.0))

        # 清除未处理的 setPosition 请求
        self._setpos_pending_position = None

        def play_action():
            try:
                mp = self.media_player
                if not mp or not mp.hasVideo(): return  # 让 ui thread 判断有没有视频

                if self.last_play_speed != playback_speed:
                    mp.setPlaybackRate(playback_speed)
                    self.last_play_speed = playback_speed

                if self.last_position is None or abs(self.last_position - start_time) >= _TIME_TOLERANCE_SEC:
                    mp.setPosition(int(start_time * 1000))
                    self.last_position = start_time

                mp.play()

                print(f"[VideoSync] Play, at {start_time:.3f}s")
            except Exception as e:
                print(f"[VideoSync] UI play_action error: {e}")


        # 解析 startAt 换算距现在的延迟
        # OpStart 有 5 秒延迟，需延迟到点再播放
        delay = self._compute_play_delay(data)

        # 如果延迟小于等于 60ms，立即播放，否则延迟播放
        if delay <= _TIME_TOLERANCE_SEC:
            self._cancel_pending_play()
            self._dispatch_ui(play_action)
            return

        # 延迟播放：threading.Timer 到点 dispatch，期间可被取消
        self._schedule_delayed_play(delay, play_action)
        print(f"[VideoSync] Play scheduled in {delay:.3f}s, at {start_time:.3f}s")






    def _handle_pause(self, data) -> None:

        start_time = float(data.get("startTime", 0.0))

        # 取消 OpStart 倒计时中尚未触发的延迟播放
        self._cancel_pending_play()

        # 清除未处理的 setPosition 请求
        self._setpos_pending_position = None

        def pause_action():
            try:
                mp = self.media_player
                if not mp or not mp.hasVideo(): return

                mp.pause()

                # 精准时间点，总是 setPosition
                mp.setPosition(int(start_time * 1000))
                self.last_position = start_time

                print(f"[VideoSync] Pause, at {start_time:.3f}s")
            except Exception as e:
                print(f"[VideoSync] UI pause_action error: {e}")

        self._dispatch_ui(pause_action)









    def _handle_stop(self, data) -> None:

        # 取消 OpStart 倒计时中尚未触发的延迟播放
        self._cancel_pending_play()

        # 清除未处理的 setPosition 请求
        self._setpos_pending_position = None

        def stop_action():
            try:
                mp = self.media_player
                if not mp or not mp.hasVideo(): return

                mp.pause() # 把 stop 当作 pause 处理

                print(f"[VideoSync] Stop")
            except Exception as e:
                print(f"[VideoSync] UI stop_action error: {e}")

        self._dispatch_ui(stop_action)







    def _handle_set_position(self, data) -> None:

        # 取消 OpStart 倒计时中尚未触发的延迟播放
        self._cancel_pending_play()

        position_time = float(data.get("position", 0.0))

        # 更新待发送位置和最后接收时间
        self._setpos_pending_position = position_time
        self._setpos_last_received_time = time.monotonic()

        # 检查是否已超过防抖间隔
        self._process_scheduled_actions()





    def _handle_unload_video(self, data) -> None:

        # 取消 OpStart 倒计时中尚未触发的延迟播放
        self._cancel_pending_play()

        # 清除未处理的 setPosition 请求
        self._setpos_pending_position = None

        def unload_action():
            try:
                mp = self.media_player
                if not mp or not mp.hasVideo(): return

                mp.stop()
                mp.setSource(QUrl())

                # 重置状态
                self.last_position = None
                self.last_play_speed = None
                self._setpos_last_sent_pos = None

                print(f"[VideoSync] Unload video executed")
            except Exception as e:
                print(f"[VideoSync] UI unload_action error: {e}")

        self._dispatch_ui(unload_action)





    def _process_scheduled_actions(self) -> None:

        if self._setpos_pending_position is None:
            return
        
        now = time.monotonic()
        if self._setpos_last_received_time is None:
            return
        
        # 检查是否已超过防抖间隔
        if now - self._setpos_last_received_time < _DEBOUNCE_SEC:
            return
        
        # 准备发送
        position = self._setpos_pending_position
        
        # 检查是否与上次发送的位置相同
        if self._setpos_last_sent_pos is not None and self._setpos_last_sent_pos == position:
            # 重复位置，跳过
            self._setpos_pending_position = None
            return
        
        # 发送 setPosition 指令到 UI 线程
        def set_position_action():
            try:
                mp = self.media_player
                if not mp or not mp.hasVideo(): return

                mp.setPosition(int(position * 1000))

                self.last_position = position
                self._setpos_last_sent_pos = position

            except Exception as e:
                print(f"[VideoSync] UI set_position_action error: {e}")
        
        self._dispatch_ui(set_position_action)
        
        # 清除待发送位置
        self._setpos_pending_position = None
