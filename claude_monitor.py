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
    Uses multi-modal tracking:
    - Persistent Process handles with continuous CPU sampling (renderer vs total)
    - Process I/O transfer deltas (SSE network stream & disk write detection)
    - Multi-directory storage tracking (IndexedDB, Local Storage, Session Storage)
    - MCP log tracking for tool approval prompts
    - Intelligent hysteresis hold timer to eliminate flickering during inter-token/thinking pauses.
    """
    CLAUDE_LOGS = os.path.expandvars(r"%LOCALAPPDATA%\Claude\logs")
    DEFAULT_HOLD_TIME_SEC = 4.5

    def __init__(self):
        # Persistent mappings to prevent counter resets between polling ticks
        self._proc_map: Dict[int, psutil.Process] = {}
        self._proc_types: Dict[int, str] = {}
        self._proc_io: Dict[int, int] = {}
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

    def _get_storage_mtime(self) -> float:
        """
        Returns the most recent modification time across Claude's storage log files
        including IndexedDB (chat history & streaming cache), Local Storage, and Session Storage.
        """
        if not self._storage_dir:
            self._storage_dir = self._resolve_storage_dir()
        if not self._storage_dir:
            return 0.0

        patterns = [
            os.path.join(self._storage_dir, "IndexedDB", "*", "*.log"),
            os.path.join(self._storage_dir, "Local Storage", "leveldb", "*.log"),
            os.path.join(self._storage_dir, "Session Storage", "*.log"),
        ]
        latest = 0.0
        for pat in patterns:
            try:
                for f in glob.iglob(pat):
                    try:
                        mtime = os.path.getmtime(f)
                        if mtime > latest:
                            latest = mtime
                    except OSError:
                        pass
            except Exception:
                pass
        return latest

    # Backwards compatibility alias
    _get_leveldb_mtime = _get_storage_mtime

    def is_running(self) -> bool:
        """
        Lightweight check if Claude Desktop processes are running.
        Maintains persistent psutil.Process handles to avoid resetting CPU & I/O baselines.
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
                            io = p.io_counters()
                            self._proc_io[pid] = io.read_bytes + io.write_bytes + io.other_bytes
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

    def sample_detailed_activity(self) -> Tuple[float, float, int]:
        """
        Calculates (total_cpu, renderer_cpu, io_delta) across all Claude processes.
        """
        if not self._proc_map:
            return 0.0, 0.0, 0

        total_cpu = 0.0
        renderer_cpu = 0.0
        io_delta = 0
        dead_pids = []

        for pid, p in self._proc_map.items():
            try:
                c = p.cpu_percent(None)
                total_cpu += c
                if self._proc_types.get(pid) == 'renderer':
                    renderer_cpu += c

                io = p.io_counters()
                total_io = io.read_bytes + io.write_bytes + io.other_bytes
                if pid in self._proc_io:
                    diff = total_io - self._proc_io[pid]
                    if diff > 0:
                        io_delta += diff
                self._proc_io[pid] = total_io
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                dead_pids.append(pid)

        for pid in dead_pids:
            self._proc_map.pop(pid, None)
            self._proc_types.pop(pid, None)
            self._proc_io.pop(pid, None)

        return total_cpu, renderer_cpu, io_delta

    def sample_detailed_cpu(self) -> Tuple[float, float]:
        """Calculates (total_cpu, renderer_cpu) across all Claude processes."""
        total_cpu, renderer_cpu, _ = self.sample_detailed_activity()
        return total_cpu, renderer_cpu

    def _sample_cpu(self) -> float:
        """Primes CPU and I/O counters and returns total CPU percentage."""
        total_cpu, _, _ = self.sample_detailed_activity()
        return total_cpu

    def _check_mcp_waiting(self) -> bool:
        """Checks if an MCP tool call was requested and is waiting for user approval."""
        candidate_paths = [
            os.path.join(self.CLAUDE_LOGS, "mcp.log")
        ]
        if self._storage_dir:
            candidate_paths.append(os.path.join(self._storage_dir, "logs", "mcp.log"))

        for mcp_log in candidate_paths:
            if not os.path.exists(mcp_log):
                continue
            try:
                mtime = os.path.getmtime(mcp_log)
                if time.time() - mtime > 60.0:
                    continue

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
        - WAITING_APPROVAL: Tool approval prompt waiting
        - WORKING: Claude is actively streaming tokens / generating
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

        # 2. Sample multi-modal activity (CPU, I/O delta, Storage)
        now = time.time()
        total_cpu, renderer_cpu, io_delta = self.sample_detailed_activity()
        storage_mtime = self._get_storage_mtime()
        storage_recent = (now - storage_mtime < 3.0) if storage_mtime > 0 else False

        # Active generation indicators:
        # 1. Substantial I/O transfer (SSE token stream or disk writes): io_delta > 1000 bytes
        # 2. Chromium renderer processing token DOM chunks with network/disk I/O: renderer_cpu > 0.4% and io_delta > 200 bytes
        # 3. Sustained renderer parsing & rendering: renderer_cpu > 1.2%
        # 4. Total app activity with active I/O: total_cpu > 2.0% and io_delta > 300 bytes
        # 5. Recent storage flush accompanied by renderer or I/O activity: storage_recent and (renderer_cpu > 0.2% or io_delta > 0)
        is_active_now = (
            io_delta > 1000 or
            (renderer_cpu > 0.4 and io_delta > 200) or
            renderer_cpu > 1.2 or
            (total_cpu > 2.0 and io_delta > 300) or
            (storage_recent and (renderer_cpu > 0.2 or io_delta > 0))
        )

        cfg = load_config()
        timings = cfg.get("timings", {})
        hold_time_sec = timings.get("claude_hold_time_sec", self.DEFAULT_HOLD_TIME_SEC)

        if is_active_now:
            self._last_active_time = now
            # If there is definite I/O or storage persistence, activate immediately
            if io_delta > 500 or storage_recent:
                self._consecutive_active_ticks = 2
            else:
                self._consecutive_active_ticks += 1
        else:
            self._consecutive_active_ticks = max(0, self._consecutive_active_ticks - 1)

        # To enter WORKING from IDLE: require 2 ticks (or 1 instant tick if definite I/O was detected above)
        if self._current_state != AgentState.WORKING:
            if self._consecutive_active_ticks >= 2:
                self._current_state = AgentState.WORKING
                return AgentState.WORKING
            return AgentState.IDLE

        # If already in WORKING: hold state through inter-token & thinking pauses until hold_time_sec elapses
        if self._last_active_time > 0 and (now - self._last_active_time < hold_time_sec):
            return AgentState.WORKING

        # Hold time elapsed with no activity -> transition back to IDLE
        self._current_state = AgentState.IDLE
        return AgentState.IDLE

if __name__ == "__main__":
    monitor = ClaudeMonitor()
    print("Claude running:", monitor.is_running())
    # Prime CPU counters
    monitor._sample_cpu()
    time.sleep(0.5)
    print("Claude state:", monitor.get_state().value)

