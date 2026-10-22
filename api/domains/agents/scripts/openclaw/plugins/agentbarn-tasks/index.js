// Keep the Agent's Tasks current without relying on the prompt alone.
//
// Registers an `agentbarn_task` tool that runs the in-pod `agentbarn-task` command, so the
// command stays the one client of the Task routes. Each turn starts with the Agent's open
// Tasks. A run that does real work without touching a Task (three or more tool calls, or
// any file it writes), or that recorded one without attaching the files it wrote, is
// reminded in the tool result the model reads next (tool_result_persist) and asked to
// revise before finishing (OpenClaw refuses that revise once a run has side effects). If
// the run still ends without a Task, the plugin records one itself, named after the
// request, with origin `automatic`. It also does the bookkeeping that would otherwise cost
// the model a call each: when a run ends, the files it wrote go to the Task it worked on
// and a Task it left in progress is marked done.
import { spawn } from "node:child_process";
import fs from "node:fs";
import { resolve as resolvePath } from "node:path";

const TOOL = "agentbarn_task";
const STATUSES = ["open", "in_progress", "done", "failed"];
const WORK_THRESHOLD = 3;
// OpenClaw's file-writing tools. A run that produces a file is worth a Task however short it is.
const FILE_TOOLS = new Set(["write", "edit", "apply_patch"]);
const OPEN_TASKS_TTL_MS = 60_000;
const OPEN_TASKS_SHOWN = 10;
// Recently finished Tasks are listed too, so a follow-up reopens its Task rather than starting another.
const DONE_TASKS_SHOWN = 3;
const AUTOMATIC_TITLE_CHARS = 120;
const AUTOMATIC_DESCRIPTION_CHARS = 2000;
const COMMAND_TIMEOUT_MS = 150_000;
// A short message made only of these words is small talk ("Thanks!", "That's all for now"): it
// gets no request line. Approvals ("ok", "yes", "go ahead") are left out on purpose: they can start work.
const SMALL_TALK_MAX_WORDS = 8;
const SMALL_TALK_WORDS = new Set(
  ("hi hey hello thanks thank you thx ty cheers great nice cool awesome perfect lovely good sounds that thats " +
    "is was all for now bye goodbye see ya later much so very appreciate appreciated it got morning afternoon " +
    "evening night have a day weekend wow haha lol").split(" "),
);

const IN_TURN_REMINDER =
  "This request has taken several steps and has no Task yet. Before you finish, create one with the " +
  "agentbarn_task tool (a body says what was done). Your files are attached and the Task is marked done " +
  "when the run ends.";
// Next to every request but small talk, as on Hermes: in end-to-end runs OpenClaw's model did not
// use the tool within the turn from the instructions alone, and it cannot be held back once a run
// has side effects. About 40 tokens.
const REQUEST_LINE =
  "If this request needs tools or produces files, create a Task with agentbarn_task before you start, " +
  "or continue an open one. Don't mention Tasks in your reply unless the user asks.";
const QUIET = " Record it quietly and answer the user's message as normal; do not report the bookkeeping.";

const PARAMETERS = {
  type: "object",
  properties: {
    action: { type: "string", enum: ["create", "status", "note", "attach", "remove_file", "list", "show"] },
    task_id: { type: "string", description: "The Task's id, for status, note, attach and show." },
    title: { type: "string", description: "A short title, for create." },
    description: { type: "string", description: "What was asked, for create." },
    status: {
      type: "string",
      enum: STATUSES,
      description: "The new status, a list filter, or the starting status for create (in_progress).",
    },
    body: { type: "string", description: "The note, for note; or one to add with create or status." },
    path: { type: "string", description: "The file to attach, absolute or relative to your workspace." },
    name: { type: "string", description: "The file's name as shown on the Task, for attach." },
    content_type: { type: "string", description: "A bare type/subtype, for attach." },
    file_id: { type: "string", description: "The file's id from show, for remove_file." },
  },
  required: ["action"],
};

