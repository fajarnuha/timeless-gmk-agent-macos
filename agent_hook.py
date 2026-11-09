#!/usr/bin/env python3
"""Queue agent lifecycle events and update the Timeless82 without delaying coding."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

# Keep hook ingestion independent of hidapi and Pillow, including on disconnected Macs.
ROOT = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get("TIMELESS82_STATE_DIR", ROOT / ".runtime"))
AGENTS = ("pi", "claude", "codex", "agy")
SESSION_TTL = 6 * 60 * 60
DEFAULT_DURATION = 3.0


@contextmanager
def state_lock():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with (STATE_DIR / "state.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def read_state():
    try:
        state = json.loads((STATE_DIR / "events.json").read_text())
    except FileNotFoundError:
        state = {"sessions": {}, "revision": 0, "desired": None, "applied": 0, "pending": []}
    # Upgrade state from the initial single-event implementation.
    if "pending" not in state:
        state["pending"] = ([{"revision": state["revision"], "desired": state["desired"]}]
                            if state["revision"] > state["applied"] else [])
    return state


def write_state(state):
    temp = STATE_DIR / "events.tmp"
    temp.write_text(json.dumps(state, indent=2) + "\n")
    temp.replace(STATE_DIR / "events.json")


def duration_seconds(value):
    duration = float(value)
    if not 0.1 <= duration <= 60:
        raise argparse.ArgumentTypeError("duration must be between 0.1 and 60 seconds")
    return duration


def record_event(agent, event, session, turn=None, duration=DEFAULT_DURATION):
    """Queue each notification for its full duration and ignore stale stops."""
    now = time.time()
    key = f"{agent}:{session}"
    with state_lock():
        state = read_state()
        sessions = {key: value for key, value in state["sessions"].items()
                    if now - value["started"] < SESSION_TTL}
        previous = sessions.get(key)
        if event == "start":
            # Agy invokes PreInvocation before every model call in a turn.
            if agent == "agy" and previous:
                return False
            sessions[key] = {"agent": agent, "started": now, "turn": turn}
        elif previous and (not turn or not previous.get("turn") or previous["turn"] == turn):
            del sessions[key]
        else:
            # Late Stop/SessionEnd events must not clear a newer turn or another agent.
            return False
        desired = {"agent": agent, "event": event, "duration": duration} if event != "cancel" else None
        state["sessions"] = sessions
        state["revision"] += 1
        state["desired"] = desired
        state["pending"].append({"revision": state["revision"], "desired": desired})
        write_state(state)
    return True


def agy_event(event, payload):
    """Translate Antigravity's camelCase Stop payload into a notification."""
    if event != "finish":
        return event
    reason = payload.get("terminationReason", "").upper()
    if (payload.get("error") or reason.startswith("MAX_") or reason in {
            "ERROR", "USER_CANCELED", "USER_CANCELLED", "CANCELED", "CANCELLED",
            "TERMINAL_CUSTOM_HOOK"}):
        return "cancel"
    # Stop can fire while background work is still running.
    return "finish" if payload.get("fullyIdle") is True else None


def spawn_worker():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log = STATE_DIR / "hook.log"
    if log.exists() and log.stat().st_size > 1_000_000:
        # Only diagnostics go here. No prompts or agent transcripts are recorded.
        log.write_text("")
    with log.open("a") as output:
        subprocess.Popen([sys.executable, str(ROOT / "agent_hook.py"), "worker"],
                         stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                         start_new_session=True, close_fds=True)


def worker():
    from kbd_screen import show_agent, show_clock

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with (STATE_DIR / "worker.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        while True:
            with state_lock():
                state = read_state()
                if not state["pending"]:
                    # Release while holding state.lock so an arriving event cannot
                    # spawn its only worker between our last check and unlock.
                    fcntl.flock(lock, fcntl.LOCK_UN)
                    return
                notification = state["pending"][0]
                revision, desired = notification["revision"], notification["desired"]
            try:
                if desired:
                    show_agent(desired["agent"], desired["event"])
                    time.sleep(desired.get("duration", DEFAULT_DURATION))
                show_clock()
            except Exception as error:
                print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} Timeless82: {error}", flush=True)
                with state_lock():
                    state = read_state()
                    state["error"] = str(error)
                    write_state(state)
                    fcntl.flock(lock, fcntl.LOCK_UN)
                    return
            with state_lock():
                state = read_state()
                state["applied"] = revision
                state["pending"] = [entry for entry in state["pending"] if entry["revision"] != revision]
                state.pop("error", None)
                write_state(state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    event_parser = sub.add_parser("event", help="receive a hook, queue a background update")
    event_parser.add_argument("agent", choices=AGENTS)
    event_parser.add_argument("event", choices=("start", "finish", "cancel"))
    event_parser.add_argument("--session", help="otherwise read session_id or Agy conversationId from JSON on stdin")
    event_parser.add_argument("--turn")
    event_parser.add_argument("--duration", type=duration_seconds, default=DEFAULT_DURATION)
    display = sub.add_parser("display", help="show an animation now, with errors on stderr")
    display.add_argument("agent", choices=AGENTS)
    display.add_argument("event", choices=("start", "finish"))
    display.add_argument("--force", action="store_true", help="upload even if already cached")
    display.add_argument("--duration", type=duration_seconds, default=DEFAULT_DURATION)
    sub.add_parser("worker", help=argparse.SUPPRESS)
    sub.add_parser("clock", help="clear active sessions and return to the clock")
    sub.add_parser("status", help="show queued state and the last device error")
    args = parser.parse_args()
    if args.command == "event":
        # Notification hooks always succeed and emit valid JSON for Codex Stop.
        # Keyboard failures remain in hook.log, never in the agent's context.
        try:
            payload = {} if args.session else json.load(sys.stdin)
            session = args.session or payload.get("conversationId" if args.agent == "agy" else "session_id")
            if not session:
                raise ValueError("hook payload is missing a session identity")
            event = agy_event(args.event, payload) if args.agent == "agy" and not args.session else args.event
            if event and record_event(args.agent, event, session, args.turn or payload.get("turn_id"), args.duration):
                spawn_worker()
        except Exception as error:
            print(f"Timeless82 hook: {error}", file=sys.stderr)
        print("{}")
        return 0
    if args.command == "worker":
        worker()
    elif args.command == "status":
        with state_lock():
            print(json.dumps(read_state(), indent=2))
    elif args.command == "clock":
        with state_lock():
            state = read_state()
            state.update(sessions={}, desired=None, revision=state["revision"] + 1)
            state["pending"] = [{"revision": state["revision"], "desired": None}]
            write_state(state)
        worker()
        with state_lock():
            if read_state().get("error"):
                raise OSError(read_state()["error"])
    elif args.command == "display":
        from kbd_screen import show_agent
        started = time.monotonic()
        show_agent(args.agent, args.event, force=args.force,
                   progress=lambda pos, total: print(f"\rUploading {pos / total:.0%}", end="", flush=True))
        selected = time.monotonic()
        time.sleep(args.duration)
        from kbd_screen import show_clock
        show_clock()
        print(f"\n{args.agent} {args.event}: played for {args.duration:g}s, "
              f"{selected - started:.1f}s preparation, returned to clock")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, TimeoutError) as error:
        print(f"Timeless82: {error}", file=sys.stderr)
        sys.exit(1)
