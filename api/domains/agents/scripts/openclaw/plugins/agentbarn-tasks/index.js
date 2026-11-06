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
// and a Task it left in progress is marked done, or reopened if the run failed. Only a Task
// call that changed something counts as recording the work: reading the Tasks does not.
// The startup checklist (BOOT.md) and subagent runs are left alone: they are not the
// user's request.
import { spawn } from "node:child_process";
import fs from "node:fs";
import { resolve as resolvePath } from "node:path";

const TOOL = "agentbarn_task";
const STATUSES = ["open", "in_progress", "done", "failed"];
const WORK_THRESHOLD = 3;
// OpenClaw's file-writing tools. A run that produces a file is worth a Task however short it is.
const FILE_TOOLS = new Set(["write", "edit", "apply_patch"]);
const OPEN_TASKS_TTL_MS = 60_000;
// The Task list is read before every turn, so it gets one short call; a slow or failed
// read leaves the list out until the cache expires rather than holding up each turn.
const LIST_TIMEOUT_MS = 10_000;
const LIST_PAGE_SIZE = 100;
const OPEN_TASKS_SHOWN = 10;
// Recently finished Tasks are listed too, so a follow-up reopens its Task rather than starting another.
const DONE_TASKS_SHOWN = 3;
const AUTOMATIC_TITLE_CHARS = 120;
const AUTOMATIC_DESCRIPTION_CHARS = 2000;
const COMMAND_TIMEOUT_MS = 150_000;
// Sessions remembered at once (requests, reminders, runs); the oldest are forgotten first.
const SESSIONS_KEPT = 500;
// Task tool actions and command subcommands that change a Task; reading one is not recording work.
const WRITE_ACTIONS = new Set(["create", "status", "note", "attach", "remove_file"]);
const COMMAND_WRITE = /agentbarn-task\s+(?:create|status|note|attach|remove-file)\b/;
const REDACTED = "[redacted]";
// Credentials a user may paste into a request. The automatic Task's title and description
// come from the request, and people across the Organization can read them.
const SECRET_PATTERNS = [
  [/-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)/g, REDACTED],
  [/(:\/\/[^/\s:@]+:)[^/\s@]+@/g, `$1${REDACTED}@`],
  [/(\bbearer\s+)\S+/gi, `$1${REDACTED}`],
  [
    /(\b(?:password|passwd|pwd|passphrase|secret|token|api[_-]?key|access[_-]?key|client[_-]?secret)\b\s*(?:[:=]|\bis\b)\s*)\S+/gi,
    `$1${REDACTED}`,
  ],
  [/\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}/g, REDACTED],
  [/\b(?:gh[pousr]_|github_pat_|glpat-|xox[abposr]-)[A-Za-z0-9_-]{10,}/g, REDACTED],
  [/\bAKIA[0-9A-Z]{16}\b/g, REDACTED],
  [/\bAIza[0-9A-Za-z_-]{35}\b/g, REDACTED],
  [/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g, REDACTED],
];
const OPAQUE_WORD = /\b[A-Za-z0-9_-]{32,}\b/g;
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
// The Task lines shown each turn, and when they were read (null: read again)
let taskListCache = { at: null, lines: [] };
// sessionKey -> its current runId; tool_result_persist is not told which run a result belongs to.
const currentRun = new Map();
// sessionKey -> the reminder its next turn starts with
const nextTurnReminders = new Map();
// sessionKey -> the user's latest request, the title of a Task recorded automatically
const requests = new Map();

// Store a value as the newest entry, forgetting the oldest past SESSIONS_KEPT.
function remember(map, key, value) {
  map.delete(key);
  map.set(key, value);
  while (map.size > SESSIONS_KEPT) map.delete(map.keys().next().value);
}

const forgetTaskList = () => {
  taskListCache = { at: null, lines: [] };
};

// A long word that reads like a key: mixed case with digits, or a long hex string (not a UUID).
const opaque = (word) =>
  (/[a-z]/.test(word) && /[A-Z]/.test(word) && /\d/.test(word)) || /^[0-9a-fA-F]{32,}$/.test(word) ? REDACTED : word;

function redacted(text) {
  const masked = SECRET_PATTERNS.reduce((current, [pattern, replacement]) => current.replace(pattern, replacement), text);
  return masked.replace(OPAQUE_WORD, opaque);
}

// The startup checklist runs in the session `agent:<id>:boot`; subagents in `...subagent:...` sessions.
const sideRun = (sessionKey) =>
  typeof sessionKey === "string" &&
  (sessionKey.endsWith(":boot") || sessionKey.startsWith("subagent:") || sessionKey.includes(":subagent:"));

const command = () => process.env.AGENTBARN_TASK_COMMAND || "/usr/local/bin/agentbarn-task";
const workspace = () => `${process.env.HOME}/.openclaw/workspace`;

const UNAVAILABLE = "Agent Barn Tasks are unavailable right now, so the change was not confirmed.";

