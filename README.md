# timeless-gmk-agent-macos

Show coding agent activity on your **Timeless82** or **Zuoya GMK87** keyboard screen from macOS. Hooks for **Pi**, **Claude Code**, **Codex**, and **Agy** (Antigravity CLI) play a distinct animation when an agent starts work and when it finishes.

Each animation plays for **2.5 seconds**, then the screen returns to its clock. Events queue in order, so a quick finish still gives both animations their full playback time. The hooks return immediately while a background worker updates the keyboard.

![Pi, Claude, Codex, and Agy working and finished cards](animations/preview.png)

Pi has a mint orbit, Claude has an orange sun, Codex has a blue terminal cursor, and Agy has a purple floating chevron. The eight GIFs in [animations](animations/) preview the working and finished loops.

## Supported keyboards

Any keyboard with USB ID `320f:5055`. That includes:

- Timeless82 (shows up as "Timeless82 Wired")
- Zuoya GMK87

To check your keyboard, run:

```sh
hidutil list | grep -i 320f
```

## Quick start

You need macOS, Python 3, and a keyboard connected by USB cable. Create the Python environment, preload the animations, and install the agent hooks:

```sh
git clone https://github.com/fajarnuha/timeless-gmk-agent-macos.git
cd timeless-gmk-agent-macos
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python agent_hook.py display pi start
.venv/bin/python install_hooks.py
```

Restart Pi, Claude Code, and Agy after installation. In Agy, check `/hooks` for `timeless82-keyboard`. In Codex, open `/hooks` and review and trust the Timeless82 hooks. Codex skips new hooks until trusted. Start a coding task to see the working animation, then the finished animation when the agent completes its turn.

The first command that displays an animation uploads all 36 frames. This takes about 90 seconds over USB. It replaces both custom image slots. Later events select a range of those frames without uploading again. Reconnecting the keyboard or changing its images with another tool can require another preload. Playback timing starts after the upload, once the animation is selected.

## Agent hooks

The installer preserves other settings and hooks, and backs up changed configuration files beside the originals. It writes:

| Agent | Location | Start | Finish |
| --- | --- | --- | --- |
| Pi | `~/.pi/agent/extensions/timeless82.ts` | `agent_start` | `agent_settled` |
| Claude Code | `~/.claude/settings.json` | `UserPromptSubmit` | `Stop` |
| Codex | `~/.codex/hooks.json` | `UserPromptSubmit` | `Stop` |
| Agy / Antigravity CLI | `~/.gemini/config/hooks.json` | `PreInvocation`, once per active turn | `Stop` with `fullyIdle: true` |

Pi uses `agent_settled` instead of `agent_end` so retries, queued prompts, and compaction finish before the completion animation. This extension targets the current Pi API, including Pi 1.4.0. Claude's `StopFailure` and Codex's `Interrupt` clear active notifications. Session shutdown also clears an active turn.

Agy uses a named `timeless82-keyboard` entry in its global hooks file, preserving other named hooks. Its payload uses `conversationId` to identify the session. Repeated `PreInvocation` events within the same turn do not replay the start animation. A `Stop` with background work still running waits for a later idle stop. Errors, cancellation, and execution limits return to the clock without a finished animation. The integration follows the hook format bundled with Agy 1.5.2.

To add Agy to an existing installation:

```sh
.venv/bin/python install_hooks.py --agents agy
.venv/bin/python agent_hook.py display agy start
```

This version repacks the animation memory into six working frames and three finished frames per agent. The first preview after updating reloads all 36 frames once; visible playback still lasts 2.5 seconds.

The scripts run locally, so a remote or cloud agent needs access to this Mac and keyboard to use them. An interruption returns the screen to its clock without showing a successful finish.

### Playback duration and agent selection

To use a different fixed duration or install only selected agents:

```sh
.venv/bin/python install_hooks.py --duration 3
.venv/bin/python install_hooks.py --agents pi
.venv/bin/python install_hooks.py --dry-run
```

### Preview animations

You can test each animation directly:

```sh
.venv/bin/python agent_hook.py display pi start --duration 2.5
.venv/bin/python agent_hook.py display pi finish --duration 2.5
.venv/bin/python agent_hook.py display claude start
.venv/bin/python agent_hook.py display codex finish
.venv/bin/python agent_hook.py display agy start
.venv/bin/python agent_hook.py display agy finish
```

### Custom integrations and status

Hooks only queue an update, then return. A detached worker handles USB writes and the playback timer. Events play in order, each for its full configured duration, even when a start and finish arrive together. Sessions have separate identities, and an old Codex turn cannot clear a newer turn.