// runId -> what the run did: tool call ids, files written and attached, reminders sent
const runs = new Map();
// sessionKey -> its current runId; tool_result_persist is not told which run a result belongs to.
const currentRun = new Map();
// sessionKey -> the reminder its next turn starts with
const nextTurnReminders = new Map();
// sessionKey -> the user's latest request, the title of a Task recorded automatically
const requests = new Map();
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
    return [
      [
        "create", "--title", params.title,
        ...(params.description ? ["--description", params.description] : []),
        "--status", STATUSES.includes(params.status) ? params.status : "in_progress",
        ...(params.body ? ["--note", params.body] : []),
      ],
      "",
    ];
  }
  if (action === "list") return [params.status ? ["list", "--status", params.status] : ["list"], ""];
  if (!["status", "note", "attach", "remove_file", "show"].includes(action)) {
    return "action must be one of: create, status, note, attach, remove_file, list, show.";
  }
  if (!taskId) return `${action} needs a task_id.`;
  if (action === "show") return [["show", taskId], ""];
  if (action === "remove_file") {
    if (!params.file_id) return "remove_file needs a file_id, from the Task's files in show.";
    return [["remove-file", taskId, params.file_id], ""];
  }
  if (action === "status") {
    if (!STATUSES.includes(params.status)) return `status needs one of: ${STATUSES.join(", ")}.`;
    return [["status", taskId, params.status, ...(params.body ? ["--note", params.body] : [])], ""];
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
      "--replace",
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

// The Task a call of the Task tool acted on: its task_id, or the id a create returned.
function taskIdOf(toolName, params, result) {
  if (toolName !== TOOL) return null;
  if (typeof params?.task_id === "string" && params.task_id) return params.task_id;
  const created = result?.details;
  return params?.action === "create" && typeof created?.id === "string" ? created.id : null;
}

// The status a call of the Task tool left its Task in, if it set one.
function statusSet(toolName, params) {
  if (toolName !== TOOL) return null;
  if (params?.action === "create") return STATUSES.includes(params.status) ? params.status : "in_progress";
  if (params?.action === "status" && STATUSES.includes(params.status)) return params.status;
  return null;
}

function track(event, ctx) {
  const runId = event.runId ?? ctx.runId ?? "";
  if (ctx.sessionKey) currentRun.set(ctx.sessionKey, runId);
  let state = runs.get(runId);
  if (!state) {
    state = {
      work: new Set(), wroteFiles: false, written: new Map(), recorded: false, taskIds: new Set(),
      // taskId -> the last status the Agent set this run
      statuses: new Map(),
      attached: new Set(), reminded: false, revised: false, sessionKey: ctx.sessionKey ?? "",
    };
    runs.set(runId, state);
  }
  return state;
}

const unrecordedWork = (state) =>
  Boolean(state) && !state.recorded && (state.wroteFiles || state.work.size >= WORK_THRESHOLD);

const attachReminder = (names) =>
  `These files you produced are not on a Task yet: ${names.join(", ")}. Attach the ones that are part of ` +
  "the result with the agentbarn_task tool (action attach).";

// Attach the run's files to the one Task it touched. Returns the names it could not attach.
async function attachAutomatically(state) {
  const unattached = [...state.written].filter(([name]) => !state.attached.has(name)).sort();
  if (state.taskIds.size !== 1) return unattached.map(([name]) => name);
  const [taskId] = state.taskIds;
  const limit = Number(process.env.TASK_FILE_MAX_BYTES) || Infinity;
  const failed = [];
  for (const [name, path] of unattached) {
    let size;
    try {
      size = fs.statSync(path).size;
    } catch {
      continue;
    }
    if (size > limit) continue;
    const { ok } = await run(["attach", taskId, path, "--replace"]);
    if (!ok) failed.push(name);
  }
  return failed;
}

// Mark done each Task the Agent left in_progress this run; a status it chose itself stays.
async function closeInProgress(state) {
  const inProgress = [...state.statuses].filter(([, status]) => status === "in_progress").map(([id]) => id).sort();
  for (const taskId of inProgress) await run(["status", taskId, "done"]);
  if (inProgress.length) openTasksCache = { at: 0, lines: null };
}

// Record a Task for work the Agent left unrecorded. Returns the files it could not attach.
async function recordAutomatically(sessionKey, state) {
  const request = (requests.get(sessionKey) ?? "").split(/\s+/).filter(Boolean).join(" ");
  let title = request || "Work recorded automatically";
  if (title.length > AUTOMATIC_TITLE_CHARS) title = `${title.slice(0, AUTOMATIC_TITLE_CHARS - 1).trimEnd()}…`;
  const argv = ["create", "--title", title, "--status", "done", "--origin", "automatic"];
  if (request) argv.push("--description", request.slice(0, AUTOMATIC_DESCRIPTION_CHARS));
  const { ok, output } = await run(argv);
  openTasksCache = { at: 0, lines: null };
  let taskId;
  try {
    taskId = ok ? JSON.parse(output).id : undefined;
  } catch {
    taskId = undefined;
  }
  if (typeof taskId !== "string") {
    return [...state.written.keys()].filter((name) => !state.attached.has(name)).sort();
  }
  state.taskIds = new Set([taskId]);
  return attachAutomatically(state);
}

function smallTalk(message) {
  const words = typeof message === "string" ? message.toLowerCase().replaceAll("'", "").match(/[a-z]+/g) ?? [] : [];
  return words.length > 0 && words.length <= SMALL_TALK_MAX_WORDS && words.every((word) => SMALL_TALK_WORDS.has(word));
}

async function openTaskLines() {
  if (openTasksCache.lines && Date.now() - openTasksCache.at < OPEN_TASKS_TTL_MS) return openTasksCache.lines;
  const lines = [];
  for (const status of ["in_progress", "open", "done"]) {
    const { ok, output } = await run(["list", "--status", status]);
    if (!ok) return null;
    let items;
    try {
      items = JSON.parse(output).items;
    } catch {
      return null;
    }
    if (!Array.isArray(items)) return null;
    for (const task of items.slice(0, status === "done" ? DONE_TASKS_SHOWN : OPEN_TASKS_SHOWN)) {
      lines.push(`- ${task.id} [${task.status}] ${String(task.title ?? "").slice(0, 120)}`);
    }
  }
  openTasksCache = { at: Date.now(), lines };
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
        "Record work that uses tools or produces files as a Task the people you work for can follow. `create` " +
        "one before you start (it starts in_progress); when your run ends, the files you wrote are attached and " +
        "a Task still in_progress is marked done. Set `failed` (with a body saying why) or `open` (waiting on " +
        "the user) yourself.",
      parameters: PARAMETERS,
      execute: executeTool,
    });

    api.on("after_tool_call", (event, ctx) => {
      if (ctx.trigger === "heartbeat") return;
      const state = track(event, ctx);
      if (touchesTasks(event.toolName, event.params)) {
        state.recorded = true;
        for (const name of attachedNames(event.toolName, event.params)) state.attached.add(name);
        const taskId = taskIdOf(event.toolName, event.params, event.result);
        if (taskId) {
          state.taskIds.add(taskId);
          const status = statusSet(event.toolName, event.params);
          if (status) state.statuses.set(taskId, status);
        }
      } else {
        if (event.toolCallId) state.work.add(event.toolCallId);
        if (FILE_TOOLS.has(event.toolName)) {
          state.wroteFiles = true;
          const path = event.params?.path ?? event.params?.file_path;
          if (typeof path === "string" && path) {
            const full = resolvePath(workspace(), path);
            state.written.set(basename(full), full);
          }
        }
      }
    });

    // Synchronous: OpenClaw ignores a returned promise here.
    api.on("tool_result_persist", (event, ctx) => {
      if (event.isSynthetic) return;
      const state = runs.get(currentRun.get(ctx.sessionKey ?? "") ?? "");
      if (!unrecordedWork(state) || state.reminded) return;
      state.reminded = true;
      const message = event.message ?? {};
      const reminder = { type: "text", text: `[Agent Barn] ${IN_TURN_REMINDER}` };
      const content = Array.isArray(message.content)
        ? [...message.content, reminder]
        : [{ type: "text", text: String(message.content ?? "") }, reminder];
      return { message: { ...message, content } };
    });

    api.on("before_agent_finalize", (event, ctx) => {
      const state = runs.get(event.runId ?? ctx.runId ?? "");
      if (!unrecordedWork(state) || state.revised) return;
      state.revised = true;
      return {
        action: "revise",
        reason: "The run did work without recording a Task.",
        retry: { instruction: IN_TURN_REMINDER, idempotencyKey: `agentbarn-task:${event.runId}`, maxAttempts: 1 },
      };
    });

    // A run's files go to the one Task it touched without asking the model; the Agent can
    // remove any that are not part of the result. Only what could not be attached is named
    // on the next turn.
    api.on("agent_end", async (event, ctx) => {
      const runId = event.runId ?? ctx.runId ?? "";
      const state = runs.get(runId);
      runs.delete(runId);
      const sessionKey = ctx.sessionKey ?? state?.sessionKey ?? "";
      if (currentRun.get(sessionKey) === runId) currentRun.delete(sessionKey);
      if (!state || ctx.trigger === "heartbeat" || event.success === false) return;
      let failed;
      if (unrecordedWork(state)) {
        failed = await recordAutomatically(sessionKey, state);
      } else if (state.recorded) {
        failed = await attachAutomatically(state);
        await closeInProgress(state);
      } else {
        return;
      }
      if (failed.length) nextTurnReminders.set(sessionKey, attachReminder(failed) + QUIET);
    });

    api.on("before_prompt_build", async (event, ctx) => {
      if (ctx.trigger === "heartbeat") return;
      const parts = [];
      if (ctx.trigger === "user" || ctx.trigger === "cron") {
        if (typeof event.prompt === "string") requests.set(ctx.sessionKey ?? "", event.prompt);
        if (!smallTalk(event.prompt)) parts.push(REQUEST_LINE);
      }
      const lines = await openTaskLines();
      if (lines?.length) {
        parts.push(
          `Your open and latest finished Tasks:\n${lines.join("\n")}\nIf the request continues one of these, ` +
            "keep using it with the agentbarn_task tool (set a done one back to in_progress) rather than creating another.",
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
