// Keep the Agent's Tasks current without relying on the prompt alone.
//
// Registers an `agentbarn_task` tool that runs the in-pod `agentbarn-task` command, so the
// command stays the one client of the Task routes. Each turn starts with the Agent's open
// Tasks. A run that does real work without touching a Task is asked to revise once before
// it finishes, and reminded on the next turn if it still ended without one. The plugin
// never records a Task itself.
import { spawn } from "node:child_process";

const TOOL = "agentbarn_task";
const STATUSES = ["open", "in_progress", "done", "failed"];
const WORK_THRESHOLD = 3;
const OPEN_TASKS_TTL_MS = 60_000;
const OPEN_TASKS_SHOWN = 10;
const COMMAND_TIMEOUT_MS = 150_000;

const IN_TURN_REMINDER =
  "This request has taken several steps and has no Task yet. Before you finish, record it with the " +
  "agentbarn_task tool: create a Task, add a note on what was done, attach the files you produced and " +
  "set its status.";
const NEXT_TURN_REMINDER =
  "Your previous turn did work without recording it as a Task. If it was more than a quick answer, " +
  "record it now with the agentbarn_task tool: create the Task, add a note on what was done, attach any " +
  "files and set its status.";

const PARAMETERS = {
  type: "object",
  properties: {
    action: { type: "string", enum: ["create", "status", "note", "attach", "list", "show"] },
    task_id: { type: "string", description: "The Task's id, for status, note, attach and show." },
    title: { type: "string", description: "A short title, for create." },
    description: { type: "string", description: "What was asked, for create." },
    status: { type: "string", enum: STATUSES, description: "The new status, or a list filter." },
    body: { type: "string", description: "The note, for note." },
    path: { type: "string", description: "The file to attach, absolute or relative to your workspace." },
    name: { type: "string", description: "The file's name as shown on the Task, for attach." },
    content_type: { type: "string", description: "A bare type/subtype, for attach." },
  },
  required: ["action"],
};

// runId -> { work: Set of tool call ids, recorded, reminded, sessionKey }
const runs = new Map();
const remindNextTurn = new Set();
let openTasksCache = { at: 0, lines: null };

const command = () => process.env.AGENTBARN_TASK_COMMAND || "/usr/local/bin/agentbarn-task";
const workspace = () => `${process.env.HOME}/.openclaw/workspace`;

const UNAVAILABLE = "Agent Barn Tasks are unavailable right now, so the change was not confirmed.";

function run(argv, stdin = "") {
  return new Promise((resolve) => {
    let stdout = "";
    let stderr = "";
    let child;
    try {
      child = spawn(command(), argv, { cwd: workspace() });
    } catch {
      resolve({ ok: false, output: UNAVAILABLE });
      return;
    }
    // Our own timer rather than spawn's, which is left running when the command never starts.
    const timer = setTimeout(() => child.kill(), COMMAND_TIMEOUT_MS);
    const settle = (result) => {
      clearTimeout(timer);
      resolve(result);
    };
    child.stdout.on("data", (chunk) => (stdout += chunk));
    child.stderr.on("data", (chunk) => (stderr += chunk));
    child.on("error", () => settle({ ok: false, output: UNAVAILABLE }));
    child.on("close", (code) =>
      settle(
        code === 0
          ? { ok: true, output: stdout.trim() }
          : { ok: false, output: stderr.trim() || "The Task command failed, so the change was not confirmed." },
      ),
    );
    child.stdin.on("error", () => {});
    child.stdin.end(stdin);
  });
}

// The command line for one tool call, or what is missing from it.
function argvFor(params) {
  const { action, task_id: taskId } = params;
  if (action === "create") {
    if (!params.title) return "create needs a title.";
    return [["create", "--title", params.title, ...(params.description ? ["--description", params.description] : [])], ""];
  }
  if (action === "list") return [params.status ? ["list", "--status", params.status] : ["list"], ""];
  if (!["status", "note", "attach", "show"].includes(action)) {
    return "action must be one of: create, status, note, attach, list, show.";
  }
  if (!taskId) return `${action} needs a task_id.`;
  if (action === "show") return [["show", taskId], ""];
  if (action === "status") {
    if (!STATUSES.includes(params.status)) return `status needs one of: ${STATUSES.join(", ")}.`;
    return [["status", taskId, params.status], ""];
  }
  if (action === "note") {
    if (!params.body) return "note needs a body.";
    return [["note", taskId], params.body];
  }
  if (!params.path) return "attach needs a path.";
  return [
    [
      "attach", taskId, params.path,
      ...(params.name ? ["--name", params.name] : []),
      ...(params.content_type ? ["--content-type", params.content_type] : []),
    ],
    "",
  ];
}

