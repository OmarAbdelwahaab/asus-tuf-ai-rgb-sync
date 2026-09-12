import threading
import time
from typing import Optional, Callable
from antigravity_monitor import AntigravityMonitor, AgentState
from claude_monitor import ClaudeMonitor
from tuf_lighting import AsusTufKeyboard
from config import load_config

class StateCoordinator:
    """
    Coordinates state between Antigravity and Claude Desktop,
    resolving priority and updating the ASUS TUF RGB backlight.
    """
    def __init__(self, on_state_change: Optional[Callable[[AgentState, AgentState, AgentState], None]] = None):
        self.antigravity_monitor = AntigravityMonitor()
        self.claude_monitor = ClaudeMonitor()
        self.keyboard = AsusTufKeyboard()

        self.antigravity_state: AgentState = AgentState.OFF
        self.claude_state: AgentState = AgentState.OFF
        self.resolved_state: AgentState = AgentState.OFF

        self.on_state_change = on_state_change
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def resolve_state(self, ag_state: AgentState, cl_state: AgentState) -> AgentState:
        """
        State priority:
        1. Both OFF -> OFF (Dormant mode, restore default)
        2. WAITING_APPROVAL takes highest priority (Amber Gold)
        3. WORKING takes second priority (Crimson Red Breathing)
        4. IDLE -> Default Profile
        """
        if ag_state == AgentState.OFF and cl_state == AgentState.OFF:
            return AgentState.OFF

        if ag_state == AgentState.WAITING_APPROVAL or cl_state == AgentState.WAITING_APPROVAL:
            return AgentState.WAITING_APPROVAL

        if ag_state == AgentState.WORKING or cl_state == AgentState.WORKING:
            return AgentState.WORKING

        return AgentState.IDLE

    def apply_lighting(self, state: AgentState):
        """Applies appropriate lighting according to resolved state."""
        if state == AgentState.WORKING:
            self.keyboard.set_working()
        elif state == AgentState.WAITING_APPROVAL:
            self.keyboard.set_waiting_approval()
        else: # IDLE or OFF
            self.keyboard.set_default()

    def update_cycle(self) -> float:
        """Executes one polling cycle and returns recommended sleep duration."""
        ag_state = self.antigravity_monitor.get_state()
        cl_state = self.claude_monitor.get_state()
        resolved = self.resolve_state(ag_state, cl_state)

        changed = (
            ag_state != self.antigravity_state or
            cl_state != self.claude_state or
            resolved != self.resolved_state
        )

        self.antigravity_state = ag_state
        self.claude_state = cl_state
        self.resolved_state = resolved

        if changed:
            self.apply_lighting(resolved)
            if self.on_state_change:
                try:
                    self.on_state_change(ag_state, cl_state, resolved)
                except Exception:
                    pass

        # Adjust sleep interval dynamically
        cfg = load_config()
        timings = cfg.get("timings", {})
        if resolved == AgentState.OFF:
            # Both programs closed: sleep longer to conserve resources
            return timings.get("dormant_poll_interval_sec", 2.5)
        else:
            # Active tracking: rapid poll for immediate response
            return timings.get("active_poll_interval_sec", 0.35)

    def _run_loop(self):
        # Prime monitors
        self.claude_monitor._sample_cpu()
        while self._running:
            try:
                sleep_sec = self.update_cycle()
                time.sleep(sleep_sec)
            except Exception as e:
                time.sleep(1.0)

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="CoordinatorThread")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        self.keyboard.restore_default_on_exit()

if __name__ == "__main__":
    def on_change(ag, cl, resolved):
        print(f"[State Update] Antigravity: {ag.value} | Claude: {cl.value} => Applied: {resolved.value}")

    coord = StateCoordinator(on_state_change=on_change)
    print("Starting Coordinator for 5 seconds test...")
    coord.start()
    time.sleep(5)
    coord.stop()
    print("Coordinator test finished.")
