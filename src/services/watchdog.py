import os
import sys
import time
from typing import Optional

import psutil


def _kill_process_tree(pid: int) -> None:
    """强杀 pid 及其整棵子进程树"""
    try:
        root = psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return
    # 先杀所有后代 (递归), 再杀自身
    # children() 单独兜底: 即使枚举失败 (AccessDenied), 仍保证 root 被杀
    try:
        children = root.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        children = []
    for child in children:
        try:
            child.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    try:
        root.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass



def _find_pids_by_process_name(target: str) -> Optional[list[int]]:
    """查根据进程名查找 PID 列表"""

    found_pids = []

    for proc in psutil.process_iter(['pid', 'name']):

        try:
            name = proc.info['name']
            if name and name == target:
                pid = proc.info['pid']
                found_pids.append(pid)

        except Exception:
            pass

    return found_pids if found_pids else None



def _force_kill_process_by_name(target: str) -> None:
    
    result = _find_pids_by_process_name(target)
    if result:
        print(f"Found {len(result)} '{target}' process(es): {result}, will force kill...")
        for pid in result:
            _kill_process_tree(pid)



def shutdown_majdata() -> None:
    """
    查找所有 MajdataView 和 MajdataEdit 窗口并强制关闭
    """

    # 1) Kill MajdataView first (force)
    _force_kill_process_by_name("MajdataViewX.exe")

    # 2) Then kill MajdataEdit (force)
    _force_kill_process_by_name("MajdataEdit-Neo.exe")











def _parent_alive(pid: int, expected_create_time: float) -> bool:
    """检测父进程是否存活"""
    try:
        proc = psutil.Process(pid)
        return proc.create_time() == expected_create_time
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False










def _find_descendant_pids(root_pid: int) -> list[int]:
    """
    返回所有以 root_pid 为祖先的进程 PID
    不含 root 本身、不含 watchdog 自身
    """
    self_pid = os.getpid()
    pid_to_ppid: dict[int, int] = {}
    for proc in psutil.process_iter(['pid', 'ppid']):
        try:
            info = proc.info
            pid = info['pid']
            ppid = info['ppid']
            if pid is None or ppid is None:
                continue
            pid_to_ppid[pid] = ppid
        except Exception:
            pass

    descendants: list[int] = []
    for pid in pid_to_ppid:
        if pid == root_pid or pid == self_pid:
            continue
        cur = pid_to_ppid.get(pid, 0)
        seen: set[int] = set()
        is_desc = False
        while cur > 0 and cur not in seen:
            if cur == root_pid:
                is_desc = True
                break
            seen.add(cur)
            cur = pid_to_ppid.get(cur, 0)
        if is_desc:
            descendants.append(pid)
    return descendants



def shutdown_orphaned_subprocesses(parent_pid: int) -> None:
    """强杀主进程派生的所有残留子进程"""
    pids = _find_descendant_pids(parent_pid)
    if not pids:
        return
    print(f"[watchdog] Found {len(pids)} orphaned descendant process(es): {pids}, force killing...")
    for pid in pids:
        # 强杀每个进程的整棵进程树
        _kill_process_tree(pid)









def main() -> int:
    parent_pid = int(sys.argv[1])

    # 记录父进程创建时间，防止 PID 被回收后又被分配给其他进程
    # 只有创建时间匹配的进程才被认为是原父进程
    try:
        parent_create_time = psutil.Process(parent_pid).create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        print(f"[watchdog] Parent PID {parent_pid} not found at startup, exiting.")
        return 0
    except Exception as e:
        print(f"[watchdog] Error checking parent process at startup: {e}, exiting.")
        return 0

    print(f"[watchdog] Started, watching parent PID {parent_pid}")

    while True:
        if not _parent_alive(parent_pid, parent_create_time):
            print(f"[watchdog] Parent PID {parent_pid} is gone, cleaning up...")
            shutdown_orphaned_subprocesses(parent_pid)
            shutdown_majdata()
            print("[watchdog] Cleanup done, exiting.")
            return 0
        time.sleep(0.02)


if __name__ == "__main__":
    sys.exit(main())
