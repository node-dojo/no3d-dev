#!/bin/bash
# ship.sh — deterministic ship pipeline for ONE target extension in the No3d
# Dev monorepo. Handles bump → build → prune old zips → publish → git commit +
# tag + push → vault ship-log append.
#
# For vendored extensions (those with a vendor.toml entry), --sync-vendor pulls
# the pinned upstream ref into the local tree before shipping — use this after
# bumping the version in the standalone repo. Without --sync-vendor, ship.sh
# ships whatever is currently in extensions/<name>/.
#
# Signature:
#   tools/ship.sh <extension_id> <version> [--notes "..."] [--sync-vendor] [--dry-run]
#
# Env:
#   BLENDER   — path to Blender binary (default: 5.2 Beta.app)
#   VAULT_001 — path to the vault; if set, ship-log entry is appended to
#               $VAULT_001/PROJECTS/no3d tools/ship-log.md
#
# Exit 0 on success; non-zero on any preflight/build/publish failure.
set -euo pipefail

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
BLENDER="${BLENDER:-/Applications/Blender 5.2 Beta.app/Contents/MacOS/Blender}"
EXT_ROOT="$PROJECT/extensions"
DIST="$PROJECT/dist"
REPO_DIR="$HOME/.no3d-extension-repo"

if command -v python3.13 >/dev/null 2>&1;   then PY=python3.13
elif command -v python3.12 >/dev/null 2>&1; then PY=python3.12
elif command -v python3.11 >/dev/null 2>&1; then PY=python3.11
else PY=python3; fi

usage() {
  cat >&2 <<EOF
Usage: tools/ship.sh <extension_id> <version> [options]

Options:
  --notes "..."      Ship-log entry text (goes to \$VAULT_001 log if set).
  --sync-vendor      For vendored extensions: run tools/vendor_sync.sh first.
                     Ignored for authored-in-place extensions.
  --dry-run          Print the plan without touching git, gh-pages, or the log.

Ships ONE extension. All other extensions in the repo are also rebuilt (they
share the aggregated index.json), but their versions are unchanged.
EOF
  exit 2
}

TARGET=""
VERSION=""
NOTES=""
SYNC_VENDOR=0
DRY_RUN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --notes)       NOTES="${2:-}"; shift 2 ;;
    --sync-vendor) SYNC_VENDOR=1; shift ;;
    --dry-run)     DRY_RUN=1; shift ;;
    -h|--help)     usage ;;
    -*)            echo "unknown flag: $1" >&2; usage ;;
    *)             if [ -z "$TARGET" ]; then TARGET="$1"
                   elif [ -z "$VERSION" ]; then VERSION="$1"
                   else echo "too many args" >&2; usage
                   fi; shift ;;
  esac
done
[ -z "$TARGET" ] || [ -z "$VERSION" ] && usage

EXT_DIR="$EXT_ROOT/$TARGET"
if [ ! -d "$EXT_DIR" ]; then
  echo "ERROR: extension '$TARGET' not found at $EXT_DIR" >&2
  exit 3
fi

log() { echo "==> $*"; }
run() {
  if [ "$DRY_RUN" -eq 1 ]; then echo "  [dry-run] $*"
  else eval "$@"
  fi
}

# ------------------------------------------------------------ preflight
log "Preflight"

# Working tree clean?
if [ "$DRY_RUN" -eq 0 ] && [ -n "$(cd "$PROJECT" && git status --porcelain)" ]; then
  echo "ERROR: working tree not clean. Commit or stash changes first." >&2
  cd "$PROJECT" && git status --short | head -10 >&2
  exit 4
fi

# On main?
BRANCH="$(cd "$PROJECT" && git branch --show-current)"
if [ "$BRANCH" != "main" ]; then
  echo "ERROR: not on main branch (currently on '$BRANCH')" >&2
  exit 5
fi

# Is TARGET vendored?
IS_VENDORED=0
if [ -f "$PROJECT/vendor.toml" ]; then
  if "$PY" -c "
