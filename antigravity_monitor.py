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
            last_call_names = [
                tc.get("function", {}).get("name") or tc.get("name", "")
                for tc in tool_calls
            ]

            # 1. Interactive Question Modal (ask_question)
            # When ask_question is open, the agent is halted waiting for the modal response.
            # Thus, ask_question is strictly in the last_entry. Once answered, a GENERIC entry is appended.
            if last_type == "PLANNER_RESPONSE" and "ask_question" in last_call_names:
                return AgentState.WAITING_APPROVAL

            # 2. Plan Review Approval (RequestFeedback: true)
            # If the turn ended with an artifact awaiting user plan approval
            if last_type == "PLANNER_RESPONSE" and len(tool_calls) == 0:
                has_pending_plan_review = False
                for entry in parsed_entries[1:]:
                    if entry.get("source") == "USER_EXPLICIT":
                        break
                    calls = entry.get("tool_calls") or []
                    for tc in calls:
                        args = str(tc.get("function", {}).get("arguments") or tc.get("arguments", ""))
                        if "RequestFeedback" in args and '"requestfeedback": true' in args.lower():
                            has_pending_plan_review = True
                            break
                    if has_pending_plan_review:
                        break
                if has_pending_plan_review and time_since_modified < 600.0:
                    return AgentState.WAITING_APPROVAL
                # Otherwise, turn ended normally and no approval is pending -> IDLE
                return AgentState.IDLE

            # 3. Working States:
            # - User just sent a prompt, agent is generating
            if last_type == "USER_INPUT" and time_since_modified < 60.0:
                return AgentState.WORKING

            # - Tool call is actively executing
            if last_type == "PLANNER_RESPONSE" and len(tool_calls) > 0 and time_since_modified < 90.0:
                return AgentState.WORKING

            # - Tool result received, agent thinking next step
            if (last_type == "GENERIC" or last_source == "SYSTEM") and time_since_modified < 45.0:
                return AgentState.WORKING

            # - Recent disk activity (last 2 seconds)
            if time_since_modified < 2.0:
                return AgentState.WORKING

            # 4. Default to IDLE
            return AgentState.IDLE

        except Exception as e:
            return AgentState.IDLE

if __name__ == "__main__":
    monitor = AntigravityMonitor()
    print("Antigravity Running:", monitor.is_running())
    print("Current State:", monitor.get_state().value)
