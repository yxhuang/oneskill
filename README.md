# oneskill

[![CI](https://github.com/yxhuang/oneskill/actions/workflows/ci.yml/badge.svg)](https://github.com/yxhuang/oneskill/actions/workflows/ci.yml)

**One skill library. Every AI coding CLI.**

Claude Code, Codex CLI, and Kimi CLI can all load *skills* — folders containing a `SKILL.md`
that teach the agent how to do something specific. The problem: each client reads from its own
directory. Write a good skill once and you end up copying it three times, then watching the
copies quietly drift apart until you can't remember which one you actually fixed.

`oneskill` keeps one canonical copy of every skill and symlinks it into every client. A single
command shows you what's shared, what's client-specific, and what's broken.

<p align="center">
  <img src="docs/demo.svg" width="720"
       alt="osk list output: a coverage matrix grouping skills into SHARED across all three clients, CLIENT-SPECIFIC, and NEEDS ATTENTION — where one skill shows a real directory shadowing its symlink on Claude.">
</p>

That last row is the whole point. A client upgrade replaced a symlink with a real directory,
so Claude is now running a private copy that no longer tracks the library. You'd never notice
by eye. `osk doctor` tells you exactly how to fix it.

## Why this happens

Symlink farms rot. Three things break them, over and over:

- **Client upgrades** overwrite symlinks with real files, silently forking your config.
- **New skills** get created in whichever client you happened to be using, and stay there.
- **Uninstalls** leave dangling links pointing at directories that no longer exist.

None of this surfaces as an error. Your agent just quietly stops seeing the skill you wrote,
or sees a stale copy of it.

## Install

Install or update with one command:

```bash
curl -fsSL https://raw.githubusercontent.com/yxhuang/oneskill/main/install.sh | sh
```

This installs the repository to `~/.local/share/oneskill` and links `osk` into
`~/.local/bin`. To install manually instead:

```bash
git clone https://github.com/yxhuang/oneskill.git ~/.local/share/oneskill
mkdir -p ~/.local/bin
ln -sfn ~/.local/share/oneskill/bin/osk ~/.local/bin/osk
```

Then initialize your skill library:

```bash
osk init          # pick where your skill library lives
osk scan --write  # build a manifest from what's already installed
osk list
```

Requires Python 3.9+. No dependencies, no build step — it's a single file.

### Contributing / self-hosting

If you fork this and push your own manifest around, enable the guard hook so your
machine-local paths never leak into a commit:

```bash
git config core.hooksPath .githooks
```

It blocks committing `skills.json` (machine-local, regenerable via `osk scan --write`)
and any absolute `/home/<user>` path in staged content.

## Commands

| Command | What it does |
|---|---|
| `osk list` | Coverage matrix across all clients. Add `--json` for machine output. |
| `osk doctor` | Find drift: broken links, real directories shadowing links, manifest mismatches. Read-only — it prints fix commands, it never runs them. |
| `osk adopt <path>` | Take a skill that exists in one client and share it with the rest. |
| `osk sync` | Reconcile reality against the manifest. Idempotent — a second run is always a no-op. |
| `osk scan --write` | Generate a manifest draft from your current setup. |
| `osk init` | First-time configuration. |

## How it works

One directory holds every skill body. Each client's skills directory gets symlinks pointing
into it. A manifest records what *should* exist, so drift becomes a diff rather than a guess.

```
  ~/skill-library/pdf-editing/SKILL.md   ← the only real copy
        ↑              ↑            ↑
  ~/.claude/     ~/.codex/    ~/.kimi-code/
    skills/        skills/       skills/
```

`adopt` is the inverse of the problem: point it at a skill living inside one client, and it
moves the body into the library, replaces the original with a symlink, and links it into the
others.

## It never deletes anything

Managing symlink farms means moving real directories around, so `oneskill` is built to be
un-scary:

- **Every destructive step asks first**, one at a time, showing the exact paths involved.
- **Conflicts are renamed, never removed.** Anything in the way becomes
  `<name>.oneskill-backup-<timestamp>`. There is no `rmtree` anywhere in the codebase.
- **`--dry-run` on `adopt` and `sync`** prints the full plan and changes nothing.
- **Failed operations roll back** — a half-finished `adopt` restores what it moved.
- **`list` and `doctor` are strictly read-only**, safe to run anywhere, any time.

The design rule is that a bad day should cost you a rename, never a file.

## Supported clients

Claude Code (`~/.claude/skills`), Codex CLI (`~/.codex/skills`), and Kimi CLI
(`~/.kimi-code/skills`) — they share the same `SKILL.md` format, which is what makes this
possible at all.

Claude Code *plugin* skills are deliberately not shared: they live in versioned cache paths
that break on every plugin update, and their content is bound to Claude-specific tooling.
`oneskill` reports them as `claude-only` rather than pretending otherwise.

Adding another client is a few lines — client paths are declared in one place near the top of
`bin/osk`.

## Status

v1, and honest about it: this scratches a real itch on the author's machine and the safety
properties are covered by tests, but it has run on exactly one setup so far. Bug reports from
a second machine would be genuinely useful.

```bash
python3 -m unittest discover -s tests
```

Roadmap — a GUI over `osk list --json`, and support for more clients. The JSON output is
stable enough to build against today.

## License

MIT