function run(argv, stdin = "", timeoutMs = COMMAND_TIMEOUT_MS) {
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
    const timer = setTimeout(() => child.kill(), timeoutMs);
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

// The command line for one tool call, or what is missing from it. Option values are joined
// to their option (`--title=-v`) so a value starting with a dash is not read as another option.
function argvFor(params) {
  const { action, task_id: taskId } = params;
  if (action === "create") {
    if (!params.title) return "create needs a title.";
    return [
      [
        "create", `--title=${params.title}`,
        ...(params.description ? [`--description=${params.description}`] : []),
        `--status=${STATUSES.includes(params.status) ? params.status : "in_progress"}`,
        ...(params.body ? [`--note=${params.body}`] : []),
      ],
      "",
    ];
  }
  if (action === "list") return [params.status ? ["list", `--status=${params.status}`] : ["list"], ""];
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
    return [["status", taskId, params.status, ...(params.body ? [`--note=${params.body}`] : [])], ""];
  }
  if (action === "note") {
    if (!params.body) return "note needs a body.";
    return [["note", taskId], params.body];
  }
  if (!params.path) return "attach needs a path.";
  return [
    [
      "attach", taskId, params.path,
      ...(params.name ? [`--name=${params.name}`] : []),
      ...(params.content_type ? [`--content-type=${params.content_type}`] : []),
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
  if (!["list", "show"].includes(argv[0])) forgetTaskList();
  if (!ok) return textResult({ error: output });
  try {
    return textResult(JSON.parse(output));
  } catch {
    return textResult({ result: output });
  }
}

const touchesTasks = (toolName, params) =>
  toolName === TOOL || (typeof params?.command === "string" && params.command.includes("agentbarn-task"));

// Whether a Task call changed a Task: a write that did not fail. Reading Tasks is not recording work.
function recordsTask(toolName, params, result) {
  if (toolName !== TOOL) return typeof params?.command === "string" && COMMAND_WRITE.test(params.command);
  if (!WRITE_ACTIONS.has(params?.action)) return false;
  return !(result?.details && typeof result.details === "object" && "error" in result.details);
}

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
  if (ctx.sessionKey) remember(currentRun, ctx.sessionKey, runId);
  let state = runs.get(runId);
  if (!state) {
    state = {
      work: new Set(), wroteFiles: false, written: new Map(), recorded: false, taskIds: new Set(),
      // taskId -> the last status the Agent set this run
      statuses: new Map(),
      attached: new Set(), reminded: false, revised: false, sessionKey: ctx.sessionKey ?? "",
    };
    remember(runs, runId, state);
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
  const limit = Number(process.env.ARTIFACT_MAX_BYTES) || Infinity;
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

// Move each Task the Agent left in_progress this run to `status`; a status it chose itself stays.
async function settleInProgress(state, status) {
  const inProgress = [...state.statuses].filter(([, current]) => current === "in_progress").map(([id]) => id).sort();
  for (const taskId of inProgress) await run(["status", taskId, status]);
  if (inProgress.length) forgetTaskList();
}

// Record a Task for work the Agent left unrecorded. Returns the files it could not attach.
async function recordAutomatically(sessionKey, state) {
  const request = redacted(requests.get(sessionKey) ?? "").split(/\s+/).filter(Boolean).join(" ");
  let title = request || "Work recorded automatically";
  if (title.length > AUTOMATIC_TITLE_CHARS) title = `${title.slice(0, AUTOMATIC_TITLE_CHARS - 1).trimEnd()}…`;
  const argv = ["create", `--title=${title}`, "--status=done", "--origin=automatic"];
  if (request) argv.push(`--description=${request.slice(0, AUTOMATIC_DESCRIPTION_CHARS)}`);
  const { ok, output } = await run(argv);
  forgetTaskList();
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

// The open Tasks, then the latest finished ones, from one listing (most recently changed first).
function taskLines(output) {
  let items;
  try {
    items = JSON.parse(output).items;
  } catch {
    return [];
  }
  if (!Array.isArray(items)) return [];
  const lines = [];
  for (const status of ["in_progress", "open", "done"]) {
    const shown = items.filter((task) => task?.status === status);
    for (const task of shown.slice(0, status === "done" ? DONE_TASKS_SHOWN : OPEN_TASKS_SHOWN)) {
      lines.push(`- ${task.id} [${status}] ${String(task.title ?? "").slice(0, 120)}`);
    }
  }
  return lines;
}

async function openTaskLines() {
  if (taskListCache.at !== null && Date.now() - taskListCache.at < OPEN_TASKS_TTL_MS) return taskListCache.lines;
  const { ok, output } = await run(["list", `--page-size=${LIST_PAGE_SIZE}`], "", LIST_TIMEOUT_MS);
  taskListCache = { at: Date.now(), lines: ok ? taskLines(output) : [] };
  return taskListCache.lines;
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
      if (ctx.trigger === "heartbeat" || sideRun(ctx.sessionKey)) return;
      const state = track(event, ctx);
      if (touchesTasks(event.toolName, event.params)) {
        if (!recordsTask(event.toolName, event.params, event.result)) return;
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
      if (event.isSynthetic || sideRun(ctx.sessionKey)) return;
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
      if (sideRun(ctx.sessionKey)) return;
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
      if (!state || ctx.trigger === "heartbeat" || sideRun(sessionKey)) return;
      const succeeded = event.success !== false;
      let failed;
      if (succeeded && unrecordedWork(state)) {
        failed = await recordAutomatically(sessionKey, state);
      } else if (state.recorded) {
        // A run that failed leaves its Task open to pick up again, not in progress.
        failed = await attachAutomatically(state);
        await settleInProgress(state, succeeded ? "done" : "open");
      } else {
        return;
      }
      if (failed.length) remember(nextTurnReminders, sessionKey, attachReminder(failed) + QUIET);
    });

    api.on("before_prompt_build", async (event, ctx) => {
      if (ctx.trigger === "heartbeat" || sideRun(ctx.sessionKey)) return;
      const parts = [];
      if (ctx.trigger === "user" || ctx.trigger === "cron") {
        if (typeof event.prompt === "string") {
          remember(requests, ctx.sessionKey ?? "", event.prompt.slice(0, AUTOMATIC_DESCRIPTION_CHARS));
        }
        if (!smallTalk(event.prompt)) parts.push(REQUEST_LINE);
      }
      const lines = await openTaskLines();
      if (lines.length) {
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
