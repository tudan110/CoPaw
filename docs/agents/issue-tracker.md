# Issue tracker: GitHub

Issues and PRDs for this repo live as GitHub issues on `github.com/tudan110/QwenPaw`. Use the `gh` CLI for all operations — it picks up the repo automatically from `git remote -v` when run inside the clone.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.

## Repo-specific notes

- Issue titles follow Conventional Commits style (`<type>(<scope>): <subject>`) — same convention as commits and PR titles.
- Internal-only work that ships on `dev` (Portal / extensions / VEOPS / alarm flows) can still use GitHub issues here, but be careful not to leak internal customer or system names into public issue bodies — sanitize before opening. Upstream-clean work (changes under `src/qwenpaw/` excluding `extensions/`) is fine to describe in full.
- Triage label vocabulary is **not configured** in this repo. If you need triage state, add the labels in GitHub first and re-run `/setup-matt-pocock-skills` — until then, the `triage` skill should fall back to writing state into the issue body instead of applying labels.
