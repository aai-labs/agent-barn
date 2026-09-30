#!/bin/sh
workspace=/home/node/.openclaw/workspace
state_dir=/home/node/.openclaw
has_legacy_workspace_state() {
  [ -e "$workspace/openclaw-workspace-state.json" ] ||
    [ -e "$workspace/.openclaw/workspace-state.json" ] ||
    find "$state_dir/workspace-attestations" -maxdepth 1 -type f \
      \( -name '*.attested' -o -name '*.attested.doctor-importing' \) -print -quit 2>/dev/null \
      | grep -q . ||
    find "$state_dir" -maxdepth 1 -type f \
      \( -name 'workspace.attested' -o -name 'workspace.attested.doctor-importing' \) -print -quit 2>/dev/null \
      | grep -q .
}
if has_legacy_workspace_state; then
  echo "[start] Migrating legacy OpenClaw workspace state"
  openclaw doctor --fix --non-interactive
fi
