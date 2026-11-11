#!/usr/bin/env bash
# scripts/github_backfill.sh — apply workshop-rules §6.5 to past pull requests:
# retitle, add the header line, label (kind + Mark), tag the merge commit, create the GitHub Release.
# Practice run by default; pass --apply to make changes. Safe to re-run (skips what already exists).
# The first line names the repository. With REPO set to another repository, --apply needs that
# name repeated (`--apply owner/name`), so a stray REPO in the shell can never write elsewhere.
# Input: docs/github-backfill.tsv  (number, version, title, mark, kind, prerelease — tab-separated)
# R6.1 decision 4: the Release is created with target_commitish (which also creates its tag), because
# some environments refuse POST git/refs. Every write GitHub refuses (a label, a retitle, the labels,
# a Release) is reported with what to do by hand on the website and never tried again; the run goes
# on to the next change and exits 1 at the end.
set -euo pipefail

HOME_REPO="Shark2558/jarvis-web"
REPO="${REPO:-$HOME_REPO}"
MAP="${MAP:-docs/github-backfill.tsv}"
APPLY="${1:-}"
CONFIRM="${2:-}"

if [[ "$APPLY" == "--apply" ]]; then
  if [[ "$REPO" != "$HOME_REPO" && "$CONFIRM" != "$REPO" ]]; then
    echo "REPO is $REPO, not $HOME_REPO: to write there, run: $0 --apply $REPO" >&2
    exit 2
  fi
  echo "Applying to $REPO from $MAP"
else
  echo "Practice run for $REPO from $MAP (nothing changes; --apply makes the changes)"
fi

run() {
  if [[ "$APPLY" == "--apply" ]]; then "$@" >/dev/null; else printf 'DRY:'; printf ' %q' "$@"; printf '\n'; fi
}

fail=0
# A write GitHub refuses: say what to do by hand, never try it again, go on, exit 1 at the end.
write() {  # what to do by hand, then the call
  local by_hand="$1"; shift
  if ! run "$@"; then echo "$by_hand" >&2; fail=1; fi
}

KINDS=(release hotfix docs)
MARK_RE='^[IVXLC]+(-[IVXLC]+)*$'  # one Mark, or several joined by "-" (VII-VIII)
is_kind() { local k; for k in "${KINDS[@]}"; do [[ "$1" == "$k" ]] && return 0; done; return 1; }
valid_row() {  # num ver mark kind pre: a PR number, v<major>.<minor>.<patch>, Marks, kind, true|false
  [[ "$1" =~ ^[0-9]+$ && "$2" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ && "$3" =~ $MARK_RE ]] &&
    is_kind "$4" && [[ "$5" == true || "$5" == false ]]
}

asked=$'\n'  # the labels this run has already made sure of (or tried to): never asked for twice
ensure_label() {  # name colour
  [[ "$asked" == *$'\n'"$1"$'\n'* ]] && return 0
  asked+="$1"$'\n'
  if ! gh api "repos/$REPO/labels/$(jq -rn --arg s "$1" '$s|@uri')" >/dev/null 2>&1; then
    write "Label \"$1\": GitHub refused it; create it by hand on the GitHub website (colour #$2)" \
      gh api -X POST "repos/$REPO/labels" -f name="$1" -f color="$2"
  fi
}

[[ -f "$MAP" ]] || { echo "missing $MAP" >&2; exit 2; }
for kind in "${KINDS[@]}"; do ensure_label "$kind" 1A4C9C; done

while IFS=$'\t' read -r num ver title mark kind pre <&3; do
  [[ -z "$num" || "$num" == \#* ]] && continue
  # -F reads a value starting with @ as a file: only true|false ever reaches it
  if ! valid_row "$num" "$ver" "$mark" "$kind" "$pre"; then
    echo "PR #$num: malformed row, skipped" >&2; fail=1; continue
  fi
  if ! pr=$(gh api "repos/$REPO/pulls/$num"); then echo "PR #$num: not readable" >&2; fail=1; continue; fi
  if [[ "$(jq -r .merged_at <<<"$pr")" == "null" ]]; then echo "PR #$num: not merged, skipped" >&2; continue; fi
  sha=$(jq -r '.merge_commit_sha // ""' <<<"$pr")
  if ! [[ "$sha" =~ ^[0-9a-f]{40}$ ]]; then echo "PR #$num: GitHub gave no merge commit, skipped" >&2; fail=1; continue; fi
  body=$(jq -r '.body // ""' <<<"$pr")

  # 1. title + header line (the original description stays below a rule)
  if [[ "$body" == *"**Version:**"* ]]; then
    write "PR #$num: GitHub refused the title; set it by hand on the GitHub website: $title" \
      gh api -X PATCH "repos/$REPO/pulls/$num" -f title="$title"
  else
    header="**Version:** $ver · **Built in:** Mark $mark · **Tag:** $ver"
    write "PR #$num: GitHub refused the title and header line; set them by hand on the GitHub website (title: $title)" \
      gh api -X PATCH "repos/$REPO/pulls/$num" -f title="$title" -f body="$header"$'\n\n---\n\n'"$body"
  fi

  # 2. labels: kind + every Mark named (e.g. "VII-VIII" → Mark VII, Mark VIII)
  labels=(-f "labels[]=$kind") names="$kind"
  IFS='-' read -ra marks <<<"$mark"
  for m in "${marks[@]}"; do
    ensure_label "Mark $m" 0C2D66; labels+=(-f "labels[]=Mark $m"); names+=", Mark $m"
  done
  write "PR #$num: GitHub refused the labels; add them by hand on the GitHub website: $names" \
    gh api -X POST "repos/$REPO/issues/$num/labels" "${labels[@]}"

  # 3 + 4. GitHub Release on the merge commit (creates the tag too)
  if ! gh api "repos/$REPO/releases/tags/$ver" >/dev/null 2>&1; then
    notes="$title"$'\n\n'"Pull request #$num. Built in Mark $mark. What you get, checks and cost are in the pull request."
    write "PR #$num: GitHub refused the release $ver; create it by hand on the GitHub website (tag $ver on $sha)" \
      gh api -X POST "repos/$REPO/releases" -f tag_name="$ver" -f target_commitish="$sha" \
      -f name="$title" -F prerelease="$pre" -f body="$notes"
  fi
  echo "PR #$num → $title"
done 3< "$MAP"
exit "$fail"
