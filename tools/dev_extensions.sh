#!/bin/bash
# Audit or install the active No3d Dev extension set as editable symlinks.
# Unknown and third-party add-ons are never touched. Conflicts are moved to a
# timestamped backup directory before links are created.
set -euo pipefail

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
MODE="${1:-audit}"
BLENDER_VERSION="${BLENDER_VERSION:-5.2}"
TARGET_ROOT="$HOME/Library/Application Support/Blender/$BLENDER_VERSION/extensions/user_default"

ACTIVE_EXTENSIONS=(
  agent_bridge
  no3d_asset_developer
  no3d_cad_wip
  no3d_camera_utilities
  no3d_save_reload
  send_nodes
)

# Only these known retired/duplicate NO3D-owned installs may be backed up.
RETIRED_PATHS=(
  "$HOME/Library/Application Support/Blender/$BLENDER_VERSION/extensions/user_default/claude_pair"
  "$HOME/Library/Application Support/Blender/$BLENDER_VERSION/extensions/user_default/save_and_reload"
  "$HOME/Library/Application Support/Blender/$BLENDER_VERSION/scripts/addons/no3d_asset_developer"
  "$HOME/Library/Application Support/Blender/$BLENDER_VERSION/scripts/addons/claude_pair"
  "$HOME/Library/Application Support/Blender/$BLENDER_VERSION/scripts/addons/save_and_reload"
  "$HOME/Library/Application Support/Blender/$BLENDER_VERSION/scripts/addons/NO3D Tools - Camera Render Utiltities"
)

usage() {
  echo "Usage: tools/dev_extensions.sh [audit|link]" >&2
  echo "Set BLENDER_VERSION to target another profile (default: 5.2)." >&2
  exit 2
}

manifest_version() {
  sed -n 's/^version = "\([^"]*\)".*/\1/p' "$1/blender_manifest.toml" | head -1
}

audit() {
  echo "No3d Dev editable extension audit"
  echo "Source: $PROJECT/extensions"
  echo "Target: $TARGET_ROOT"
  local problems=0
  for name in "${ACTIVE_EXTENSIONS[@]}"; do
    local source="$PROJECT/extensions/$name"
    local target="$TARGET_ROOT/$name"
    if [ ! -f "$source/blender_manifest.toml" ]; then
      echo "MISSING_SOURCE  $name"
      problems=$((problems + 1))
      continue
    fi
    local version
    version="$(manifest_version "$source")"
    if [ -L "$target" ] && [ "$(readlink "$target")" = "$source" ]; then
      echo "LINKED          $name  $version"
    elif [ -e "$target" ] || [ -L "$target" ]; then
      echo "CONFLICT        $name  expected=$source  target=$target"
      problems=$((problems + 1))
    else
      echo "NOT_LINKED      $name  $version"
      problems=$((problems + 1))
    fi
  done
  for path in "${RETIRED_PATHS[@]}"; do
    if [ -e "$path" ] || [ -L "$path" ]; then
      echo "RETIRED_PRESENT $path"
      problems=$((problems + 1))
    fi
  done
  echo "Audit issues: $problems"
  return 0
}

link_extensions() {
  if pgrep -f "/Applications/Blender( $BLENDER_VERSION)?\.app/Contents/MacOS/Blender" >/dev/null 2>&1; then
    echo "ERROR: Blender appears to be running. Close it before replacing extension paths." >&2
    exit 3
  fi

  local stamp backup_root
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  backup_root="$HOME/Library/Application Support/Blender/$BLENDER_VERSION/extensions.bak-no3d-dev-$stamp"
  mkdir -p "$TARGET_ROOT" "$backup_root"

  for name in "${ACTIVE_EXTENSIONS[@]}"; do
    local source="$PROJECT/extensions/$name"
    local target="$TARGET_ROOT/$name"
    if [ ! -f "$source/blender_manifest.toml" ]; then
      echo "ERROR: active extension source is incomplete: $source" >&2
      exit 4
    fi
    if [ -L "$target" ] && [ "$(readlink "$target")" = "$source" ]; then
      continue
    fi
    if [ -e "$target" ] || [ -L "$target" ]; then
      mv "$target" "$backup_root/${name}-replaced"
    fi
    ln -s "$source" "$target"
    echo "LINKED $name -> $source"
  done

  for path in "${RETIRED_PATHS[@]}"; do
    if [ -e "$path" ] || [ -L "$path" ]; then
      local label
      label="$(basename "$path")-retired"
      if [ -e "$backup_root/$label" ] || [ -L "$backup_root/$label" ]; then
        label="$(basename "$(dirname "$path")")-$(basename "$path")-retired"
      fi
      mv "$path" "$backup_root/$label"
      echo "BACKED_UP retired install: $path"
    fi
  done

  echo "Backup: $backup_root"
  echo "Restart Blender, enable the linked extensions once, and save preferences."
  audit
}

case "$MODE" in
  audit) audit ;;
  link) link_extensions ;;
  *) usage ;;
esac
