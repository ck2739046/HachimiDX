import json
import socket
import threading
import time
import traceback


# 允许 start/continue 指令中的时间，与自身的 last_position 相差一定时间
# 如果超过允许的误差值，则执行 setPosition 以校正播放位置
_TIME_TOLERANCE_SEC = 0.03

# 用户在 majdataedit 拖动音频条调整进度的时候会在短时间产生大量 setPosition 指令
# 设置防抖，超过此时间间隔没有收到新的 setPosition 指令时，才发送最后一个 setPosition 指令到 UI 线程
_DEBOUNCE_SEC = 0.06

# 本程序监听的 UDP 端口
_PORT = 8014




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
        self._pending_play_token = 0      # 调度/取消时自增以使旧回调失效；触发或取消后重置为 0
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
                    self.handle_message(message)

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








    def handle_message(self, data) -> None:

        msg_type = data.get("type")
        try:
            if msg_type == "play":
                self._handle_play(data)
            elif msg_type == "pause":
                self._handle_pause(data)
            elif msg_type == "seek":
                self._handle_set_position(data)
            # 忽略 ack / 未知类型

        except Exception as e:
            print(f"[VideoSync] Error handling {msg_type}: {e}")
            traceback.print_exc()








    def _cancel_pending_play(self) -> None:
        """取消尚未触发的延迟播放（OpStart 倒计时期间收到 pause/seek 时调用）"""
        with self._play_timer_lock:
            if self._pending_play_timer is not None:
                self._pending_play_timer.cancel()
                self._pending_play_timer = None
            self._pending_play_token = 0  # reset token


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
                # 延迟播放已触发，重置 token
                self._pending_play_token = 0
            self._dispatch_ui(play_action)

        timer = threading.Timer(delay, fire)
        with self._play_timer_lock:
            if token != self._pending_play_token:
                # 加锁期间被并发取消/取代，丢弃本次调度
                timer.cancel()
                return
            self._pending_play_timer = timer

        timer.start()



    def _video_time(self, position: float, data) -> float:
        """音频时间换算为视频时间：video = max(0, audio - pvOffset)"""
        pv_offset = float(data.get("pvOffset", 0.0))
        return max(0.0, position - pv_offset)


    def _handle_play(self, data) -> None:

        start_time = float(data.get("position", 0.0))  # Audio position in seconds
        playback_speed = float(data.get("speed", 1.0))
        delay_seconds = float(data.get("delaySeconds", 0.0))
        video_time = self._video_time(start_time, data)

        # 清除未处理的 setPosition 请求
        self._setpos_pending_position = None

        def play_action():
            try:
                mp = self.media_player
                if not mp or not mp.hasVideo(): return  # 让 ui thread 判断有没有视频

                if self.last_play_speed != playback_speed:
                    mp.setPlaybackRate(playback_speed)
                    self.last_play_speed = playback_speed

                if self.last_position is None or abs(self.last_position - video_time) >= _TIME_TOLERANCE_SEC:
                    mp.setPosition(int(video_time * 1000))
                    self.last_position = video_time

                mp.play()

                print(f"[VideoSync] Play, at {video_time:.3f}s")
            except Exception as e:
                print(f"[VideoSync] UI play_action error: {e}")


        # delaySeconds=0 立即播放；否则（OpStart）延迟到点再播放
        if delay_seconds <= _TIME_TOLERANCE_SEC:
            self._cancel_pending_play()
            self._dispatch_ui(play_action)
            return

        self._schedule_delayed_play(delay_seconds, play_action)
        print(f"[VideoSync] Play scheduled in {delay_seconds:.3f}s, at {video_time:.3f}s")






    def _handle_pause(self, data) -> None:

        start_time = float(data.get("position", 0.0))
        video_time = self._video_time(start_time, data)

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
                mp.setPosition(int(video_time * 1000))
                self.last_position = video_time

                print(f"[VideoSync] Pause, at {video_time:.3f}s")
            except Exception as e:
                print(f"[VideoSync] UI pause_action error: {e}")

        self._dispatch_ui(pause_action)















    def _handle_set_position(self, data) -> None:

        # 取消 OpStart 倒计时中尚未触发的延迟播放
        self._cancel_pending_play()

        position_time = float(data.get("position", 0.0))
        video_time = self._video_time(position_time, data)

        # 更新待发送位置和最后接收时间
        self._setpos_pending_position = video_time
        self._setpos_last_received_time = time.monotonic()

        # 检查是否已超过防抖间隔
        self._process_scheduled_actions()









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