const textResult = (value) => ({ content: [{ type: "text", text: JSON.stringify(value) }], details: value });

async function executeTool(_toolCallId, params) {
  const built = argvFor(params && typeof params === "object" ? params : {});
  if (typeof built === "string") return textResult({ error: built });
  const [argv, stdin] = built;
  const { ok, output } = await run(argv, stdin);
  if (!["list", "show"].includes(argv[0])) openTasksCache = { at: 0, lines: null };
  if (!ok) return textResult({ error: output });
  try {
    return textResult(JSON.parse(output));
  } catch {
    return textResult({ result: output });
  }
}

const touchesTasks = (toolName, params) =>
  toolName === TOOL || (typeof params?.command === "string" && params.command.includes("agentbarn-task"));

function track(event, ctx) {
  const runId = event.runId ?? ctx.runId ?? "";
  let state = runs.get(runId);
  if (!state) {
    state = { work: new Set(), recorded: false, reminded: false, sessionKey: ctx.sessionKey ?? "" };
    runs.set(runId, state);
  }
  return state;
}

const nonTrivial = (state) => state && !state.recorded && state.work.size >= WORK_THRESHOLD;

async function openTaskLines() {
  if (openTasksCache.lines && Date.now() - openTasksCache.at < OPEN_TASKS_TTL_MS) return openTasksCache.lines;
  const lines = [];
  for (const status of ["in_progress", "open"]) {
    const { ok, output } = await run(["list", "--status", status]);
    if (!ok) return null;
    let items;
    try {
      items = JSON.parse(output).items;
    } catch {
      return null;
    }
    if (!Array.isArray(items)) return null;
    for (const task of items) lines.push(`- ${task.id} [${task.status}] ${String(task.title ?? "").slice(0, 120)}`);
  }
  openTasksCache = { at: Date.now(), lines: lines.slice(0, OPEN_TASKS_SHOWN) };
  return openTasksCache.lines;
}

export default {
  id: "agentbarn-tasks",
  name: "Agent Barn Tasks",
  description: "Give the Agent a Task tool, show its open Tasks each turn, and remind it to record its work",
  register(api) {
    const { AGENT_ID, INGEST_URL, INGEST_API_KEY } = process.env;
    if (!AGENT_ID || !INGEST_URL || !INGEST_API_KEY) return;

    api.registerTool({
      name: TOOL,
      label: "Agent Barn Task",
      description:
        "Record your own work as Tasks the people you work for can follow. Create a Task for any request that " +
        "takes more than a quick answer, keep its status current, add notes as you go and attach the files you " +
        "produce. Check `list` before creating, to continue a Task that already covers the request.",
      parameters: PARAMETERS,
      execute: executeTool,
    });

    api.on("after_tool_call", (event, ctx) => {
      if (ctx.trigger === "heartbeat") return;
      const state = track(event, ctx);
      if (touchesTasks(event.toolName, event.params)) state.recorded = true;
      else if (event.toolCallId) state.work.add(event.toolCallId);
    });

    api.on("before_agent_finalize", (event, ctx) => {
      const state = runs.get(event.runId ?? ctx.runId ?? "");
      if (!nonTrivial(state) || state.reminded) return;
      state.reminded = true;
      return {
        action: "revise",
        reason: "The run did work without recording a Task.",
        retry: { instruction: IN_TURN_REMINDER, idempotencyKey: `agentbarn-task:${event.runId}`, maxAttempts: 1 },
      };
    });

    api.on("agent_end", (event, ctx) => {
      const runId = event.runId ?? ctx.runId ?? "";
      const state = runs.get(runId);
      runs.delete(runId);
      if (ctx.trigger === "heartbeat" || event.success === false || !nonTrivial(state)) return;
      remindNextTurn.add(ctx.sessionKey ?? state.sessionKey);
    });

    api.on("before_prompt_build", async (_event, ctx) => {
      if (ctx.trigger === "heartbeat") return;
      const parts = [];
      const lines = await openTaskLines();
      if (lines?.length) {
        parts.push(
          `Your open Tasks:\n${lines.join("\n")}\nKeep their status current with the agentbarn_task tool, ` +
            "and mark a Task done or failed when its work ends.",
        );
      }
      if (remindNextTurn.delete(ctx.sessionKey ?? "")) parts.push(NEXT_TURN_REMINDER);
      return parts.length ? { appendContext: parts.join("\n\n") } : undefined;
    });
  },
};
