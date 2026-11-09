#!/usr/bin/env python3
"""Install Timeless82 hooks for Pi, Claude Code, Codex, and Agy. Preserve existing settings."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import sys
import time

from agent_hook import AGENTS, DEFAULT_DURATION, duration_seconds

ROOT = Path(__file__).resolve().parent
HOOK = ROOT / "agent_hook.py"
AGY_HOOK_NAME = "timeless82-keyboard"


def owned(handler):
    command = handler.get("command", "")
    try:
        args = shlex.split(command)
    except ValueError:
        return False
    return len(args) >= 5 and args[1] == str(HOOK) and args[2] == "event"


def merge_hooks(config, agent, python, uninstall=False, duration=DEFAULT_DURATION):
    if agent == "agy":
        entry = config.get(AGY_HOOK_NAME, {})
        if not isinstance(entry, dict):
            raise ValueError(f"{AGY_HOOK_NAME} must be a hook object")
        for event, state in (("PreInvocation", "start"), ("Stop", "finish")):
            handlers = [handler for handler in entry.get(event, []) if not owned(handler)]
            if not uninstall:
                handlers.append({"type": "command", "command": shlex.join([
                    str(python), str(HOOK), "event", agent, state, "--duration", str(duration)]),
                    "timeout": 5})
            if handlers:
                entry[event] = handlers
            else:
                entry.pop(event, None)
        if any(key != "enabled" for key in entry):
            config[AGY_HOOK_NAME] = entry
        else:
            config.pop(AGY_HOOK_NAME, None)
        return config
    hooks = config.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("existing hooks must be an object")
    for event, groups in list(hooks.items()):
        remaining = []
        for group in groups:
            handlers = [handler for handler in group.get("hooks", []) if not owned(handler)]
            if handlers:
                remaining.append({**group, "hooks": handlers})
        if remaining:
            hooks[event] = remaining
        else:
            del hooks[event]
    if not uninstall:
        events = {"UserPromptSubmit": "start", "Stop": "finish", "SessionEnd": "cancel"}
        events["Interrupt" if agent == "codex" else "StopFailure"] = "cancel"
        for event, state in events.items():
            command = shlex.join([str(python), str(HOOK), "event", agent, state, "--duration", str(duration)])
            # The command only queues an event. Keep ingestion synchronous to preserve
            # event order; the USB upload runs in our detached, serialized worker.
            handler = {"type": "command", "command": command,
                       "timeout": 3 if event == "Interrupt" else 5}
            hooks.setdefault(event, []).append({"hooks": [handler]})
    if not hooks:
        config.pop("hooks", None)
    return config


def save(path, content, dry_run=False):
    if path.exists() and path.read_text() == content:
        print(f"Unchanged {path}")
        return
    print(f"{'Would update' if dry_run else 'Updating'} {path}")
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_name(path.name + f".timeless82-{time.time_ns()}.bak")
        shutil.copy2(path, backup)
    temp = path.with_name(path.name + ".timeless82.tmp")
    temp.touch(mode=0o600, exist_ok=True)
    temp.chmod(stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600)
    temp.write_text(content)
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agents", nargs="+", choices=AGENTS, default=list(AGENTS))
    parser.add_argument("--home", type=Path, help="alternate home, useful for a sandbox preview")
    parser.add_argument("--python", type=Path, default=ROOT / ".venv/bin/python")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--duration", type=duration_seconds, default=DEFAULT_DURATION)
    parser.add_argument("--agy-config-dir", type=Path, help="Agy customization root, defaults to ~/.gemini/config")
    args = parser.parse_args()
    python = args.python.absolute()
    if not args.uninstall and not python.is_file():
        parser.error(f"Python does not exist: {python}. Create .venv first.")
    home = args.home or Path.home()
    targets = {
        "pi": (home / ".pi/agent" if args.home else
               Path(os.environ.get("PI_CODING_AGENT_DIR", home / ".pi/agent"))) / "extensions/timeless82.ts",
        "claude": (home / ".claude" if args.home else
                   Path(os.environ.get("CLAUDE_CONFIG_DIR", home / ".claude"))) / "settings.json",
        "codex": (home / ".codex" if args.home else
                  Path(os.environ.get("CODEX_HOME", home / ".codex"))) / "hooks.json",
        "agy": (args.agy_config_dir or home / ".gemini/config") / "hooks.json",
    }
    # Validate and prepare every edit before changing any configuration.
    edits = []
    for agent in args.agents:
        path = targets[agent]
        if agent == "pi":
            if args.uninstall:
                if path.exists() and str(HOOK) in path.read_text():
                    edits.append((path, None))
                continue
            template = (ROOT / "hooks/pi.ts").read_text()
            content = template.replace('"__TIMELESS82_PYTHON__"', json.dumps(str(python)))
            content = content.replace('"__TIMELESS82_HOOK__"', json.dumps(str(HOOK)))
            content = content.replace('"__TIMELESS82_DURATION__"', json.dumps(str(args.duration)))
        else:
            if args.uninstall and not path.exists():
                continue
            config = json.loads(path.read_text()) if path.exists() else {}
            if not isinstance(config, dict):
                raise ValueError(f"{path} must contain a JSON object")
            content = json.dumps(merge_hooks(config, agent, python, args.uninstall, args.duration), indent=2) + "\n"
        edits.append((path, content))
    for path, content in edits:
        if content is None:
            print(f"{'Would remove' if args.dry_run else 'Removing'} {path}")
            if not args.dry_run:
                path.unlink()
        else:
            save(path, content, args.dry_run)
    if not args.uninstall:
        print("Restart installed agents. In Agy, check /hooks. In Codex, open /hooks and trust the Timeless82 hooks.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError) as error:
        print(f"Cannot install hooks: {error}", file=sys.stderr)
        sys.exit(1)
