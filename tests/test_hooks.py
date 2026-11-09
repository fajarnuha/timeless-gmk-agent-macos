import copy
from contextlib import redirect_stdout
import io
import json
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import agent_hook
from install_hooks import AGY_HOOK_NAME, HOOK, ROOT, merge_hooks, save


class EventTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch = patch.object(agent_hook, "STATE_DIR", Path(self.temp.name))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_each_finish_displays_its_agent_without_clearing_other_sessions(self):
        agent_hook.record_event("pi", "start", "one")
        agent_hook.record_event("codex", "start", "two")
        agent_hook.record_event("pi", "finish", "one")
        self.assertEqual(agent_hook.read_state()["desired"]["agent"], "pi")
        self.assertIn("codex:two", agent_hook.read_state()["sessions"])
        agent_hook.record_event("codex", "finish", "two")
        self.assertEqual(agent_hook.read_state()["desired"]["event"], "finish")

    def test_latest_stop_cannot_clear_newer_turn(self):
        agent_hook.record_event("codex", "start", "session", "old")
        agent_hook.record_event("codex", "start", "session", "new")
        self.assertFalse(agent_hook.record_event("codex", "finish", "session", "old"))
        self.assertEqual(len(agent_hook.read_state()["sessions"]), 1)

    def test_cancellation_returns_to_clock_without_replaying_old_start(self):
        agent_hook.record_event("pi", "start", "one")
        agent_hook.record_event("claude", "start", "two")
        agent_hook.record_event("claude", "cancel", "two")
        self.assertIsNone(agent_hook.read_state()["desired"])
        self.assertIn("pi:one", agent_hook.read_state()["sessions"])
        agent_hook.record_event("pi", "cancel", "one")
        self.assertIsNone(agent_hook.read_state()["desired"])

    def test_worker_drains_event_arriving_during_upload(self):
        agent_hook.record_event("pi", "start", "one", duration=0.1)
        def during_upload(agent, event):
            if event == "start":
                agent_hook.record_event("pi", "finish", "one", duration=0.1)
        with patch("kbd_screen.show_agent", side_effect=during_upload) as show, patch("kbd_screen.show_clock") as clock:
            agent_hook.worker()
        self.assertEqual(clock.call_count, 2)
        self.assertEqual(show.call_args_list[0].args, ("pi", "start"))
        self.assertEqual(show.call_args_list[1].args, ("pi", "finish"))
        state = agent_hook.read_state()
        self.assertEqual(state["revision"], state["applied"])

    def test_disconnect_is_retryable_without_losing_event(self):
        agent_hook.record_event("pi", "start", "one", duration=0.1)
        with patch("kbd_screen.show_agent", side_effect=OSError("disconnected")):
            agent_hook.worker()
        self.assertEqual(agent_hook.read_state()["error"], "disconnected")
        with patch("kbd_screen.show_agent") as show, patch("kbd_screen.show_clock"):
            agent_hook.worker()
        show.assert_called_once_with("pi", "start")
        self.assertNotIn("error", agent_hook.read_state())

    def test_worker_waits_fixed_duration_before_restoring_clock(self):
        agent_hook.record_event("claude", "start", "one", duration=2.5)
        timeline = []
        now = [100.0]
        def sleep(seconds):
            now[0] += seconds
        with patch("agent_hook.time.monotonic", side_effect=lambda: now[0]), \
             patch("agent_hook.time.sleep", side_effect=sleep), \
             patch("kbd_screen.show_agent", side_effect=lambda *args: timeline.append(("animation", now[0]))), \
             patch("kbd_screen.show_clock", side_effect=lambda: timeline.append(("clock", now[0]))):
            agent_hook.worker()
        self.assertEqual(timeline, [("animation", 100.0), ("clock", 102.5)])

    def test_rapid_start_and_finish_both_play_for_full_duration(self):
        agent_hook.record_event("pi", "start", "one", duration=2.5)
        agent_hook.record_event("pi", "finish", "one", duration=3)
        with patch("agent_hook.time.sleep") as sleep, patch("kbd_screen.show_agent") as show, \
             patch("kbd_screen.show_clock") as clock:
            agent_hook.worker()
        self.assertEqual([call.args for call in show.call_args_list], [("pi", "start"), ("pi", "finish")])
        self.assertEqual([call.args for call in sleep.call_args_list], [(2.5,), (3,)])
        self.assertEqual(clock.call_count, 2)
        self.assertEqual(agent_hook.read_state()["pending"], [])

    def agy_hook(self, event, payload):
        output = io.StringIO()
        with patch("sys.argv", ["agent_hook.py", "event", "agy", event]), \
             patch("sys.stdin", io.StringIO(json.dumps(payload))), \
             patch("agent_hook.spawn_worker") as spawn, redirect_stdout(output):
            self.assertEqual(agent_hook.main(), 0)
        self.assertEqual(json.loads(output.getvalue()), {})
        return spawn.call_count

    def test_agy_camel_case_payload_deduplicates_invocations_and_waits_for_idle(self):
        payload = {"conversationId": "conversation", "invocationNum": 0}
        self.assertEqual(self.agy_hook("start", payload), 1)
        self.assertEqual(self.agy_hook("start", {**payload, "invocationNum": 1}), 0)
        self.assertEqual(self.agy_hook("finish", {**payload, "fullyIdle": False}), 0)
        self.assertIn("agy:conversation", agent_hook.read_state()["sessions"])
        self.assertEqual(self.agy_hook("finish", {**payload, "fullyIdle": True,
                                                "terminationReason": "NO_TOOL_CALL"}), 1)
        state = agent_hook.read_state()
        self.assertEqual([entry["desired"]["event"] for entry in state["pending"]], ["start", "finish"])
        self.assertNotIn("agy:conversation", state["sessions"])
        self.assertEqual(self.agy_hook("start", payload), 1)

    def test_agy_failed_and_cancelled_stops_do_not_show_done(self):
        for reason in ("USER_CANCELED", "ERROR", "MAX_INVOCATIONS", "TERMINAL_CUSTOM_HOOK"):
            payload = {"conversationId": reason}
            self.agy_hook("start", payload)
            self.agy_hook("finish", {**payload, "terminationReason": reason, "fullyIdle": True})
            self.assertIsNone(agent_hook.read_state()["desired"])
            self.assertNotIn(f"agy:{reason}", agent_hook.read_state()["sessions"])

    def test_agy_stop_error_cancels_even_without_idle_flag(self):
        payload = {"conversationId": "error-conversation"}
        self.agy_hook("start", payload)
        self.agy_hook("finish", {**payload, "error": "provider failure"})
        self.assertIsNone(agent_hook.read_state()["desired"])


