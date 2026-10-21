// Run the Task command through the pinned core's real exec tool, as the Agent would.
import fs from "node:fs";

const dist = "/usr/local/lib/node_modules/openclaw/dist";
// Bundle file names are content hashes; find the module by what it exports.
let createExecTool;
for (const name of fs.readdirSync(dist).filter((file) => /^bash-tools-.*\.js$/.test(file))) {
  createExecTool ??= (await import(`${dist}/${name}`)).createExecTool;
}
if (!createExecTool) throw new Error("the pinned OpenClaw core no longer exports createExecTool");

const taskId = process.argv[2];
const state = process.env.HOME + "/.openclaw";
const workspace = state + "/workspace";
const config = JSON.parse(fs.readFileSync(state + "/openclaw.json", "utf8"));
const exec = createExecTool({
  config,
  agentId: "main",
  sessionKey: "agent:main:connection:task-contract:session",
  cwd: workspace,
  host: "gateway",
  security: "full",
  ask: "off",
  allowBackground: false,
  notifyOnExit: false,
});

const commands = {
  discover: "command -v agentbarn-task",
  create: 'agentbarn-task create --title "Reconcile invoices" --description "For October"',
  status: `agentbarn-task status ${taskId} in_progress`,
  note: `agentbarn-task note ${taskId} <<'NOTE'\nMatched 40 of 42 invoices\nNOTE`,
  attach: `printf 'invoice,amount\\n1,10\\n' > report.csv && agentbarn-task attach ${taskId} report.csv`,
  refused: `printf 'x' > too-big.csv && agentbarn-task attach ${taskId} too-big.csv`,
  list: "agentbarn-task list --status open",
  show: `agentbarn-task show ${taskId}`,
};

const results = {};
let call = 0;
for (const [name, command] of Object.entries(commands)) {
  const result = await exec.execute(`task-contract-${call++}`, { command, workdir: workspace, timeoutSeconds: 30 });
  const output = (result.content ?? []).map((part) => part.text ?? "").join("\n");
  results[name] = { exit_code: result.details?.exitCode ?? null, output, details: result.details ?? null };
}
console.log("TASK_RUNTIME_CONTRACT=" + JSON.stringify({
  results,
  instructions: fs.readFileSync(workspace + "/AGENTS.md", "utf8"),
}));
process.exit(0);
