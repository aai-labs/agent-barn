// Keep the Agent's Tasks current without relying on the prompt alone.
//
// Registers an `agentbarn_task` tool that runs the in-pod `agentbarn-task` command, so the
// command stays the one client of the Task routes. Each turn starts with the Agent's open
// Tasks. A run that does real work without touching a Task (three or more tool calls, or
// any file it writes), or that recorded one without attaching the files it wrote, is
// reminded in the tool result the model reads next (tool_result_persist) and asked to
// revise before finishing; OpenClaw refuses that revise once a run has side effects, so
// the next turn of the session carries the reminder too. The plugin never records a Task
// itself.
import { spawn } from "node:child_process";

const TOOL = "agentbarn_task";
const STATUSES = ["open", "in_progress", "done", "failed"];
const WORK_THRESHOLD = 3;
// OpenClaw's file-writing tools. A run that produces a file is worth a Task however short it is.
const FILE_TOOLS = new Set(["write", "edit", "apply_patch"]);
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

// runId -> what the run did: tool call ids, files written and attached, reminders sent
const runs = new Map();
// sessionKey -> its current runId; tool_result_persist is not told which run a result belongs to.
const currentRun = new Map();
// sessionKey -> the reminder its next turn starts with
const nextTurnReminders = new Map();
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

const basename = (path) => path.split("/").filter(Boolean).pop() ?? "";

// File names a call attached to a Task, through the tool or the command.
function attachedNames(toolName, params) {
  if (toolName === TOOL) {
    return params?.action === "attach" && typeof params.path === "string" ? [basename(params.path)] : [];
  }
  const command = params?.command;
  return typeof command === "string" && command.includes("agentbarn-task attach")
    ? command.split(/\s+/).filter(Boolean).map(basename)
    : [];
}

function track(event, ctx) {
  const runId = event.runId ?? ctx.runId ?? "";
  if (ctx.sessionKey) currentRun.set(ctx.sessionKey, runId);
  let state = runs.get(runId);
  if (!state) {
    state = {
      work: new Set(), wroteFiles: false, written: new Set(), recorded: false, attached: new Set(),
      reminded: new Set(), sessionKey: ctx.sessionKey ?? "",
    };
    runs.set(runId, state);
  }
  return state;
}

// What the run still owes its Task: a record of real work, or the files it produced.
function missing(state) {
  if (!state) return null;
  if (!state.recorded) {
    return state.wroteFiles || state.work.size >= WORK_THRESHOLD ? { kind: "record", names: [] } : null;
  }
  const names = [...state.written].filter((name) => !state.attached.has(name)).sort();
  return names.length ? { kind: "attach", names } : null;
}

const attachReminder = (names) =>
  `You recorded a Task but have not attached the files you produced: ${names.join(", ")}. Attach each ` +
  "with the agentbarn_task tool (action attach) so the Task shows the result.";

const inTurnReminder = (gap) => (gap.kind === "record" ? IN_TURN_REMINDER : attachReminder(gap.names));
const nextTurnReminder = (gap) => (gap.kind === "record" ? NEXT_TURN_REMINDER : attachReminder(gap.names));

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
      if (touchesTasks(event.toolName, event.params)) {
        state.recorded = true;
        for (const name of attachedNames(event.toolName, event.params)) state.attached.add(name);
      } else {
        if (event.toolCallId) state.work.add(event.toolCallId);
        if (FILE_TOOLS.has(event.toolName)) {
          state.wroteFiles = true;
          const path = event.params?.path ?? event.params?.file_path;
          if (typeof path === "string" && path) state.written.add(basename(path));
        }
      }
    });

    // Synchronous: OpenClaw ignores a returned promise here.
    api.on("tool_result_persist", (event, ctx) => {
      if (event.isSynthetic) return;
      const state = runs.get(currentRun.get(ctx.sessionKey ?? "") ?? "");
      const gap = missing(state);
      if (!gap || state.reminded.has(gap.kind)) return;
      state.reminded.add(gap.kind);
      const message = event.message ?? {};
      const reminder = { type: "text", text: `[Agent Barn] ${inTurnReminder(gap)}` };
      const content = Array.isArray(message.content)
        ? [...message.content, reminder]
        : [{ type: "text", text: String(message.content ?? "") }, reminder];
      return { message: { ...message, content } };
    });

    api.on("before_agent_finalize", (event, ctx) => {
      const state = runs.get(event.runId ?? ctx.runId ?? "");
      const gap = missing(state);
      if (!gap || state.reminded.has(`finalize:${gap.kind}`)) return;
      state.reminded.add(`finalize:${gap.kind}`);
      return {
        action: "revise",
        reason: "The run has work its Task does not show yet.",
        retry: {
          instruction: inTurnReminder(gap),
          idempotencyKey: `agentbarn-task:${event.runId}:${gap.kind}`,
          maxAttempts: 1,
        },
      };
    });

    api.on("agent_end", (event, ctx) => {
      const runId = event.runId ?? ctx.runId ?? "";
      const state = runs.get(runId);
      runs.delete(runId);
      const sessionKey = ctx.sessionKey ?? state?.sessionKey ?? "";
      if (currentRun.get(sessionKey) === runId) currentRun.delete(sessionKey);
      const gap = missing(state);
      if (ctx.trigger === "heartbeat" || event.success === false || !gap) return;
      nextTurnReminders.set(sessionKey, nextTurnReminder(gap));
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
      const reminder = nextTurnReminders.get(ctx.sessionKey ?? "");
      if (reminder) {
        nextTurnReminders.delete(ctx.sessionKey ?? "");
        parts.push(reminder);
      }
      return parts.length ? { appendContext: parts.join("\n\n") } : undefined;
    });
  },
};
