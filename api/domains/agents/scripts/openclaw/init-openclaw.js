const fs = require('fs');
const path = require('path');

const HOME = process.env.HOME || '/home/node';
const TEMPLATE_DIR = '/app/config';
const WORKSPACE_DIR = path.join(HOME, '.openclaw', 'workspace');
const OVERLAY_PATH = path.join(TEMPLATE_DIR, 'openclaw-config-overlay.json');
const CONFIG_PATH = path.join(HOME, '.openclaw', 'openclaw.json');
const PREINSTALLED_NPM_DIR = '/opt/openclaw-preinstalled/npm';
const RUNTIME_NPM_DIR = path.join(HOME, '.openclaw', 'npm');
const PREINSTALLED_NODE_MODULES_DIR = path.join(PREINSTALLED_NPM_DIR, 'node_modules');
const PREINSTALLED_MSTEAMS_DIR = path.join(PREINSTALLED_NODE_MODULES_DIR, '@openclaw', 'msteams');
const RUNTIME_NODE_MODULES_DIR = path.join(RUNTIME_NPM_DIR, 'node_modules');

// These paths are replaced wholesale from the overlay rather than deep-merged,
// so that removals (e.g. removing a channel or DM user) take effect on restart.
const REPLACE_PATHS = [
  ['channels', 'slack', 'channels'],
  ['channels', 'slack', 'allowFrom'],
  ['channels', 'msteams', 'allowFrom'],
  ['channels', 'telegram', 'allowFrom'],
];

function getPath(obj, parts) {
  return parts.reduce((cur, key) => (cur && typeof cur === 'object' ? cur[key] : undefined), obj);
}

function setPath(obj, parts, value) {
  const last = parts[parts.length - 1];
  const parent = parts.slice(0, -1).reduce((cur, key) => {
    if (!cur[key] || typeof cur[key] !== 'object') cur[key] = {};
    return cur[key];
  }, obj);
  parent[last] = value;
}

function deepMerge(base, overlay) {
  const result = Object.assign({}, base);
  for (const [key, val] of Object.entries(overlay)) {
    result[key] = (val && typeof val === 'object' && !Array.isArray(val)
      && result[key] && typeof result[key] === 'object' && !Array.isArray(result[key]))
      ? deepMerge(result[key], val)
      : val;
  }
  return result;
}

function isPathInside(child, parent) {
  const relative = path.relative(parent, child);
  return relative === '' || (!!relative && !relative.startsWith('..') && !path.isAbsolute(relative));
}

function realpathOrResolved(filePath) {
  try { return fs.realpathSync(filePath); }
  catch { return path.resolve(filePath); }
}

function restorePreinstalledMsteamsPlugin(overlay) {
  if (getPath(overlay, ['channels', 'msteams', 'enabled']) !== true) return;
  if (!fs.existsSync(PREINSTALLED_MSTEAMS_DIR)) {
    console.log('[init-openclaw] Preinstalled msteams plugin missing, skipping restore');
    return;
  }

  const sourceReal = realpathOrResolved(PREINSTALLED_NODE_MODULES_DIR);
  const destReal = realpathOrResolved(RUNTIME_NODE_MODULES_DIR);
  if (isPathInside(destReal, sourceReal) || isPathInside(sourceReal, destReal)) {
    console.log('[init-openclaw] Skipping msteams restore: source/destination overlap');
    return;
  }

  if (fs.existsSync(RUNTIME_NPM_DIR) && fs.lstatSync(RUNTIME_NPM_DIR).isSymbolicLink()) {
    console.log('[init-openclaw] Skipping msteams restore: runtime npm path is a symlink');
    return;
  }

  fs.mkdirSync(RUNTIME_NPM_DIR, { recursive: true });
  for (const metadataFile of ['package.json', 'package-lock.json']) {
    const sourceFile = path.join(PREINSTALLED_NPM_DIR, metadataFile);
    if (fs.existsSync(sourceFile)) {
      fs.copyFileSync(sourceFile, path.join(RUNTIME_NPM_DIR, metadataFile));
    }
  }

  fs.mkdirSync(RUNTIME_NODE_MODULES_DIR, { recursive: true });
  fs.cpSync(PREINSTALLED_NODE_MODULES_DIR, RUNTIME_NODE_MODULES_DIR, { recursive: true, force: true });
  console.log('[init-openclaw] Restored preinstalled Microsoft Teams npm plugin');
}

