#!/bin/bash
# vendor_sync.sh — sync a vendored extension's source from its upstream repo.
#
# Reads vendor.toml at the repo root. For the named extension, pulls the
# pinned ref's <subdir> via `git clone --depth 1` and merges it into
# extensions/<name>/. Files that exist locally but NOT in the upstream subdir
# are preserved (so a locally-authored blender_manifest.toml or similar
# survives when the upstream doesn't ship one).
#
# Usage:  tools/vendor_sync.sh <extension_id>            # sync one
#         tools/vendor_sync.sh --all                     # sync every entry in vendor.toml
#         tools/vendor_sync.sh <extension_id> --dry-run  # show what would change
# Env:    (none)
# Exit 0 on success; non-zero on parse / fetch / IO error.
set -euo pipefail

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR_TOML="$PROJECT/vendor.toml"
EXT_ROOT="$PROJECT/extensions"

usage() {
  cat >&2 <<EOF
Usage: tools/vendor_sync.sh <extension_id> [--dry-run]
       tools/vendor_sync.sh --all [--dry-run]

Reads vendor.toml at the repo root and syncs the pinned upstream source for the
named extension (or all vendored extensions) into extensions/<name>/.
EOF
  exit 2
}

if [ ! -f "$VENDOR_TOML" ]; then
  echo "ERROR: $VENDOR_TOML not found" >&2
  exit 1
fi

# Prefer a Python that has tomllib in the stdlib (3.11+). Fall back to
# whichever python3 is available and hope for the best (script exits with a
# helpful message if the fallback lacks tomllib).
if command -v python3.13 >/dev/null 2>&1;   then PY=python3.13
elif command -v python3.12 >/dev/null 2>&1; then PY=python3.12
elif command -v python3.11 >/dev/null 2>&1; then PY=python3.11
else PY=python3; fi

DRY_RUN=0
TARGET=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --all)     TARGET="__all__" ;;
    -h|--help) usage ;;
    -*)        echo "unknown flag: $arg" >&2; usage ;;
    *)         if [ -z "$TARGET" ]; then TARGET="$arg"; else echo "too many args" >&2; usage; fi ;;
  esac
done
[ -z "$TARGET" ] && usage

# Parse vendor.toml → TSV (name<TAB>source<TAB>ref<TAB>subdir) via python's tomllib.
TARGETS_TSV="$(mktemp)"
trap 'rm -f "$TARGETS_TSV"' EXIT

"$PY" - "$VENDOR_TOML" "$TARGET" "$TARGETS_TSV" <<'PYEOF'
import sys
try:
    import tomllib
except ImportError:
    print("ERROR: this script requires Python 3.11+ (for tomllib). "
          "Install python 3.12 (e.g. `brew install python@3.12`) or pass "
          "PY=python3.12 as an env var.", file=sys.stderr)
    sys.exit(6)
path, target, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path, "rb") as fh:
    data = tomllib.load(fh)
entries = data if target == "__all__" else {}
if target != "__all__":
    if target not in data:
        print(f"ERROR: extension '{target}' not found in vendor.toml", file=sys.stderr)
        sys.exit(3)
    entries = {target: data[target]}
lines = []
for name, cfg in entries.items():
    for req in ("source", "ref", "subdir"):
        if req not in cfg:
            print(f"ERROR: [{name}] missing required key '{req}'", file=sys.stderr)
            sys.exit(3)
    lines.append("\t".join([name, cfg["source"], cfg["ref"], cfg["subdir"]]))
with open(out_path, "w") as fh:
    fh.write("\n".join(lines) + ("\n" if lines else ""))
PYEOF

while IFS=$'\t' read -r name source ref subdir; do
  [ -z "$name" ] && continue
  ext_dir="$EXT_ROOT/$name"
  echo "==> Syncing $name from $source @ $ref (subdir: $subdir)"

  tmp="$(mktemp -d)"
  # Depth 1 clone at the pinned ref (branch, tag, or SHA that's reachable
  # from a branch — plain SHAs need a slightly different fetch, add later
  # if needed).
  if ! git clone --depth 1 --branch "$ref" --quiet "$source" "$tmp/src" 2>/tmp/vendor_clone_err.$$; then
    echo "ERROR: git clone failed for $name:" >&2
    cat /tmp/vendor_clone_err.$$ >&2
    rm -f /tmp/vendor_clone_err.$$
    rm -rf "$tmp"
    exit 4
  fi
  rm -f /tmp/vendor_clone_err.$$

  src_subdir="$tmp/src/$subdir"
  if [ ! -d "$src_subdir" ]; then
    echo "ERROR: subdir '$subdir' does not exist in $source@$ref" >&2
    rm -rf "$tmp"
    exit 5
  fi
  upstream_sha="$(git -C "$tmp/src" rev-parse HEAD)"
  mkdir -p "$ext_dir"

  if [ "$DRY_RUN" -eq 1 ]; then
    echo "  --dry-run: would rsync $src_subdir/  →  $ext_dir/"
    echo "  diff (upstream vs local, first 20 lines):"
    diff -qr "$src_subdir" "$ext_dir" 2>&1 | sed 's/^/    /' | head -20 || true
  else
    # Merge upstream into local; --delete NOT set, so local-only files (like
    # a blender_manifest.toml authored in this monorepo) are preserved.
    rsync -a "$src_subdir/" "$ext_dir/"
    cat > "$ext_dir/.vendor_last_sync" <<EOF
source: $source
ref: $ref
commit: $upstream_sha
synced_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF
    echo "  ✓ synced @ $upstream_sha"
  fi

  rm -rf "$tmp"
done < "$TARGETS_TSV"

echo ""
if [ "$DRY_RUN" -eq 1 ]; then
  echo "vendor_sync dry-run complete (no changes written)."
else
  echo "vendor_sync complete."
fi
