# oneskill

[![CI](https://github.com/yxhuang/oneskill/actions/workflows/ci.yml/badge.svg)](https://github.com/yxhuang/oneskill/actions/workflows/ci.yml)

**One skill library. Every AI coding CLI.**

English | [简体中文](docs/README.zh-CN.md)

Claude Code, Codex CLI, and Kimi CLI all load *skills* — folders with a `SKILL.md` that
teach your agent how to do something. They even share the same format. But each client
reads its own directory, so every good skill ends up copied three times — and the copies
quietly drift apart until you can't remember which one you actually fixed.

`oneskill` keeps **one canonical copy** of every skill and symlinks it into every client.
One command shows you what's shared, what's client-specific, and what's silently broken.

<p align="center">
  <img src="docs/demo.svg" width="720"
       alt="osk list output: a coverage matrix grouping skills into SHARED across all three clients, CLIENT-SPECIFIC, and NEEDS ATTENTION — where one skill shows a real directory shadowing its symlink on Claude.">
</p>

That amber row is the whole point. A client upgrade replaced a symlink with a real
directory, so Claude is now running a private copy that no longer tracks the library.
You'd never notice by eye. `osk doctor` prints the exact fix.

## Why this exists

Symlink farms rot, and nothing tells you:

- **Client upgrades** overwrite symlinks with real files, silently forking your config.
- **New skills** get created in whichever client you happened to be using, and stay there.
- **Uninstalls** leave dangling links pointing at nothing.

None of it surfaces as an error. Your agent just quietly stops seeing the skill you
wrote — or keeps using a stale copy of it.

## Quick start

```bash
curl -fsSL https://raw.githubusercontent.com/yxhuang/oneskill/main/install.sh | sh

osk init          # pick where your skill library lives
osk scan --write  # inventory every skill you already have, across all clients
osk adopt --all   # adopt every unmanaged skill; confirm each move
osk list          # see the coverage matrix
```

Skills you already have show up as `unmanaged`. `osk adopt --all` brings them all under
management in one pass; use `--dry-run` to preview or `--yes` after review for unattended
onboarding. You can also run the individual command `osk doctor` prints —
`osk adopt <path>` moves the body into the library, replaces the original with a symlink,
and links it into the other clients. If you hand-copied the same skill into two clients,
one adoption unifies them (the redundant copy is moved to an external backup, never
deleted).

Requires Python 3.9+. A single file, zero dependencies, no build step.

## A package manager for agent skills

Install skills straight from GitHub — into all of your clients at once:

```bash
osk install gh:anthropics/skills/skills/skill-creator@main --review
osk update            # re-fetch every remote skill; upgrades only on real changes
osk uninstall <name>  # unlink everywhere, body preserved as a backup
```

Downloads use the GitHub tarball API via Python's standard library — no `git` needed.
The manifest records each skill's source, resolved commit, and install time, and
`osk list` shows the pinned ref.

Third-party skills are third-party *prompts*: your agent will follow what's inside them.
`--review` prints the complete `SKILL.md` before anything is installed. Install only from
sources you trust.

## Commands

| Command | What it does |
|---|---|
| `osk list` | Coverage matrix across all clients. `--json` for machine output. |
| `osk doctor` | Detect drift: broken links, shadowed symlinks, manifest mismatches. Read-only — prints fixes, never runs them. |
| `osk adopt <path>` / `osk adopt --all` | Adopt one in-client skill, or every unmanaged skill in one pass. |
| `osk install <source>` | Install from a local directory or `gh:owner/repo[/subdir][@ref]`. |
| `osk update [name]` | Update one remote skill, or all of them. |
| `osk uninstall <name>` | Unlink everywhere; body kept as a timestamped backup. |
| `osk sync` | Reconcile reality against the manifest. Idempotent. |
| `osk scan --write` | Generate the manifest from your current setup. |
| `osk init` | First-time configuration. |

## How it works

One directory holds every skill body. Each client's skills directory holds symlinks into
it. A manifest records what *should* exist — so drift becomes a diff, not a guess.

```
  ~/skill-library/pdf-editing/SKILL.md   ← the only real copy
        ↑              ↑            ↑
  ~/.claude/     ~/.codex/    ~/.kimi-code/
    skills/        skills/       skills/
```

## It never deletes anything

Managing symlink farms means moving real directories around, so `oneskill` is built to
be un-scary:

- **Every destructive step asks first**, showing the exact paths involved.
- **Conflicts are renamed, never removed.** Client-side copies move outside the clients'
  load paths to `~/.oneskill/backups/<client>/<name>.oneskill-backup-<timestamp>`; library
  bodies keep their adjacent timestamped backups. There is no `rmtree` in the codebase.
- **`--dry-run` everywhere** prints the full plan and changes nothing.
- **Failed operations roll back** to where they started.
- **`list` and `doctor` are strictly read-only.**

The design rule: a bad day should cost you a rename, never a file.

## FAQ

**Is it automatic? Does it watch my skills directories?**
No — deliberately. There is no daemon, no watcher, no background process. The state of
your entire skill setup is always one `osk list` away, and every fix is one printed
command. If you work with AI agents anyway, the idiomatic setup is one line in your
agent's rules file (`CLAUDE.md`, `AGENTS.md`, …): *"after creating or installing a
skill, run `osk adopt <path>`"* — your agent maintains the library for you, which is
more reliable than any file watcher.

**I already have skills everywhere. How painful is onboarding?**
`osk scan --write` inventories everything in one shot, then `osk adopt --all` adopts every
unmanaged skill. It still asks before each move unless you pass `--yes`. Duplicated
hand-copies of the same skill collapse into one shared body, with redundant copies safely
backed up outside the client skills directories. `osk doctor` also prints one deduplicated
`adopt` command per skill if you prefer to work through them individually.

**Can I add another client (Gemini CLI, Copilot CLI, …)?**
Yes — client paths live in a single mapping near the top of `bin/osk`. One entry, and
every scan/list/sync/install path picks it up.

**Why aren't Claude Code plugin skills shared?**
They live in versioned cache paths that break on every plugin update, and their content
is bound to Claude-specific tooling. `oneskill` reports them honestly as `claude-only`
instead of pretending.

## Status

Young and honest about it: the safety properties are covered by 35 offline tests and CI
runs on Linux and macOS across Python 3.9/3.13 — but it has run on a handful of setups so
far. Bug reports from a second machine are genuinely useful.

```bash
python3 -m unittest discover -s tests
```

Implemented: bulk `adopt --all` for one-pass onboarding. Roadmap: more clients and a GUI
over `osk list --json` (the JSON keys are stable to build against today).

## License

MIT
