import sys
import time
import signal
from coordinator import StateCoordinator
from antigravity_monitor import AgentState

def main():
    use_tray = "--no-tray" not in sys.argv

    def on_state_change(ag_state: AgentState, cl_state: AgentState, res_state: AgentState):
        tip = f"ASUS AI Sync: {res_state.value}\nAntigravity: {ag_state.value}\nClaude: {cl_state.value}"
        if use_tray and tray_app_instance:
            tray_app_instance.update_tooltip(tip)
        print(f"[{time.strftime('%H:%M:%S')}] Antigravity: {ag_state.value} | Claude: {cl_state.value} => Backlight: {res_state.value}", flush=True)

    coordinator = StateCoordinator(on_state_change=on_state_change)
    tray_app_instance = None

    def cleanup(*args):
        print("\nShutting down ASUS TUF AI RGB Sync...", flush=True)
        coordinator.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    coordinator.start()
    print("ASUS Gaming Laptop AI RGB Sync Daemon started.", flush=True)
    print("Priority: Waiting for Approval > Working > Idle", flush=True)
    print("Working: Breathing Pure 255 Red | Waiting: Solid Pure 255 Yellow | Idle: Default Profile", flush=True)

    if use_tray:
        try:
            from tray_app import TrayApp
            tray_app_instance = TrayApp(coordinator, on_exit=cleanup)
            tray_app_instance.run()
        except Exception as e:
            print(f"Tray error ({e}), falling back to headless console mode...")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                cleanup()
    else:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            cleanup()

if __name__ == "__main__":
    main()
