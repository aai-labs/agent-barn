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
// and a Task it left in progress is marked done, or reopened if the run failed; one it kept
// (`keep`, for work that continues in a later turn) stays in progress. Before a Task is
// marked done the run is reported to Agent Barn, where a decision model can hold it back:
// in progress when the job is still going, open when it waits on the user. Only a
// Task call that changed something counts as recording the work: reading the Tasks does not.
// The startup checklist (BOOT.md) and subagent runs are left alone: they are not the
// user's request.
import { spawn } from "node:child_process";
import fs from "node:fs";
import { join as joinPath, resolve as resolvePath } from "node:path";

const TOOL = "agentbarn_task";
const MAIN_AGENT = "main";
const SECRET_ROOT = process.env.BOT_SECRET_ROOT || "/run/agentbarn/bots";
const AGENT_NAME = /^[A-Za-z0-9-]+$/;
const IDENTITY_NAMES = ["AGENT_ID", "INGEST_URL", "INGEST_API_KEY", "ARTIFACT_URL", "ARTIFACT_API_KEY", "ARTIFACT_MAX_BYTES"];
const STATUSES = ["open", "in_progress", "done", "failed"];
// A Task the Agent left in_progress with keep: work that continues in a later turn. Only a run
// that failed moves it (to open); otherwise it stays in_progress.
const KEPT = "kept";
const WORK_THRESHOLD = 3;
// OpenClaw's scheduler tool, under its current and its earlier name.
const SCHEDULER_TOOLS = new Set(["automations", "cron"]);
const INTENT_TIMEOUT_MS = 45_000;
const RUN_NOTE_CHARS = 300;
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
const LATEST_NOTE_CHARS = 200;
const AUTOMATIC_TITLE_CHARS = 120;
const AUTOMATIC_DESCRIPTION_CHARS = 2000;
const COMMAND_TIMEOUT_MS = 150_000;
// Asking whether a Task about to be closed is finished: how long it may take, and how much it is told.
const TURN_END_TIMEOUT_MS = 45_000;
const TURN_TOOLS_SENT = 40;
const TOOL_SUMMARY_CHARS = 300;
const TURN_TEXT_CHARS = 4000;
// Sessions remembered at once (requests, reminders, runs); the oldest are forgotten first.
const SESSIONS_KEPT = 500;
// Task tool actions and command subcommands that change a Task; reading one is not recording work.
const WRITE_ACTIONS = new Set(["create", "status", "note", "attach", "remove_file"]);
// A command run as a command (at the start, or after ; & | ( or a newline, by name or full path),
// not merely mentioned.
const COMMAND_WRITE = /(?:^|[;&|(\n])\s*(?:\S*\/)?agentbarn-task\s+(?:create|status|note|attach|remove-file)\b/;
// A file the Agent published for the user is part of the result, however it was written.
const ARTIFACT_UPLOAD = /(?:^|[;&|(\n])\s*(?:\S*\/)?agentbarn-artifacts\s+upload\s+([^;&|)\n]+)/g;
const REDACTED = "[redacted]";
// Credentials a user may paste into a request. The automatic Task's title and description
// come from the request, and people across the Organization can read them.
const SECRET_PATTERNS = [
  [/-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)/g, REDACTED],
  [/(:\/\/[^/\s:@]+:)[^/\s@]+@/g, `$1${REDACTED}@`],
  [/(\bbearer\s+)\S+/gi, `$1${REDACTED}`],
  // The keyword may sit inside a longer name (DB_PASSWORD=, GITHUB_TOKEN=) or a quoted JSON key.
  [
    /(\w*(?:password|passwd|pwd|passphrase|secret|token|api[_-]?key|access[_-]?key|client[_-]?secret)\w*["']?\s*(?:[:=]|\bis\b)\s*["']?)[^\s"',}]+/gi,
    `$1${REDACTED}`,
  ],
  [/\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}/g, REDACTED],
  [/\b(?:gh[pousr]_|github_pat_|glpat-|xox[abposr]-)[A-Za-z0-9_-]{10,}/g, REDACTED],
  [/\bAKIA[0-9A-Z]{16}\b/g, REDACTED],
  [/\bAIza[0-9A-Za-z_-]{35}\b/g, REDACTED],
  [/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g, REDACTED],
];
// Files that hold credentials are never attached automatically: anyone who may read the Agent's
// Tasks could download them. The Agent can still attach one on purpose.
const CREDENTIAL_FILE =
  /^(?:\.env(?:\..*)?|\.netrc|\.npmrc|\.pgpass|id_(?:rsa|dsa|ecdsa|ed25519)(?:\.pub)?|.*\.(?:pem|key|p12|pfx)|.*credentials.*\.json|service[-_]account.*\.json)$/i;
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
  "agentbarn_task tool (a body says what was done). Files you write with your file-writing tool are " +
  "attached and the Task is marked done when the run ends; attach any other file that is part of the " +
  "result yourself.";
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
    keep: {
      type: "boolean",
      description:
        "With create, or status in_progress: keep the Task in progress after this turn, because the job " +
        "continues in a later turn (more parts or messages to come). Without it the Task is marked done when " +
        "the turn ends.",
    },
    path: { type: "string", description: "The file to attach, absolute or relative to your workspace." },
    name: { type: "string", description: "The file's name as shown on the Task, for attach." },
    content_type: { type: "string", description: "A bare type/subtype, for attach." },
    file_id: { type: "string", description: "The file's id from show, for remove_file." },
  },
  required: ["action"],
};

