import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

// install_hooks.py fills these absolute paths so this works in any project.
const python = "__TIMELESS82_PYTHON__";
const hook = "__TIMELESS82_HOOK__";
const duration = "__TIMELESS82_DURATION__";

export default function timeless82(pi: ExtensionAPI) {
  let active = false;
  const notify = async (event: "start" | "finish" | "cancel", session: string) => {
    try {
      await pi.exec(python, [hook, "event", "pi", event, "--session", session, "--duration", duration], { timeout: 1500 });
    } catch {
      // A screen notification must not interrupt the coding agent.
    }
  };
  pi.on("agent_start", async (_event, ctx) => {
    active = true;
    await notify("start", ctx.sessionManager.getSessionId());
  });
  // agent_end can be followed by retries, compaction, or queued prompts.
  pi.on("agent_settled", async (event, ctx) => {
    if (!active) return;
    active = false;
    await notify(event.aborted ? "cancel" : "finish", ctx.sessionManager.getSessionId());
  });
  pi.on("session_shutdown", async (_event, ctx) => {
    if (!active) return;
    active = false;
    await notify("cancel", ctx.sessionManager.getSessionId());
  });
}