class InstallTests(unittest.TestCase):
    def test_agy_installer_targets_global_hooks_and_uninstalls_only_our_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home / ".gemini/config/hooks.json"
            path.parent.mkdir(parents=True)
            original = {"existing": {"Stop": [{"command": "echo keep"}]}}
            path.write_text(json.dumps(original))
            command = [sys.executable, str(ROOT / "install_hooks.py"), "--home", str(home),
                       "--agents", "agy", "--duration", "3"]
            subprocess.run(command, check=True, capture_output=True, text=True)
            installed = path.read_text()
            self.assertIn(AGY_HOOK_NAME, json.loads(installed))
            self.assertFalse((home / ".codex/hooks.json").exists())
            subprocess.run(command, check=True, capture_output=True, text=True)
            self.assertEqual(path.read_text(), installed)
            subprocess.run(command + ["--uninstall"], check=True, capture_output=True, text=True)
            self.assertEqual(json.loads(path.read_text()), original)

    def test_agy_named_hooks_are_flat_idempotent_and_preserve_foreign_hooks(self):
        original = {"existing-hook": {"enabled": True, "Stop": [{"command": "echo existing"}]}}
        python = Path("/tmp/path with spaces/python")
        config = merge_hooks(copy.deepcopy(original), "agy", python, duration=3)
        self.assertNotIn("hooks", config)
        self.assertEqual(config["existing-hook"], original["existing-hook"])
        for event, state in (("PreInvocation", "start"), ("Stop", "finish")):
            handler = config[AGY_HOOK_NAME][event][0]
            self.assertNotIn("hooks", handler)
            import shlex
            self.assertEqual(shlex.split(handler["command"]), [str(python), str(HOOK), "event", "agy", state,
                                                             "--duration", "3"])
        installed = copy.deepcopy(config)
        self.assertEqual(merge_hooks(config, "agy", python, duration=3), installed)
        self.assertEqual(merge_hooks(config, "agy", python, uninstall=True), original)

    def test_installer_preserves_private_file_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text("{}\n")
            path.chmod(0o600)
            save(path, '{"hooks": {}}\n')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_install_is_idempotent_and_uninstall_preserves_other_settings(self):
        original = {"permissions": {"allow": ["Bash(ls)"]}, "hooks": {
            "Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "echo existing"}]}]}}
        config = merge_hooks(copy.deepcopy(original), "claude", Path("/tmp/path with spaces/python"))
        first = copy.deepcopy(config)
        self.assertEqual(merge_hooks(config, "claude", Path("/tmp/path with spaces/python")), first)
        self.assertEqual(merge_hooks(config, "claude", Path("/tmp/python"), uninstall=True), original)


if __name__ == "__main__":
    unittest.main()
