#!/usr/bin/env bash
# Container clean-checkout reproduction of docs/independent_reproduction.md.
#
# OPERATOR DISCLOSURE: this run was performed by the project maintainer's AI
# agent inside an isolated Linux container. It is NOT an independent
# third-party reproduction: the reviewer boundary in the protocol requires a
# person other than the primary implementation operator.

OUT=/repro
STATUS="$OUT/status.txt"
CHECKOUT_TAG="${CHECKOUT_TAG:-v0.7.0}"
mkdir -p "$OUT"
exec > >(tee "$OUT/full.log") 2>&1

record() {
  desc="$1"
  shift
  echo ""
  echo "==============================================================="
  echo "RUN: $desc"
  "$@"
  rc=$?
  echo "EXIT: $desc -> $rc"
  echo "$desc|$rc" >> "$STATUS"
}

echo "ENVIRONMENT"
date -u +"%Y-%m-%dT%H:%M:%SZ"
head -2 /etc/os-release
uname -sm
python --version
free -h 2>/dev/null | head -2 || true

: > "$STATUS"

record "apt-get update" apt-get update -qq
record "apt-get install git ca-certificates" \
  apt-get install -y -qq git ca-certificates
record "pip install uv" pip install -q uv
record "uv --version" uv --version
record "clone public repository" \
  git clone https://github.com/ariakage/protein-split-audit /work
cd /work || exit 97
record "checkout frozen tag $CHECKOUT_TAG" git checkout -q "$CHECKOUT_TAG"

echo ""
echo "REVIEWED STATE"
git rev-parse HEAD
git log -1 --format='%H %cI %s'
shasum -a 256 uv.lock || sha256sum uv.lock

record "git status --porcelain (initial)" git status --porcelain
record "git rev-parse HEAD" git rev-parse HEAD
record "shasum uv.lock" sha256sum uv.lock
record "uv lock --check" uv lock --check
record "uv sync --locked --group dev ${SYNC_EXTRA:-}" \
  uv sync --locked --group dev ${SYNC_EXTRA:-}
record "uv run --locked ruff check ." uv run --locked ruff check .
record "uv run --locked ruff format --check ." \
  uv run --locked ruff format --check .
record "uv run --locked mypy src" uv run --locked mypy src
record "uv run --locked pytest" uv run --locked pytest
record "uv build --clear" uv build --clear
record "demo run external-demo-a" \
  uv run --locked psaudit demo run --output-dir results/runs/external-demo-a
record "demo run external-demo-b" \
  uv run --locked psaudit demo run --output-dir results/runs/external-demo-b
record "diff two demo runs" \
  diff -ru --exclude=.psaudit-publication.lock \
    results/runs/external-demo-a results/runs/external-demo-b
record "sha256 demo files" \
  sha256sum \
    results/runs/external-demo-a/README.md \
    results/runs/external-demo-a/split_summary.csv \
    results/runs/external-demo-a/demo_manifest.json
record "git status --porcelain (final)" git status --porcelain

echo ""
echo "STATUS SUMMARY (command|exit)"
cat "$STATUS"
failed=$(grep -v '|0$' "$STATUS" || true)
if [ -n "$failed" ]; then
  echo "OVERALL: FAIL"
  exit 1
fi
echo "OVERALL: PASS"
