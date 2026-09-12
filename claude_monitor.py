import os
import glob
import time
from enum import Enum
from typing import List, Optional
import psutil
from antigravity_monitor import AgentState

class ClaudeMonitor:
    """
    Monitors Claude Desktop client for active generation/streaming in Standard Chat.
    Uses process CPU measurement across ticks, LevelDB updates, and MCP log signals.
    """
    CLAUDE_LOGS = os.path.expandvars(r"%LOCALAPPDATA%\Claude\logs")
    CLAUDE_STORAGE = os.path.expandvars(
        r"%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude"
    )

    def __init__(self):
        self._claude_procs: List[psutil.Process] = []
        self._last_proc_refresh: float = 0
        self._consecutive_active_ticks: int = 0
        self._last_active_time: float = 0
        self._is_running: bool = False

    def is_running(self) -> bool:
        now = time.time()
        if now - self._last_proc_refresh < 1.0:
            return self._is_running

        self._last_proc_refresh = now
        procs = []
        try:
            for p in psutil.process_iter(['name', 'pid']):
                if (p.info['name'] or '').lower() == 'claude.exe':
                    procs.append(p)
        except Exception:
            pass

        self._claude_procs = procs
        self._is_running = len(procs) > 0
        return self._is_running

    def _sample_cpu(self) -> float:
        """Calculates combined CPU percentage across all Claude processes."""
        if not self._claude_procs:
            return 0.0

        total_cpu = 0.0
        alive_procs = []
        for p in self._claude_procs:
            try:
                # cpu_percent(None) is non-blocking and compares with last call
                cpu = p.cpu_percent(None)
                total_cpu += cpu
                alive_procs.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        self._claude_procs = alive_procs
        return total_cpu

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
            return AgentState.OFF

        # 1. Check MCP waiting approval if user uses tools
        if self._check_mcp_waiting():
            return AgentState.WAITING_APPROVAL

        # 2. Check process CPU delta
        cpu = self._sample_cpu()
        now = time.time()

        # When Claude streams responses, Chromium renderer thread CPU rises > 1.2%
        if cpu > 1.2:
            self._consecutive_active_ticks += 1
            self._last_active_time = now
        else:
            self._consecutive_active_ticks = max(0, self._consecutive_active_ticks - 1)

        # Consider working if currently active or active within last 1.2 seconds (smoothing)
        if self._consecutive_active_ticks >= 1 or (now - self._last_active_time < 1.2 and self._last_active_time > 0):
            return AgentState.WORKING

        return AgentState.IDLE

if __name__ == "__main__":
    monitor = ClaudeMonitor()
    print("Claude running:", monitor.is_running())
    # Prime CPU counters
    monitor._sample_cpu()
    time.sleep(0.5)
    print("Claude state:", monitor.get_state().value)