// Files the agent writes runtime state to — never overwrite on restart.
const AGENT_OWNED_FILES = new Set(['USER.md']);

fs.mkdirSync(WORKSPACE_DIR, { recursive: true });
for (const file of fs.readdirSync(TEMPLATE_DIR)) {
  if (!file.endsWith('.md')) continue;
  const dest = path.join(WORKSPACE_DIR, file);
  if (AGENT_OWNED_FILES.has(file) && fs.existsSync(dest)) {
    console.log(`[init-openclaw] Preserving workspace/${file} (agent-owned)`);
    continue;
  }
  fs.copyFileSync(path.join(TEMPLATE_DIR, file), dest);
  console.log(`[init-openclaw] Copied workspace/${file}`);
}

// Reconstruct skill docs under workspace/skills/<path> from the bundled manifest.
const SKILLS_MANIFEST = path.join(TEMPLATE_DIR, 'skills.json');
if (fs.existsSync(SKILLS_MANIFEST)) {
  const SKILLS_DIR = path.join(WORKSPACE_DIR, 'skills');
  let entries = [];
  try { entries = JSON.parse(fs.readFileSync(SKILLS_MANIFEST, 'utf8')); }
  catch { entries = []; }
  let written = 0;
  for (const { path: rel, content } of entries) {
    const dest = path.join(SKILLS_DIR, rel);
    if (!isPathInside(dest, SKILLS_DIR)) continue;  // block ../ traversal
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.writeFileSync(dest, content);
    written += 1;
  }
  console.log(`[init-openclaw] Wrote ${written} skill files`);
}

let overlay;
try { overlay = JSON.parse(fs.readFileSync(OVERLAY_PATH, 'utf8')); }
catch { console.log('[init-openclaw] No overlay found, skipping'); process.exit(0); }

restorePreinstalledMsteamsPlugin(overlay);

let config = {};
try { config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8')); } catch {}

const merged = deepMerge(config, overlay);

for (const parts of REPLACE_PATHS) {
  const overlayVal = getPath(overlay, parts);
  if (overlayVal !== undefined) setPath(merged, parts, overlayVal);
}

fs.mkdirSync(path.dirname(CONFIG_PATH), { recursive: true });
fs.writeFileSync(CONFIG_PATH, JSON.stringify(merged, null, 2));
console.log('[init-openclaw] Config merged successfully');

// Overwrite allowFrom credentials so the configured allowlist wins over stale runtime state.
// openclaw writes paired users to <channel>-default-allowFrom.json (wrapped) at runtime; we mirror both here.
for (const [channel, allowFile, defaultAllowFile] of [
  ['slack', 'slack-allowFrom.json', 'slack-default-allowFrom.json'],
  ['msteams', 'msteams-allowFrom.json', 'msteams-default-allowFrom.json'],
  ['telegram', 'telegram-allowFrom.json', 'telegram-default-allowFrom.json'],
]) {
  const af = getPath(overlay, ['channels', channel, 'allowFrom']);
  if (af !== undefined) {
    const credDir = path.join(HOME, '.openclaw', 'credentials');
    fs.mkdirSync(credDir, { recursive: true });
    fs.writeFileSync(path.join(credDir, allowFile), JSON.stringify(af, null, 2));
    fs.writeFileSync(
      path.join(credDir, defaultAllowFile),
      JSON.stringify({ version: 1, allowFrom: af }, null, 2),
    );
    console.log('[init-openclaw] Synced ' + channel + ' allowFrom credentials');
  }
}