// runId -> what the run did: tool call ids, files written and attached, reminders sent
const runs = new Map();
const taskListCache = new Map();
const identities = new Map();
// sessionKey -> its current runId; tool_result_persist is not told which run a result belongs to.
const currentRun = new Map();
// sessionKey -> the reminder its next turn starts with
const nextTurnReminders = new Map();
// sessionKey -> the user's latest request, the title of a Task recorded automatically
const requests = new Map();
// runId -> the id of the scheduled job the run belongs to
const runJobs = new Map();
// Jobs removed while one of their runs was still going; that run finishes their Task when it ends.
const removedMidRun = new Set();

// Store a value as the newest entry, forgetting the oldest past SESSIONS_KEPT.
function remember(map, key, value) {
  map.delete(key);
  map.set(key, value);
  while (map.size > SESSIONS_KEPT) map.delete(map.keys().next().value);
}

const forgetTaskList = (agent) => {
  taskListCache.delete(agent);
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

function agentOf(ctx) {
  if (ctx?.agentId) return ctx.agentId;
  const scoped = /^agent:([^:]+):/.exec(ctx?.sessionKey ?? "");
  return scoped ? scoped[1] : MAIN_AGENT;
}

const workspace = (agent) =>
  `${process.env.HOME}/.openclaw/${agent === MAIN_AGENT ? "workspace" : `workspace-${agent}`}`;

function identity(agent) {
  if (agent === MAIN_AGENT) return {};
  if (identities.has(agent)) return identities.get(agent);
  if (!AGENT_NAME.test(agent)) return null;
  const values = {};
  for (const name of IDENTITY_NAMES) {
    try {
      values[name] = fs.readFileSync(joinPath(SECRET_ROOT, agent, name), "utf8");
    } catch {
      values[name] = "";
    }
  }
  if (values.AGENT_ID !== agent || !values.INGEST_URL || !values.INGEST_API_KEY) return null;
  values.ARTIFACT_UPLOAD_ROOTS = workspace(agent);
  identities.set(agent, values);
  return values;
}

const maxBytes = (agent) => Number((identity(agent) ?? {}).ARTIFACT_MAX_BYTES ?? process.env.ARTIFACT_MAX_BYTES) || Infinity;

const UNAVAILABLE = "Agent Barn Tasks are unavailable right now, so the change was not confirmed.";

function run(agent, argv, stdin = "", timeoutMs = COMMAND_TIMEOUT_MS) {
  return new Promise((resolve) => {
    const own = identity(agent);
    if (own === null) {
      resolve({ ok: false, output: UNAVAILABLE });
      return;
    }
    let stdout = "";
    let stderr = "";
    let child;
    try {
      child = spawn(command(), argv, { cwd: workspace(agent), env: { ...process.env, ...own } });
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

async function executeTool(agent, _toolCallId, params) {
  const built = argvFor(params && typeof params === "object" ? params : {});
  if (typeof built === "string") return textResult({ error: built });
  const [argv, stdin] = built;
  const { ok, output } = await run(agent, argv, stdin);
  if (!["list", "show"].includes(argv[0])) forgetTaskList(agent);
  if (!ok) return textResult({ error: output });
  try {
    return textResult(JSON.parse(output));
  } catch {
    return textResult({ result: output });
  }
}

const touchesTasks = (toolName, params) =>
  toolName === TOOL || (typeof params?.command === "string" && params.command.includes("agentbarn-task"));

// Whether a tool call failed. OpenClaw sets `error` for a failed write, edit or patch, but a
// command that exits non-zero completes normally and only carries its exit code.
function failed(event) {
  const exitCode = event.result?.details?.exitCode;
  return Boolean(event.error) || (typeof exitCode === "number" && exitCode !== 0);
}

// The files a successful write, edit or patch produced. apply_patch names its files only in the
// patch text, so the paths it reports back are used.
function writtenPaths(event) {
  const summary = event.result?.details?.summary;
  if (summary && typeof summary === "object") {
    return [...(summary.added ?? []), ...(summary.modified ?? [])].filter((path) => typeof path === "string" && path);
  }
  const path = event.params?.path ?? event.params?.file_path;
  return typeof path === "string" && path ? [path] : [];
}

// Files a shell command published with `agentbarn-artifacts upload`. Workflow uploads (with
// --attempt-id) belong to their run, not to a Task.
function publishedPaths(params) {
  const command = params?.command;
  if (typeof command !== "string") return [];
  const paths = [];
  for (const match of command.matchAll(ARTIFACT_UPLOAD)) {
    const words = [...match[1].matchAll(/"([^"]*)"|'([^']*)'|(\S+)/g)].map((word) => word[1] ?? word[2] ?? word[3]);
    if (words.length && !words.some((word) => word.startsWith("--attempt-id"))) paths.push(words[0]);
  }
  return paths;
}

// Whether a Task call changed a Task: a write that did not fail. Reading Tasks is not recording work.
function recordsTask(toolName, params, result, event = {}) {
  if (toolName !== TOOL) {
    return typeof params?.command === "string" && COMMAND_WRITE.test(params.command) && !failed(event);
  }
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
  let status;
  if (params?.action === "create") status = STATUSES.includes(params.status) ? params.status : "in_progress";
  else if (params?.action === "status" && STATUSES.includes(params.status)) status = params.status;
  else return null;
  return status === "in_progress" && (params.keep === true || params.keep === "true") ? KEPT : status;
}

function track(event, ctx) {
  const runId = event.runId ?? ctx.runId ?? "";
  if (ctx.sessionKey) remember(currentRun, ctx.sessionKey, runId);
  let state = runs.get(runId);
  if (!state) {
    state = newState(ctx);
    remember(runs, runId, state);
  }
  return state;
}

// What the plugin knows about one run.
const newState = (ctx) => ({
  work: new Set(), wroteFiles: false, written: new Set(), recorded: false, taskIds: new Set(),
  // taskId -> the last status the Agent set this run
  statuses: new Map(),
  attached: new Set(), reminded: false, revised: false, sessionKey: ctx.sessionKey ?? "", agent: agentOf(ctx),
  // The Task the Agent touched last, and the titles it gave the Tasks it created.
  lastTask: null, titles: new Map(),
  // Schedules the Agent created this run, and the ids of those it removed.
  schedules: [], removedJobs: new Set(),
  // The run's tool calls, one short line each, for the question asked before a Task is closed.
  tools: [], toolIds: new Set(),
});

// One tool call as a short line, its name and arguments, for the question asked before a Task is closed.
function toolSummary(name, params) {
  let text = "";
  try {
    text = JSON.stringify(params) ?? "";
  } catch {
    text = "";
  }
  return redacted(`${name} ${text}`).slice(0, TOOL_SUMMARY_CHARS);
}

// Ask Agent Barn which of the Tasks about to be marked done are not finished. Returns
// taskId -> the status to leave it in ("in_progress" or "open"); empty when nothing is held.
async function held(state, reply, trigger, closing) {
  const told = {
    request: redacted(requests.get(state.sessionKey) ?? "").slice(0, TURN_TEXT_CHARS),
    reply: redacted(reply).slice(0, TURN_TEXT_CHARS),
    tools: state.tools,
    closing,
    trigger: String(trigger ?? "").slice(0, 60),
  };
  const answer = await run(state.agent, ["turn-end"], JSON.stringify(told), TURN_END_TIMEOUT_MS);
  try {
    const holds = answer.ok ? JSON.parse(answer.output).holds : null;
    return holds && typeof holds === "object" ? holds : {};
  } catch {
    return {};
  }
}

const linksPath = () => `${process.env.HOME}/.openclaw/agentbarn-task-schedules.json`;

// Job id -> {task_id, agent, runs}: the Tasks that follow a schedule, and whose they are. Kept beside OpenClaw's own state.
function readLinks() {
  try {
    const links = JSON.parse(fs.readFileSync(linksPath(), "utf8"));
    return links && typeof links === "object" && !Array.isArray(links) ? links : {};
  } catch {
    return {};
  }
}

function saveLinks(links) {
  try {
    fs.writeFileSync(`${linksPath()}.tmp`, JSON.stringify(links));
    fs.renameSync(`${linksPath()}.tmp`, linksPath());
  } catch {
    // The link is a convenience; the Agent can still update the Task itself.
  }
}

// Stop following a schedule; its Task is done unless another schedule still feeds it.
async function endLink(jobId, setDone = true) {
  const links = readLinks();
  const link = links[jobId];
  if (!link) return;
  delete links[jobId];
  saveLinks(links);
  if (!setDone || Object.values(links).some((other) => other?.task_id === link.task_id)) return;
  const agent = link.agent ?? MAIN_AGENT;
  await run(agent, ["status", link.task_id, "done"]);
  forgetTaskList(agent);
}

function recurrenceOf(schedule) {
  if (schedule?.kind === "every" && typeof schedule.everyMs === "number") return `every ${Math.round(schedule.everyMs / 1000)}s`;
  if (schedule?.kind === "cron" && typeof schedule.expr === "string") return schedule.expr;
  if (schedule?.kind === "at") return `once at ${schedule.at ?? ""}`.trim();
  return String(schedule?.kind ?? "");
}

// Remember a schedule the Agent created or removed with OpenClaw's scheduler tool.
function trackSchedule(state, event) {
  const params = event.params ?? {};
  if (failed(event)) return;
  if (params.action === "remove") {
    const jobId = params.jobId ?? params.id;
    if (typeof jobId === "string") state.removedJobs.add(jobId);
    return;
  }
  if (params.action !== "add") return;
  const details = event.result?.details ?? {};
  const job = details.job ?? details;
  if (typeof job?.id !== "string") return;
  const schedule = job.schedule ?? params.job?.schedule ?? params.schedule;
  state.schedules.push({
    jobId: job.id,
    name: String(job.name ?? params.job?.name ?? ""),
    recurrence: recurrenceOf(schedule).slice(0, 200),
    // OpenClaw has no run limit: only a one-off is known to end.
    runLimit: schedule?.kind === "at" ? 1 : null,
  });
}

// Decide, for each schedule created this run, whether its runs are part of the Task for the request.
// A decision model reads the request once. Without its answer, a Task the Agent kept follows the schedule.
async function linkSchedules(sessionKey, state) {
  const request = redacted(requests.get(sessionKey) ?? "");
  for (const schedule of state.schedules) {
    let taskId = state.lastTask;
    const agentStatus = taskId ? state.statuses.get(taskId) : undefined;
    const asked = {
      request: request.slice(0, AUTOMATIC_DESCRIPTION_CHARS),
      schedule: { recurrence: schedule.recurrence, run_limit: schedule.runLimit },
      task: {
        title: taskId ? (state.titles.get(taskId) ?? "").slice(0, 500) : "",
        status: agentStatus === KEPT ? "in_progress" : (agentStatus ?? ""),
      },
    };
    const answer = await run(state.agent, ["schedule-intent"], JSON.stringify(asked), INTENT_TIMEOUT_MS);
    let intent = null;
    try {
      intent = answer.ok ? (JSON.parse(answer.output).intent ?? null) : null;
    } catch {
      intent = null;
    }
    if (intent === null) intent = agentStatus === KEPT ? "runs" : "setup";
    if (intent !== "runs") {
      // Setting up the schedule was the whole job, so the Task for it is finished.
      if (taskId && (agentStatus === KEPT || agentStatus === "in_progress")) {
        await run(state.agent, ["status", taskId, "done"]);
        state.statuses.set(taskId, "done");
        forgetTaskList(state.agent);
      }
      continue;
    }
    if (!taskId) {
      const words = request.split(/\s+/).filter(Boolean).join(" ");
      const title = (schedule.name || words || "Scheduled work").slice(0, AUTOMATIC_TITLE_CHARS);
      const created = await run(state.agent, ["create", `--title=${title}`, "--status=in_progress", "--origin=automatic"]);
      try {
        taskId = created.ok ? JSON.parse(created.output).id : null;
      } catch {
        taskId = null;
      }
      if (typeof taskId !== "string") continue;
      state.recorded = true;
      state.taskIds.add(taskId);
      state.lastTask = taskId;
    } else if (agentStatus !== KEPT && agentStatus !== "in_progress") {
      await run(state.agent, ["status", taskId, "in_progress"]);
    }
    state.statuses.set(taskId, KEPT);
    const links = readLinks();
    links[schedule.jobId] = { task_id: taskId, agent: state.agent };
    saveLinks(links);
    forgetTaskList(state.agent);
  }
}

// The Agent's final reply in a run's messages, as plain text.
function lastReply(messages) {
  if (!Array.isArray(messages)) return "";
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message?.role !== "assistant") continue;
    const content = message.content;
    const text =
      typeof content === "string"
        ? content
        : Array.isArray(content)
          ? content.filter((part) => part?.type === "text" && typeof part.text === "string").map((part) => part.text).join(" ")
          : "";
    if (text.trim()) return text;
  }
  return "";
}

// Note a scheduled run on the Task that follows its schedule. False when no Task does.
async function recordScheduledRun(jobId, state, event) {
  const links = readLinks();
  const link = links[jobId];
  if (typeof link?.task_id !== "string") return false;
  const taskId = link.task_id;
  const agent = link.agent ?? MAIN_AGENT;
  const number = (Number.isInteger(link.runs) ? link.runs : 0) + 1;
  const reply = redacted(lastReply(event.messages)).split(/\s+/).filter(Boolean).join(" ");
  await run(agent, ["note", taskId], reply ? `Run ${number}: ${reply.slice(0, RUN_NOTE_CHARS)}` : `Run ${number}.`);
  if (state) {
    state.taskIds = new Set([taskId]);
    await attachAutomatically(state);
  }
  if (state?.removedJobs.has(jobId) || removedMidRun.delete(jobId)) {
    // The run ended its own schedule, so the job is finished.
    await endLink(jobId);
  } else {
    links[jobId] = { ...link, runs: number };
    saveLinks(links);
    const set = state?.statuses.get(taskId);
    // The schedule is still live, so the Task is not finished whatever this run set.
    if (set && ![KEPT, "in_progress", "failed"].includes(set)) await run(agent, ["status", taskId, "in_progress"]);
  }
  forgetTaskList(agent);
  return true;
}

// The scheduled job a run belongs to. OpenClaw names it on the run, in an isolated run's session key
// (agent:<id>:cron:<jobId>:run:<n>), and at the start of every scheduled prompt ([cron:<jobId> <name>]).
function jobOf(ctx, prompt) {
  if (ctx.trigger !== "cron") return undefined;
  if (typeof ctx.jobId === "string" && ctx.jobId) return ctx.jobId;
  const inKey = /(?:^|:)cron:([^:]+)(?::|$)/.exec(ctx.sessionKey ?? "");
  if (inKey) return inKey[1];
  const inPrompt = /^\[cron:(\S+)[ \]]/.exec(typeof prompt === "string" ? prompt : "");
  return inPrompt ? inPrompt[1] : undefined;
}

const unrecordedWork = (state) =>
  Boolean(state) && !state.recorded && (state.wroteFiles || state.work.size >= WORK_THRESHOLD);

const attachReminder = (names) =>
  `These files you produced are not on a Task yet: ${names.join(", ")}. Attach the ones that are part of ` +
  "the result with the agentbarn_task tool (action attach).";

// The run's written files, as [name, path], that it has not attached and may attach.
const unattachedFiles = (state) =>
  [...state.written]
    .sort()
    .map((path) => [basename(path), path])
    .filter(([name]) => !state.attached.has(name) && !CREDENTIAL_FILE.test(name));

// Attach the run's files to the one Task it touched. Returns the names it could not attach.
async function attachAutomatically(state) {
  const unattached = unattachedFiles(state);
  if (state.taskIds.size !== 1) return unattached.map(([name]) => name);
  const [taskId] = state.taskIds;
  const limit = maxBytes(state.agent);
  const names = unattached.map(([name]) => name);
  const notAttached = [];
  for (const [name, path] of unattached) {
    let size;
    try {
      size = fs.statSync(path).size;
    } catch {
      continue;
    }
    if (size > limit) {
      notAttached.push(name);
      continue;
    }
    // A newer copy replaces the Task's file of the same name, unless this run wrote two files of
    // that name in different folders: then both are kept.
    const replace = names.filter((other) => other === name).length === 1 ? ["--replace"] : [];
    const { ok } = await run(state.agent, ["attach", taskId, path, ...replace]);
    if (!ok) notAttached.push(name);
  }
  return notAttached;
}

// Move each Task the Agent left in_progress this run to `status`; a status it chose itself stays.
// A Task it kept stays in_progress, unless the run failed: then it is reopened too.
async function settleInProgress(state, status, reply = "", trigger = "") {
  const settles = status === "open" ? ["in_progress", KEPT] : ["in_progress"];
  const inProgress = [...state.statuses].filter(([, current]) => settles.includes(current)).map(([id]) => id).sort();
  if (!inProgress.length) return;
  // A Task about to be marked done is held back when Agent Barn finds its job is not finished.
  const holds = status === "done" ? await held(state, reply, trigger, inProgress) : {};
  for (const taskId of inProgress) {
    if (holds[taskId] === "in_progress") continue;
    await run(state.agent, ["status", taskId, holds[taskId] === "open" ? "open" : status]);
  }
  forgetTaskList(state.agent);
}

// Record a Task for work the Agent left unrecorded. Returns the files it could not attach.
async function recordAutomatically(sessionKey, state) {
  const request = redacted(requests.get(sessionKey) ?? "").split(/\s+/).filter(Boolean).join(" ");
  let title = request || "Work recorded automatically";
  if (title.length > AUTOMATIC_TITLE_CHARS) title = `${title.slice(0, AUTOMATIC_TITLE_CHARS - 1).trimEnd()}…`;
  const argv = ["create", `--title=${title}`, "--status=done", "--origin=automatic"];
  if (request) argv.push(`--description=${request.slice(0, AUTOMATIC_DESCRIPTION_CHARS)}`);
  const { ok, output } = await run(state.agent, argv);
  forgetTaskList(state.agent);
  let taskId;
  try {
    taskId = ok ? JSON.parse(output).id : undefined;
  } catch {
    taskId = undefined;
  }
  if (typeof taskId !== "string") {
    return unattachedFiles(state).map(([name]) => name);
  }
  state.taskIds = new Set([taskId]);
  return attachAutomatically(state);
}

function smallTalk(message) {
  const words = typeof message === "string" ? message.toLowerCase().replaceAll("'", "").match(/[a-z]+/g) ?? [] : [];
  return words.length > 0 && words.length <= SMALL_TALK_MAX_WORDS && words.every((word) => SMALL_TALK_WORDS.has(word));
}

// The open Tasks, then the latest finished ones, from one listing (most recently changed first).
// An unfinished Task is listed with the start of its latest note, so a later turn or scheduled run,
// which has no memory of earlier ones, sees where the work got to.
function notePreview(note) {
  const text = typeof note === "string" ? note.split(/\s+/).filter(Boolean).join(" ") : "";
  if (!text) return "";
  return ` (latest note: "${text.slice(0, LATEST_NOTE_CHARS)}${text.length > LATEST_NOTE_CHARS ? "…" : ""}")`;
}

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
      const note = status === "done" ? "" : notePreview(task.latest_note);
      lines.push(`- ${task.id} [${status}] ${String(task.title ?? "").slice(0, 120)}${note}`);
    }
  }
  return lines;
}