import sys, tomllib
with open('$PROJECT/vendor.toml', 'rb') as f: d = tomllib.load(f)
sys.exit(0 if '$TARGET' in d else 1)
" 2>/dev/null; then
    IS_VENDORED=1
    log "  $TARGET is vendored (vendor.toml entry present)"
  fi
fi

# For vendored + --sync-vendor: pull upstream first (before the version-agreement
# check so bumps that came in from upstream get picked up).
if [ "$IS_VENDORED" -eq 1 ] && [ "$SYNC_VENDOR" -eq 1 ]; then
  log "Vendor sync (upstream → local before bump)"
  run "$PROJECT/tools/vendor_sync.sh $TARGET"
elif [ "$SYNC_VENDOR" -eq 1 ]; then
  echo "  --sync-vendor ignored: $TARGET is authored-in-place (no vendor.toml entry)"
fi

# Register harness must pass for every extension, not just this one.
log "Register-check (all extensions)"
if [ "$DRY_RUN" -eq 0 ]; then
  BLENDER="$BLENDER" "$PROJECT/tools/check_register.sh" > /tmp/ship_check.$$ 2>&1
  if ! grep -q "^REGISTER_OK$" /tmp/ship_check.$$; then
    echo "ERROR: check_register.sh did not pass. Last output:" >&2
    tail -20 /tmp/ship_check.$$ >&2
    rm -f /tmp/ship_check.$$
    exit 6
  fi
  rm -f /tmp/ship_check.$$
  echo "  ✓ REGISTER_OK"
else
  echo "  [dry-run] would run tools/check_register.sh"
fi

# ------------------------------------------------------------ bump
log "Bump $TARGET to $VERSION"

MANIFEST="$EXT_DIR/blender_manifest.toml"
INIT="$EXT_DIR/__init__.py"

CURRENT_MANIFEST_VERSION="$(grep '^version' "$MANIFEST" | head -1 | cut -d'"' -f2 || true)"
if [ -z "$CURRENT_MANIFEST_VERSION" ]; then
  echo "ERROR: could not parse current version from $MANIFEST" >&2
  exit 7
fi
echo "  manifest: $CURRENT_MANIFEST_VERSION → $VERSION"

# Parse "X.Y.Z" into tuple form (X, Y, Z) for bl_info.
VERSION_TUPLE="($(echo "$VERSION" | tr '.' ',' | sed 's/,/, /g'))"
CURRENT_BL_INFO="$(grep -E '^\s*"version"\s*:' "$INIT" | head -1 | sed -E 's/.*\(([^)]+)\).*/(\1)/' || true)"
if [ -n "$CURRENT_BL_INFO" ]; then
  echo "  bl_info:  $CURRENT_BL_INFO → $VERSION_TUPLE"
fi

if [ "$DRY_RUN" -eq 0 ]; then
  # Manifest
  sed -i "" "s/^version = .*/version = \"$VERSION\"/" "$MANIFEST"
  # bl_info in __init__.py — only rewrite if the pattern is present.
  if [ -n "$CURRENT_BL_INFO" ]; then
    "$PY" - "$INIT" "$VERSION" <<'PYEOF'
import re, sys
path, version = sys.argv[1], sys.argv[2]
tup = "(" + ", ".join(version.split(".")) + ")"
src = open(path).read()
new = re.sub(r'("version"\s*:\s*)\([^)]+\)', rf'\1{tup}', src, count=1)
if new != src:
    open(path, "w").write(new)
PYEOF
  fi
fi

# Sanity: post-bump agreement (skip on dry-run since files not touched).
if [ "$DRY_RUN" -eq 0 ]; then
  M="$(grep '^version' "$MANIFEST" | head -1 | cut -d'"' -f2)"
  if [ "$M" != "$VERSION" ]; then
    echo "ERROR: manifest version bump verification failed (still '$M')" >&2
    exit 8
  fi
fi

# ------------------------------------------------------------ build
log "Build all extensions"
run "$PROJECT/tools/build_all.sh"

# ------------------------------------------------------------ prune
log "Prune old zips (keep only current version per extension)"

