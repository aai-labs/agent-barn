const fs = require('fs');
const path = require('path');

const HOME = process.env.HOME || '/home/node';
const TEMPLATE_DIR = '/app/config';
const WORKSPACE_DIR = path.join(HOME, '.openclaw', 'workspace');
const OVERLAY_PATH = path.join(TEMPLATE_DIR, 'openclaw-config-overlay.json');
const CONFIG_PATH = path.join(HOME, '.openclaw', 'openclaw.json');

// These paths are replaced wholesale from the overlay rather than deep-merged,
// so an old provider configuration cannot survive the headless-runtime cutover.
const REPLACE_PATHS = [
  ['channels'],
  ['bindings'],
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

let config = {};
try { config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8')); } catch {}

// PRUNE DEPRECATED FIELDS FROM OLD CONFIG
if (config.tools && config.tools.exec) {
  delete config.tools.exec;
}

const merged = deepMerge(config, overlay);

for (const parts of REPLACE_PATHS) {
  const overlayVal = getPath(overlay, parts);
  if (overlayVal !== undefined) setPath(merged, parts, overlayVal);
}

fs.mkdirSync(path.dirname(CONFIG_PATH), { recursive: true });
fs.writeFileSync(CONFIG_PATH, JSON.stringify(merged, null, 2));
console.log('[init-openclaw] Config merged successfully');
