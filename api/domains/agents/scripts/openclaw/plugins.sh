# Sourced by start.sh. Needs OPENCLAW_VERSION and CORE_DIR; PLUGIN_PROJECTS can be
# overridden (the startup tests point it at a scratch directory).
PLUGIN_PROJECTS="${PLUGIN_PROJECTS:-/home/node/.openclaw/npm/projects}"

# Official plugins install from npm at the core's version: OpenClaw only grants plugin
# state to npm installs it recorded, and those records live on the PVC. A reinstall
# fails once present, so skip plugins already at the core's version.
#
# Each install also links the core into the plugin from /usr/local, outside the
# volume, so restore points cannot carry that link and a restored tree arrives
# without it. Recreating it is enough: the package and OpenClaw's record of it
# both came back with the volume, and reinstalling over them fails anyway --
# OpenClaw rejects a package whose record it already holds.
repair_peer_link() {
  # -d follows the link, so this is false when the peer is missing or dangling.
  [ -n "$1" ] && [ ! -d "$1/node_modules/openclaw" ] || return 0
  mkdir -p "$1/node_modules"
  rm -f "$1/node_modules/openclaw"
  ln -s "$CORE_DIR" "$1/node_modules/openclaw"
  echo "[start] recreated the openclaw peer link for $1"
}

# True when the package and every file it declares OpenClaw should load at runtime exist.
plugin_files_present() {
  [ -f "$1/package.json" ] || return 1
  for entry in $(jq -r '.openclaw // {} | (.runtimeExtensions // []) + [.runtimeSetupEntry // empty] | .[]' "$1/package.json" 2>/dev/null); do
    [ -f "$1/$entry" ] || return 1
  done
}

# An install that stopped partway (or files lost from the volume) leaves OpenClaw's record
# of the plugin without the package behind it. OpenClaw then refuses to start, and its own
# repair commands -- plugins install --force, plugins uninstall, doctor --fix -- all abort
# on that record. Putting the files back with npm, in the project OpenClaw created (whose
# package.json pins the version), satisfies the record; a registry refresh re-indexes it.
# The damaged package directory goes first: npm skips a package whose package.json is
# already in place, however incomplete the rest of it is.
repair_plugin_files() {
  echo "[start] $2 is missing files; reinstalling it into $1"
  rm -rf "${1:?}/node_modules/$2"
  if ! (cd "$1" && npm install --omit=peer --no-audit --no-fund --ignore-scripts >/dev/null 2>&1); then
    echo "[start] $2 repair failed"
    return 0
  fi
  repair_peer_link "$1/node_modules/$2"
  openclaw plugins registry --refresh >/dev/null 2>&1 || echo "[start] plugin registry refresh failed"
}

install_plugin() {
  # OpenClaw names a plugin's npm project after the package: @openclaw/slack -> openclaw-slack-<hash>.
  project="$(ls -d "$PLUGIN_PROJECTS"/openclaw-"${1##*/}"-* 2>/dev/null | head -n 1)"
  if [ -z "$project" ]; then
    # Otherwise find whichever project holds the package.
    found="$(ls -d "$PLUGIN_PROJECTS"/openclaw-*/node_modules/"$1" 2>/dev/null | head -n 1)"
    project="${found%/node_modules/*}"
  fi
  pkg_dir="${project:+$project/node_modules/$1}"
  if [ -n "$project" ] && [ -f "$project/package.json" ] && ! plugin_files_present "$pkg_dir"; then
    repair_plugin_files "$project" "$1"
  fi
  installed="$(cat "$pkg_dir/package.json" 2>/dev/null | jq -r .version | head -n 1)"
  if [ "$installed" = "$OPENCLAW_VERSION" ]; then
    repair_peer_link "$pkg_dir"
    return 0
  fi
  flag=""
  [ -n "$installed" ] && flag="--force"
  openclaw plugins install "$1@$OPENCLAW_VERSION" --accept-capabilities $flag 2>&1 \
    || echo "[start] $1 plugin install failed"
}
