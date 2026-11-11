#!/usr/bin/env bash
# scripts/github_backfill.sh — apply workshop-rules §6.5 to past pull requests:
# retitle, add the header line, label (kind + Mark), tag the merge commit, create the GitHub Release.
# Practice run by default; pass --apply to make changes. Safe to re-run (skips what already exists).
# Input: docs/github-backfill.tsv  (number, version, title, mark, kind, prerelease — tab-separated)
# R6.1 decision 4: the Release is created with target_commitish (which also creates its tag), because
# some environments refuse POST git/refs; a refused write is reported, never retried in a loop.
set -euo pipefail

REPO="${REPO:-Shark2558/jarvis-web}"
MAP="${MAP:-docs/github-backfill.tsv}"
APPLY="${1:-}"

run() {
  if [[ "$APPLY" == "--apply" ]]; then "$@" >/dev/null; else printf 'DRY:'; printf ' %q' "$@"; printf '\n'; fi
}

ensure_label() {  # name colour
  if ! gh api "repos/$REPO/labels/$(jq -rn --arg s "$1" '$s|@uri')" >/dev/null 2>&1; then
    run gh api -X POST "repos/$REPO/labels" -f name="$1" -f color="$2"
  fi
}

[[ -f "$MAP" ]] || { echo "missing $MAP" >&2; exit 2; }
for kind in release hotfix docs; do ensure_label "$kind" 1A4C9C; done

fail=0
while IFS=$'\t' read -r num ver title mark kind pre <&3; do
  [[ -z "$num" || "$num" == \#* ]] && continue
  if ! pr=$(gh api "repos/$REPO/pulls/$num"); then echo "PR #$num: not readable" >&2; fail=1; continue; fi
  if [[ "$(jq -r .merged_at <<<"$pr")" == "null" ]]; then echo "PR #$num: not merged, skipped" >&2; continue; fi
  sha=$(jq -r .merge_commit_sha <<<"$pr")
  body=$(jq -r '.body // ""' <<<"$pr")

  # 1. title + header line (the original description stays below a rule)
  if [[ "$body" == *"**Version:**"* ]]; then
    run gh api -X PATCH "repos/$REPO/pulls/$num" -f title="$title"
  else
    header="**Version:** $ver · **Built in:** Mark $mark · **Tag:** $ver"
    run gh api -X PATCH "repos/$REPO/pulls/$num" -f title="$title" -f body="$header"$'\n\n---\n\n'"$body"
  fi

  # 2. labels: kind + every Mark named (e.g. "VII-VIII" → Mark VII, Mark VIII)
  labels=(-f "labels[]=$kind")
  IFS='-' read -ra marks <<<"$mark"
  for m in "${marks[@]}"; do ensure_label "Mark $m" 0C2D66; labels+=(-f "labels[]=Mark $m"); done
  run gh api -X POST "repos/$REPO/issues/$num/labels" "${labels[@]}"

  # 3 + 4. GitHub Release on the merge commit (creates the tag too)
  if ! gh api "repos/$REPO/releases/tags/$ver" >/dev/null 2>&1; then
    notes="$title"$'\n\n'"Pull request #$num. Built in Mark $mark. What you get, checks and cost are in the pull request."
    if ! run gh api -X POST "repos/$REPO/releases" -f tag_name="$ver" -f target_commitish="$sha" \
        -f name="$title" -F prerelease="$pre" -f body="$notes"; then
      echo "PR #$num: GitHub refused the release $ver — create it on the website (tag $ver on $sha)" >&2
      fail=1
    fi
  fi
  echo "PR #$num → $title"
done 3< "$MAP"
exit "$fail"
