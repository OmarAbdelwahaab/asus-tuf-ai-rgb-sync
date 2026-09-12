import os
import glob
import json
import time
from enum import Enum
from typing import Optional, Tuple
import psutil

class AgentState(Enum):
    OFF = "OFF"                          # Application not running
    IDLE = "IDLE"                        # Application open, no active task / normal
    WORKING = "WORKING"                  # Agent thinking, executing tools, streaming
    WAITING_APPROVAL = "WAITING_APPROVAL" # Agent waiting for approval / user input

class AntigravityMonitor:
    """
    Monitors Antigravity process and conversation transcripts in real-time
    to determine the current agent execution state.
    """
    BASE_APP_DATA = os.path.expandvars(r"%USERPROFILE%\.gemini\antigravity")

    def __init__(self):
        self._cached_transcript_path: Optional[str] = None
        self._cached_transcript_mtime: float = 0
        self._last_process_check_time: float = 0
        self._is_process_running: bool = False
        self._last_file_position: int = 0

    def is_running(self) -> bool:
        """Lightweight check if Antigravity or Antigravity IDE processes are running."""
        now = time.time()
        # Cache process check for 1 second to minimize system calls
        if now - self._last_process_check_time < 1.0:
            return self._is_process_running

        self._last_process_check_time = now
        found = False
        try:
            for p in psutil.process_iter(['name']):
                pname = (p.info['name'] or '').lower()
                if pname in ('antigravity.exe', 'antigravity ide.exe'):
                    found = True
                    break
        except Exception:
            pass

        self._is_process_running = found
        return found

    def _find_active_transcript(self) -> Optional[str]:
        """Finds the most recently active conversation transcript."""
        pattern = os.path.join(self.BASE_APP_DATA, "brain", "*", ".system_generated", "logs", "transcript.jsonl")
        files = glob.glob(pattern)
        if not files:
            return None

        # Sort by modification time
        files.sort(key=os.path.getmtime, reverse=True)
        return files[0]

    def get_state(self) -> AgentState:
        """
        Determines the current state of Antigravity:
        - OFF: Not running
        - WORKING: Thinking, executing tool calls, active turn
        - WAITING_APPROVAL: Awaiting plan approval, ask_question response, or confirmation
        - IDLE: Open but idle
        """
        if not self.is_running():
            return AgentState.OFF

        transcript_path = self._find_active_transcript()
        if not transcript_path or not os.path.exists(transcript_path):
            return AgentState.IDLE

        try:
            mtime = os.path.getmtime(transcript_path)
            now = time.time()
            time_since_modified = now - mtime

            # If transcript hasn't been modified in > 5 minutes, agent is idle
            if time_since_modified > 300.0:
                return AgentState.IDLE

            # Read the last few lines to assess state
            with open(transcript_path, 'r', encoding='utf-8', errors='ignore') as f:
                # Seek to near the end for ultra-fast reading without reading large logs
                file_size = os.path.getsize(transcript_path)
                seek_bytes = min(file_size, 16384)
                f.seek(file_size - seek_bytes)
                lines = f.readlines()

            if not lines:
                return AgentState.IDLE

            # Parse last valid lines
            parsed_entries = []
            for l in reversed(lines):
                line_str = l.strip()
                if not line_str:
                    continue
                try:
                    data = json.loads(line_str)
                    parsed_entries.append(data)
                    if len(parsed_entries) >= 6:
                        break
                except Exception:
                    continue

            if not parsed_entries:
                return AgentState.IDLE

            last_entry = parsed_entries[0]
            last_type = last_entry.get("type")
            last_source = last_entry.get("source")
            tool_calls = last_entry.get("tool_calls") or []

            # 1. Check for explicit WAITING_APPROVAL conditions
            # Check if any recent entry is a tool call requiring approval (ask_question, RequestFeedback: true)
            for entry in parsed_entries:
                if entry.get("source") == "USER_EXPLICIT":
                    # Reached user input boundary, stop looking back
                    break
                calls = entry.get("tool_calls") or []
                for tc in calls:
                    fn = tc.get("function", {})
                    fn_name = fn.get("name") or tc.get("name", "")
                    fn_args = fn.get("arguments") or tc.get("arguments", "")
                    if fn_name == "ask_question":
                        # If ask_question was called and no subsequent USER_INPUT answered it
                        return AgentState.WAITING_APPROVAL
                    if "RequestFeedback" in str(fn_args) and '"RequestFeedback": true' in str(fn_args).lower():
                        return AgentState.WAITING_APPROVAL

            # 2. Check for WORKING conditions
            # - User just sent input, model is thinking
            if last_type == "USER_INPUT" and last_source == "USER_EXPLICIT":
                # If within 30 seconds of user input, model is actively processing
                if time_since_modified < 60.0:
                    return AgentState.WORKING

            # - Planner response with tool calls (tool execution in progress)
            if last_type == "PLANNER_RESPONSE" and len(tool_calls) > 0:
                # Tool was dispatched, awaiting result
                if time_since_modified < 90.0:
                    return AgentState.WORKING

            # - Tool result received (GENERIC or tool response), agent is now thinking the next step
            if last_type == "GENERIC" or last_source == "SYSTEM":
                if time_since_modified < 45.0:
                    return AgentState.WORKING

            # - Recent activity check: if file modified in last 3 seconds
            if time_since_modified < 3.0:
                return AgentState.WORKING

            # 3. Otherwise, if turn ended normally and no pending approvals
            return AgentState.IDLE

        except Exception as e:
            return AgentState.IDLE

if __name__ == "__main__":
    monitor = AntigravityMonitor()
    print("Antigravity Running:", monitor.is_running())
    print("Current State:", monitor.get_state().value)
