import os
import glob
import time
from enum import Enum
from typing import Dict, List, Optional, Tuple
import psutil
from antigravity_monitor import AgentState
from config import load_config

class ClaudeMonitor:
    """
    Monitors Claude Desktop client for active generation/streaming in Standard Chat.
    Uses continuous process CPU measurement across persistent Process handles,
    LevelDB write tracking, and MCP log signals with a robust hysteresis hold-off
    timer to prevent state flapping during LLM token streaming.
    """
    CLAUDE_LOGS = os.path.expandvars(r"%LOCALAPPDATA%\Claude\logs")
    DEFAULT_HOLD_TIME_SEC = 3.5

    def __init__(self):
        # Persistent mapping: pid -> psutil.Process to prevent CPU counter resets
        self._proc_map: Dict[int, psutil.Process] = {}
        self._proc_types: Dict[int, str] = {}
        self._last_proc_refresh: float = 0
        self._last_active_time: float = 0
        self._consecutive_active_ticks: int = 0
        self._is_running: bool = False
        self._storage_dir: Optional[str] = self._resolve_storage_dir()
        self._current_state: AgentState = AgentState.IDLE

    def _resolve_storage_dir(self) -> Optional[str]:
        """Resolves Claude's local storage directory across MSIX and standard installations."""
        msix_pattern = os.path.expandvars(
            r"%LOCALAPPDATA%\Packages\*Claude*\LocalCache\Roaming\Claude"
        )
        matches = glob.glob(msix_pattern)
        if matches:
            return matches[0]

        roaming = os.path.expandvars(r"%APPDATA%\Claude")
        if os.path.exists(roaming):
            return roaming

        return None

    def _get_leveldb_mtime(self) -> float:
        """Returns the most recent modification time of Claude's LevelDB log files."""
        if not self._storage_dir:
            self._storage_dir = self._resolve_storage_dir()
        if not self._storage_dir:
            return 0.0

        leveldb_dir = os.path.join(self._storage_dir, "Local Storage", "leveldb")
        if not os.path.exists(leveldb_dir):
            return 0.0

        try:
            log_files = glob.glob(os.path.join(leveldb_dir, "*.log"))
            if not log_files:
                return 0.0
            return max(os.path.getmtime(f) for f in log_files)
        except Exception:
            return 0.0

    def is_running(self) -> bool:
        """
        Lightweight check if Claude Desktop processes are running.
        Maintains persistent psutil.Process handles to avoid resetting CPU baselines.
        """
        now = time.time()
        if now - self._last_proc_refresh < 4.0 and self._proc_map:
            alive = {}
            for pid, p in self._proc_map.items():
                try:
                    if p.is_running():
                        alive[pid] = p
                except Exception:
                    pass
            self._proc_map = alive
            self._is_running = len(self._proc_map) > 0
            return self._is_running

        self._last_proc_refresh = now
        new_map: Dict[int, psutil.Process] = {}
        new_types: Dict[int, str] = {}

        try:
            for p in psutil.process_iter(['name', 'pid', 'cmdline']):
                if (p.info['name'] or '').lower() == 'claude.exe':
                    pid = p.info['pid']
                    cmd = p.info.get('cmdline') or []
                    ptype = "main"
                    for arg in cmd:
                        if arg.startswith('--type='):
                            ptype = arg.split('=')[1]
                            break

                    if pid in self._proc_map:
                        new_map[pid] = self._proc_map[pid]
                    else:
                        try:
                            p.cpu_percent(None)
                        except Exception:
                            pass
                        new_map[pid] = p

                    new_types[pid] = ptype
        except Exception:
            pass

        self._proc_map = new_map
        self._proc_types = new_types
        self._is_running = len(new_map) > 0
        return self._is_running

    def _sample_cpu(self) -> float:
        """Calculates combined CPU percentage across all Claude processes."""
        total_cpu, _ = self.sample_detailed_cpu()
        return total_cpu

    def sample_detailed_cpu(self) -> Tuple[float, float]:
        """Calculates (total_cpu, renderer_cpu) across all Claude processes."""
        if not self._proc_map:
            return 0.0, 0.0

        total_cpu = 0.0
        renderer_cpu = 0.0
        dead_pids = []

        for pid, p in self._proc_map.items():
            try:
                c = p.cpu_percent(None)
                total_cpu += c
                if self._proc_types.get(pid) == 'renderer':
                    renderer_cpu += c
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                dead_pids.append(pid)

        for pid in dead_pids:
            self._proc_map.pop(pid, None)
            self._proc_types.pop(pid, None)

        return total_cpu, renderer_cpu

    def _check_mcp_waiting(self) -> bool:
        """Checks if an MCP tool call was requested and is waiting for user approval."""
        mcp_log = os.path.join(self.CLAUDE_LOGS, "mcp.log")
        if not os.path.exists(mcp_log):
            return False
        try:
            mtime = os.path.getmtime(mcp_log)
            if time.time() - mtime > 60.0:
                return False

            with open(mcp_log, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            for line in reversed(lines[-20:]):
                if 'tools/call' in line:
                    return True
                if 'tools/list' in line or 'result' in line:
                    break
        except Exception:
            pass
        return False

    def get_state(self) -> AgentState:
        """
        Determines current state of Claude Desktop:
        - OFF: Claude is not running
        - WORKING: Claude is actively streaming tokens / generating
        - WAITING_APPROVAL: Tool approval or prompt waiting
        - IDLE: Claude is idle waiting for user prompt
        """
        if not self.is_running():
            self._consecutive_active_ticks = 0
            self._last_active_time = 0
            self._current_state = AgentState.OFF
            return AgentState.OFF

        # 1. Check MCP tool approval wait
        if self._check_mcp_waiting():
            return AgentState.WAITING_APPROVAL

        # 2. Sample CPU and storage signals
        now = time.time()
        total_cpu, renderer_cpu = self.sample_detailed_cpu()
        leveldb_mtime = self._get_leveldb_mtime()
        leveldb_recent = (now - leveldb_mtime < 2.5) if leveldb_mtime > 0 else False

        # Active generation indicators:
        # 1. Renderer process active (token layout, markdown parsing, and paint): renderer_cpu > 1.0%
        # 2. Significant Claude total activity with renderer participation: total_cpu > 3.5% and renderer_cpu > 0.3%
        # 3. Active LevelDB persistence accompanied by renderer activity: leveldb_recent and renderer_cpu > 0.8%
        is_active_now = (
            renderer_cpu > 1.0 or
            (total_cpu > 3.5 and renderer_cpu > 0.3) or
            (leveldb_recent and renderer_cpu > 0.8)
        )

        cfg = load_config()
        timings = cfg.get("timings", {})
        hold_time_sec = timings.get("claude_hold_time_sec", self.DEFAULT_HOLD_TIME_SEC)

        if is_active_now:
            self._consecutive_active_ticks += 1
            self._last_active_time = now
        else:
            self._consecutive_active_ticks = max(0, self._consecutive_active_ticks - 1)

        # To enter WORKING from IDLE: require 2 consecutive active ticks (filters out single cursor/repaint blips)
        if self._current_state != AgentState.WORKING:
            if self._consecutive_active_ticks >= 2:
                self._current_state = AgentState.WORKING
                return AgentState.WORKING
            return AgentState.IDLE

        # If already in WORKING: hold state through inter-token pauses until hold_time_sec elapses
        if self._last_active_time > 0 and (now - self._last_active_time < hold_time_sec):
            return AgentState.WORKING

        # Hold time elapsed -> transition back to IDLE
        self._current_state = AgentState.IDLE
        return AgentState.IDLE

if __name__ == "__main__":
    monitor = ClaudeMonitor()
    print("Claude running:", monitor.is_running())
    # Prime CPU counters
    monitor._sample_cpu()
    time.sleep(0.5)
    print("Claude state:", monitor.get_state().value)

