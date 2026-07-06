#!/bin/bash
# publish_repo.sh — build the extension zip, generate the static repo
# listing, and publish it to the gh-pages branch (served by GitHub Pages).
#
# Result: https://node-dojo.github.io/no3d-asset-developer/index.json
# Users with that repo registered get native in-Blender updates.
#
# Usage:  tools/publish_repo.sh
# Requires: Blender 5.2 CLI, git (authed for node-dojo), run from anywhere.

set -euo pipefail

BLENDER="/Applications/Blender 5.2 Beta.app/Contents/MacOS/Blender"
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
REPO_DIR="$HOME/.no3d-extension-repo"     # scratch, outside Dropbox
DIST="$PROJECT/dist"

VERSION=$(grep '^version' "$PROJECT/blender_manifest.toml" | head -1 | cut -d'"' -f2)
ZIP_NAME="no3d_asset_developer-$VERSION.zip"

echo "==> Building $ZIP_NAME"
mkdir -p "$DIST"
"$BLENDER" --factory-startup --command extension build \
  --source-dir "$PROJECT" --output-filepath "$DIST/$ZIP_NAME"

echo "==> Assembling repo dir at $REPO_DIR"
mkdir -p "$REPO_DIR"
# Keep prior zips so older Blender versions can still resolve a compatible
# build; same-version zip is replaced.
cp -f "$DIST/$ZIP_NAME" "$REPO_DIR/"

echo "==> Generating index.json (+ html listing)"
"$BLENDER" --factory-startup --command extension server-generate \
  --repo-dir "$REPO_DIR" --html

echo "==> Publishing to gh-pages"
cd "$REPO_DIR"
if [ ! -d .git ]; then
  git init -b gh-pages
  git remote add origin https://github.com/node-dojo/no3d-asset-developer.git
fi
touch .nojekyll
git add -A
git commit -m "repo: publish $ZIP_NAME" || echo "(nothing to commit)"
git push -f origin gh-pages

echo ""
echo "Done. Repo URL:"
echo "  https://node-dojo.github.io/no3d-asset-developer/index.json"