async function openTaskLines(agent) {
  const cached = taskListCache.get(agent);
  if (cached && Date.now() - cached.at < OPEN_TASKS_TTL_MS) return cached.lines;
  const { ok, output } = await run(agent, ["list", `--page-size=${LIST_PAGE_SIZE}`], "", LIST_TIMEOUT_MS);
  const lines = ok ? taskLines(output) : [];
  remember(taskListCache, agent, { at: Date.now(), lines });
  return lines;
}

export default {
  id: "agentbarn-tasks",
  name: "Agent Barn Tasks",
  description: "Give the Agent a Task tool, show its open Tasks each turn, and remind it to record its work",
  register(api) {
    const { AGENT_ID, INGEST_URL, INGEST_API_KEY } = process.env;
    if (!AGENT_ID || !INGEST_URL || !INGEST_API_KEY) return;

    api.registerTool((ctx) => ({
      name: TOOL,
      label: "Agent Barn Task",
      description:
        "Record work that uses tools or produces files as a Task the people you work for can follow. `create` " +
        "one before you start (it starts in_progress); when your run ends, files you wrote with your " +
        "file-writing tool or published are attached and a Task still in_progress is marked done. If the work " +
        "continues in a later turn and is not waiting on the user, set it in_progress with keep: true so it stays " +
        "in progress. Attach any other file that is part of the result yourself. Set `failed` (with a body saying " +
        "why), `open` (waiting on the user) or `done` yourself.",
      parameters: PARAMETERS,
      execute: (toolCallId, params) => executeTool(agentOf(ctx), toolCallId, params),
    }), { name: TOOL });

    api.on("after_tool_call", (event, ctx) => {
      if (ctx.trigger === "heartbeat" || sideRun(ctx.sessionKey)) return;
      const state = track(event, ctx);
      if (event.toolCallId && !state.toolIds.has(event.toolCallId) && state.tools.length < TURN_TOOLS_SENT) {
        state.toolIds.add(event.toolCallId);
        state.tools.push(toolSummary(event.toolName, event.params));
      }
      if (SCHEDULER_TOOLS.has(event.toolName)) trackSchedule(state, event);
      if (touchesTasks(event.toolName, event.params)) {
        if (!recordsTask(event.toolName, event.params, event.result, event)) return;
        state.recorded = true;
        for (const name of attachedNames(event.toolName, event.params)) state.attached.add(name);
        const taskId = taskIdOf(event.toolName, event.params, event.result);
        if (taskId) {
          state.taskIds.add(taskId);
          state.lastTask = taskId;
          if (typeof event.params?.title === "string") state.titles.set(taskId, event.params.title);
          const status = statusSet(event.toolName, event.params);
          if (status) state.statuses.set(taskId, status);
        }
      } else {
        if (event.toolCallId) state.work.add(event.toolCallId);
        if (FILE_TOOLS.has(event.toolName) && !failed(event)) {
          state.wroteFiles = true;
          for (const path of writtenPaths(event)) state.written.add(resolvePath(workspace(state.agent), path));
        }
        const published = failed(event) ? [] : publishedPaths(event.params);
        if (published.length) {
          state.wroteFiles = true;
          for (const path of published) state.written.add(resolvePath(workspace(state.agent), path));
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
      const jobId = runJobs.get(runId) ?? jobOf(ctx, requests.get(sessionKey));
      runJobs.delete(runId);
      if (ctx.trigger === "heartbeat" || sideRun(sessionKey)) return;
      if (typeof jobId === "string" && (await recordScheduledRun(jobId, state, event))) return;
      if (!state) return;
      const succeeded = event.success !== false;
      if (succeeded && state.schedules.length) await linkSchedules(sessionKey, state);
      // A status the Agent set itself while removing a schedule stands.
      for (const removed of state.removedJobs) {
        await endLink(removed, !state.statuses.has(readLinks()[removed]?.task_id));
      }
      let failed;
      if (succeeded && unrecordedWork(state)) {
        failed = await recordAutomatically(sessionKey, state);
      } else if (state.recorded) {
        // A run that failed leaves its Task open to pick up again, not in progress.
        failed = await attachAutomatically(state);
        if (succeeded) await settleInProgress(state, "done", lastReply(event.messages), ctx.trigger);
        else await settleInProgress(state, "open");
      } else {
        return;
      }
      if (failed.length) remember(nextTurnReminders, sessionKey, attachReminder(failed) + QUIET);
    });

    // A schedule that is removed, or a one-off that has run, finishes the Task that follows it.
    api.on("cron_changed", async (event) => {
      const jobId = event?.jobId;
      if (typeof jobId !== "string" || !readLinks()[jobId]) return;
      const ended = event.action === "removed" || (event.action === "finished" && event.job?.schedule?.kind === "at");
      if (!ended) return;
      if ([...runJobs.values()].includes(jobId)) removedMidRun.add(jobId);
      else await endLink(jobId);
    });

    api.on("before_prompt_build", async (event, ctx) => {
      if (ctx.trigger === "heartbeat" || sideRun(ctx.sessionKey)) return;
      const jobId = jobOf(ctx, event.prompt);
      const runId = event.runId ?? ctx.runId;
      if (jobId && runId) remember(runJobs, runId, jobId);
      const parts = [];
      if (ctx.trigger === "user" || ctx.trigger === "cron") {
        if (typeof event.prompt === "string") {
          remember(requests, ctx.sessionKey ?? "", event.prompt.slice(0, AUTOMATIC_DESCRIPTION_CHARS));
        }
        if (!smallTalk(event.prompt)) parts.push(REQUEST_LINE);
      }
      const lines = await openTaskLines(agentOf(ctx));
      if (lines.length) {
        parts.push(
          `Your open and latest finished Tasks:\n${lines.join("\n")}\nKeep using one of these only when the ` +
            "request is the same piece of work: set it to in_progress with the agentbarn_task tool, with keep: true " +
            "if the work still continues after this turn. A new request gets its own Task, even while another is " +
            "in progress.",
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