The hook accepts JSON on stdin with `session_id` and an optional `turn_id`, or Agy's `conversationId`. Agy stop payloads also include `fullyIdle`, `terminationReason`, and an optional `error`. A session argument is available for other integrations:

```sh
.venv/bin/python agent_hook.py event pi start --session demo --duration 2.5
.venv/bin/python agent_hook.py event pi finish --session demo --duration 2.5
.venv/bin/python agent_hook.py status
.venv/bin/python agent_hook.py clock
```

State, upload metadata, and errors live in `.runtime/`, which Git ignores. No prompts or transcripts are stored. Set `TIMELESS82_STATE_DIR` consistently for all commands to move this directory. A disconnected keyboard never blocks an agent; errors go to `.runtime/hook.log`. After reconnecting, run `display` to preload again, or `worker` to retry queued events. If another tool replaced the images, use `display pi start --force` to rebuild all eight animations.

### Uninstall

Remove the hooks and return to the clock:

```sh
.venv/bin/python install_hooks.py --uninstall
.venv/bin/python agent_hook.py clock
```

The installer respects `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, and `PI_CODING_AGENT_DIR`. Use `--agy-config-dir /path/to/config` to override Agy's customization root. `--home /tmp/example-home` installs into a separate home directory for inspection. Keep this checkout and its `.venv` at the installed paths, or reinstall the hooks after moving them.

Hook references: [Pi extension lifecycle](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md), [Claude Code hooks](https://code.claude.com/docs/en/hooks), [Codex hooks and trust](https://learn.chatgpt.com/docs/hooks), and [Antigravity hooks](https://antigravity.google/docs/hooks).

## How it works

The installer connects each agent's lifecycle events to `agent_hook.py`. That script queues notifications for a background worker, which selects the agent's working or finished animation, waits for the configured duration, and restores the clock screen.

All eight animations fit into the keyboard's 36-frame image memory. `kbd_screen.py` uploads them once as RGB565 frames, then selects each animation by changing the frame range in the keyboard's configuration. It preserves unrelated settings and refreshes the clock during screen updates.

USB commands use the standard macOS HID system, with usage page `0xFF1C` and report ID `4`. A shared lock serializes keyboard access, including calls from the standalone time sync utility. You don't need drivers or `sudo`.

## Troubleshooting

- If an animation does not appear, check `.runtime/hook.log` and run `.venv/bin/python agent_hook.py status`. Try a direct preview to check USB access separately from the agent hook.
- If Pi, Claude Code, or Agy does not trigger animations, restart the agent after installing the hooks. In Agy, inspect `/hooks` for `timeless82-keyboard`. In Codex, check that the Timeless82 hooks are trusted in `/hooks`.
- If the keyboard vendor interface is not found, connect the USB cable. Bluetooth and the 2.4G dongle have not been tested.
- If another tool changed the keyboard images, run `.venv/bin/python agent_hook.py display pi start --force` to upload all eight animations again.
- To clear notifications and show the clock, run `.venv/bin/python agent_hook.py clock`.

## Ad hoc time sync

`kbd_time_sync.py` is a separate utility for copying your Mac's date and time to the keyboard. Run it when you need to correct the clock, such as after unplugging the keyboard. Agent notifications also refresh the clock, so this script is optional for the animation workflow.

```sh
.venv/bin/python kbd_time_sync.py
```

Example output:

```text
keyboard time: 2024-09-06 08:28:44 (weekday 5)
set to:        2026-11-05 16:19:36 (weekday 4)
```

To read the keyboard settings without changing them:

```sh
.venv/bin/python kbd_time_sync.py --dump
```

The printed keyboard time is the time that was last set, rather than the clock currently on the screen. The script reads the keyboard's 48-byte configuration block, updates the date and time fields at offsets 35 through 41, and writes the block back. If the screen still shows the old time, unplug the USB cable and reconnect it.

## Development

Regenerate the animation previews and run the software checks:

```sh
.venv/bin/python agent_animations.py
.venv/bin/python -m unittest discover -s tests -v
node tests/test_pi.mjs
```

The Pi smoke test needs Node.js with native TypeScript support. Python tests cover RGB565 encoding, frame ranges, USB packet construction, config preservation, overlapping events, stale turns, disconnect recovery, hook installation, and the fixed playback timer. They do not require a keyboard.

## Credits

The protocol was reverse-engineered by Jochen Eisinger ([zuoya_gmk87.py](https://gist.github.com/jeisinger/b198a72c5d7d203541c6269508c9ad8c)) and ported to Go in [rusq/kbdctl](https://github.com/rusq/kbdctl). This project adapts it to macOS. It is BSD-3-Clause licensed; see [LICENSE](LICENSE).