prune_dir() {
  local dir="$1"
  [ -d "$dir" ] || return 0
  # For each unique extension id in the dir, keep only the newest-version zip.
  local ids
  ids=$(ls "$dir"/*.zip 2>/dev/null | xargs -n1 basename 2>/dev/null | \
        sed -E 's/-[0-9]+\.[0-9]+\.[0-9]+\.zip$//' | sort -u || true)
  for id in $ids; do
    # Read manifest version straight from the source tree — this is the version
    # we just bumped/kept, and is the authoritative "current" for this ship.
    local src_manifest="$EXT_ROOT/$id/blender_manifest.toml"
    if [ ! -f "$src_manifest" ]; then
      # Orphan zips (extension no longer in the tree) → remove them all.
      for f in "$dir/$id-"*.zip; do
        [ -e "$f" ] || continue
        run "rm -f '$f'"
        echo "  pruned orphan: $(basename "$f")"
      done
      continue
    fi
    local current
    current="$(grep '^version' "$src_manifest" | head -1 | cut -d'"' -f2)"
    for f in "$dir/$id-"*.zip; do
      [ -e "$f" ] || continue
      if [ "$(basename "$f")" != "$id-$current.zip" ]; then
        run "rm -f '$f'"
        echo "  pruned:  $(basename "$f")"
      else
        echo "  kept:    $(basename "$f")"
      fi
    done
  done
}

prune_dir "$DIST"
prune_dir "$REPO_DIR"

# ------------------------------------------------------------ publish
log "Publish (gh-pages)"
run "$PROJECT/tools/publish_repo.sh"

# ------------------------------------------------------------ git commit + tag
log "Commit + tag"
COMMIT_MSG="ship: $TARGET $VERSION"
if [ -n "$NOTES" ]; then
  COMMIT_MSG="$COMMIT_MSG

$NOTES"
fi

if [ "$DRY_RUN" -eq 0 ]; then
  cd "$PROJECT"
  if [ -n "$(git status --porcelain "$EXT_DIR")" ]; then
    git add "$EXT_DIR/blender_manifest.toml" "$EXT_DIR/__init__.py" 2>/dev/null || true
    # Include vendor sentinel if it changed
    [ -f "$EXT_DIR/.vendor_last_sync" ] && git add "$EXT_DIR/.vendor_last_sync"
    git commit -m "$COMMIT_MSG" 2>&1 | tail -3
  else
    echo "  (no version-related changes to commit)"
  fi
  TAG="$TARGET-v$VERSION"
  if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "  tag $TAG already exists — skipping"
  else
    git tag -a "$TAG" -m "$TARGET $VERSION"
    echo "  tagged $TAG"
  fi
  git push origin main --tags 2>&1 | tail -3
else
  echo "  [dry-run] would commit + tag as $TARGET-v$VERSION and push"
fi

# ------------------------------------------------------------ ship-log
if [ -n "${VAULT_001:-}" ]; then
  LOG_PATH="$VAULT_001/PROJECTS/no3d tools/ship-log.md"
  log "Ship-log append → $LOG_PATH"
  if [ "$DRY_RUN" -eq 0 ]; then
    mkdir -p "$(dirname "$LOG_PATH")"
    SHA="$(cd "$PROJECT" && git rev-parse HEAD)"
    {
      echo ""
      echo "## $(date -u +%Y-%m-%d) — $TARGET $VERSION"
      echo ""
      echo "- Tag: \`$TARGET-v$VERSION\`"
      echo "- Commit: \`$SHA\`"
      echo "- Repo index: https://node-dojo.github.io/no3d-dev/index.json"
      if [ -n "$NOTES" ]; then
        echo ""
        echo "$NOTES"
      fi
    } >> "$LOG_PATH"
  else
    echo "  [dry-run] would append ship entry"
  fi
else
  echo "  (\$VAULT_001 not set — skipping ship-log)"
fi

echo ""
echo "✓ Shipped $TARGET $VERSION"
echo "  https://node-dojo.github.io/no3d-dev/index.json"
