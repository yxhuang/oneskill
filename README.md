# oneskill

[![CI](https://github.com/yxhuang/oneskill/actions/workflows/ci.yml/badge.svg)](https://github.com/yxhuang/oneskill/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
![Zero dependencies](https://img.shields.io/badge/dependencies-none-brightgreen.svg)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/yxhuang/oneskill/pulls)

**One skill library. Every AI coding CLI.**

English | [简体中文](docs/README.zh-CN.md)

Claude Code, Codex CLI, and Kimi CLI all load *skills*: folders with a `SKILL.md` that
tells your agent how to do something. They use the same format, but each tool only reads its
own directory. So a skill you wrote well gets copied three times, and over time the copies
drift until you can't remember which one you actually fixed.

`oneskill` keeps **one copy** of each skill and symlinks it into every tool. One command
shows you what's shared, what lives in a single tool, and what has quietly broken.

<p align="center">
  <img src="docs/demo.svg" width="720"
       alt="osk list output: a coverage matrix grouping skills into SHARED across all three clients, CLIENT-SPECIFIC, and NEEDS ATTENTION, with one skill showing a real directory shadowing its symlink on Claude.">
</p>

The amber row at the bottom is the reason this exists. A tool upgrade replaced a symlink with
a real directory, so Claude is now running its own copy that no longer follows the library.
You would never catch that by eye. `osk doctor` tells you exactly how to fix it.

## What it solves

Symlinks like these rot, and nothing warns you:

- A tool upgrade overwrites a symlink with a real file, and the two copies split.
- A new skill gets made in whichever tool you happened to be using, and stays there.
- An uninstall leaves a dead link pointing at a directory that's gone.

None of this raises an error. Your agent just stops seeing the skill you wrote, or keeps
using a stale copy of it.

## Quick start

```bash
curl -fsSL https://raw.githubusercontent.com/yxhuang/oneskill/main/install.sh | sh

osk init          # pick where your skill library lives
osk scan --write  # inventory every skill you already have, across all tools
osk adopt --all   # adopt every unmanaged skill; it confirms each move
osk list          # see the coverage matrix
```

Skills you already have show up as `unmanaged`. `osk adopt --all` brings them all in at
once. Preview with `--dry-run`, or add `--yes` once you've looked to run unattended. You can
also work through them one at a time using the command `osk doctor` prints: `osk adopt <path>`
moves the body into the library, replaces the original with a symlink, and links it into the
other tools. If you had hand-copied the same skill into two tools, adopting it once merges
them into one, and the extra copy is moved aside as a backup rather than deleted.

Requires Python 3.9+. One file, no dependencies, no build step.

## Platforms

Linux and macOS are supported, and CI runs on both on every push (Python 3.9 and 3.13). On
**Windows, use WSL**: oneskill works by creating symlinks, which on native Windows need
Developer Mode or an elevated shell, and the installer is a POSIX shell script. Inside WSL
it's just a Linux program and works out of the box.

## Also a package manager for skills

You can install a skill straight from GitHub, into every tool at once:

```bash
osk install gh:anthropics/skills/skills/skill-creator@main --review
osk update            # re-fetch remote skills; only upgrades when the content changed
osk uninstall <name>  # unlink everywhere, keep the body as a backup
```

Downloads go through the GitHub tarball API using only the standard library, so `git` isn't
required. The manifest records each skill's source, the commit it resolved to, and when it
was installed, and `osk list` shows the pinned ref.

A third-party skill is a third-party prompt: your agent will act on whatever is inside it.
Pass `--review` to print the whole `SKILL.md` before installing, and only install from
sources you trust.

## Adopting vs. installing

Several tools now manage skills across AI CLIs — [cc-switch](https://github.com/farion1231/cc-switch)
is the most complete of them, with a desktop UI, provider switching, and a registry browser.
It is worth knowing which direction each tool runs in, because that decides what it can do
for you.

**Installer-style tools push down.** You browse a remote repository or registry, click
install, and the skill lands in each tool's directory. The starting point is a catalogue
somebody else maintains.

**oneskill pulls up.** The starting point is what is already on your disk: the skills you
wrote yourself, the ones some vendor's installer dropped in, the copy you pasted into a
second tool six months ago and forgot about. `osk scan` inventories them where they lie,
`osk adopt` collapses them into one body, and `osk doctor` keeps watching for the moment a
tool upgrade silently replaces a symlink with a real directory.

The two overlap in the middle — oneskill installs from GitHub too, and cc-switch symlinks
too — but the ends are different, and so are the gaps:

|  | oneskill | installer-style |
|---|---|---|
| Adopt skills already on disk | `osk scan` / `osk adopt` | generally not covered |
| Drift detection | `osk doctor` | not the focus |
| Browse and install from a registry | `osk search` + `osk install` | richer, with a UI |
| Interface | CLI, scriptable, agent-callable | usually a desktop app |
| Provider / MCP / prompt management | out of scope | often included |

⚠️ **Don't point two of them at the same directory.** If both oneskill and another manager
write symlinks into `~/.claude/skills/`, they will overwrite each other's work and neither
will be right. Pick one to be authoritative for skills.

If you do run both, put the library at `~/.agents/skills` on each side. That path is an
emerging community convention, oneskill offers it during `osk init`, and cc-switch supports
it as of v3.13 — so at least the bodies stay one copy.

## Commands

| Command | What it does |
|---|---|
| `osk list` | Coverage matrix across all tools. Add `--json` for machine output. |
| `osk doctor` | Find drift: broken links, real directories shadowing symlinks, manifest mismatches. Read-only, so it prints fixes but never runs them. |
| `osk adopt <path>` / `osk adopt --all` | Adopt one skill from a tool, or every unmanaged skill at once. |
| `osk search <query>` | Search the skills.sh public registry. Prints results and the command to install one; never installs on its own. |
| `osk install <source>` | Install from a local directory or `gh:owner/repo[/subdir][@ref]`. |
| `osk outdated [name]` | Check remote skills for updates through the GitHub API. Downloads nothing, changes no skill; `osk list` then marks them with `↑`. |
| `osk update [name]` | Update one remote skill, or all of them. |
| `osk uninstall <name>` | Unlink everywhere; the body is kept as a timestamped backup. |
| `osk sync` | Reconcile what's on disk against the manifest. Idempotent. |
| `osk scan --write` | Generate the manifest from your current setup. |
| `osk init` | First-time configuration. |

### Intentionally single-client skills

A skill linked into only one tool is flagged `needs review: single-client skill` — usually
drift worth fixing. When it is deliberate (a skill that only makes sense for one tool), add
`"single_client_ok": true` to its `skills.json` entry and the flag stops:

```json
{ "name": "mail-attachment-organizer", "source": "self", "body": "...", "scope": ["codex"],
  "single_client_ok": true }
```

The flag survives `osk scan --write`. It is tied to the body path it was confirmed against,
so replacing the skill's implementation clears it and asks for review again.

## How it works

One directory holds every skill body. Each tool's skills directory holds symlinks that point
into it. A manifest records what should be there, so drift becomes a diff instead of a guess.

```
  ~/skill-library/pdf-editing/SKILL.md   ← the only real copy
        ↑              ↑            ↑
  ~/.claude/     ~/.codex/    ~/.kimi-code/
    skills/        skills/       skills/
```

## It doesn't delete things

Managing symlinks means moving real directories around, so oneskill leaves an exit at every
step:

- Every destructive step asks first, and shows the exact paths involved.
- Conflicts are renamed, not removed. A copy sitting in a tool's directory is moved out of
  that tool's load path, into `~/.oneskill/backups/<tool>/`; a body in the library keeps a
  timestamped backup next to it. There is no `rmtree` anywhere in the code.
- `--dry-run` works everywhere and prints the plan without touching anything.
- If an operation fails partway, it rolls back to where it started.
- `list` and `doctor` are read-only and safe to run any time.

The worst case is one extra rename, never a lost file.

## FAQ

**Is it automatic? Does it watch my skills directories?**
No, and that's on purpose. There's no daemon, no watcher, no background process. The full
state of your setup is one `osk list` away, and every fix comes as a command you can run. If
you already work with AI agents, the natural setup is one line in your agent's rules file
(`CLAUDE.md`, `AGENTS.md`, and so on): *"after creating or installing a skill, run
`osk adopt`."* Your agent keeps the library in order, which beats any file watcher.

**My skills are already scattered everywhere. Is onboarding painful?**
`osk scan --write` inventories all of them at once, then `osk adopt --all` takes them in.
Unless you pass `--yes`, it asks before each move. Copies of the same skill across tools
collapse into one shared body, and the extras are backed up outside the tools' directories.
If you'd rather go one by one, `osk doctor` prints a single `adopt` command per skill.

**Can I add another tool (Gemini CLI, Copilot CLI, and so on)?**
Yes. The tool paths live in one mapping near the top of `bin/osk`. Add an entry, and scan,
list, sync, and install all pick it up.

**Why aren't Claude Code plugin skills shared?**
They live in cache paths with a version number in them, so the symlink breaks on every plugin
update, and their contents are tied to Claude-specific tooling. oneskill just labels them
`claude-only` instead of pretending they can be shared.

## Status

Still early. The safety behavior is covered by 46 offline tests, and CI runs on Linux and
macOS across Python 3.9 and 3.13, but it has only run on a few machines so far. If you hit a
bug on another setup, a report would genuinely help.

```bash
python3 -m unittest discover -s tests
```

Done: `adopt --all` for one-pass onboarding. Next: more tools, and a GUI over
`osk list --json` (the JSON keys are stable enough to build on now).

## Contributing

Issues and PRs are welcome, especially a bug report from a machine that isn't mine. If you
work on the code, turn on the guard hook so your local paths never end up in a commit:

```bash
git config core.hooksPath .githooks
```

It blocks committing `skills.json` (local machine state, regenerable with `osk scan --write`)
and any absolute `/home/<user>` path in what you've staged.

## Disclaimer

oneskill moves real directories inside your tools' skill folders. It's built not to delete:
conflicts are renamed and backed up, every destructive step confirms first, and `--dry-run`
previews everything. Even so, you run it at your own risk. If you want to be careful, start
with `--dry-run`, or point `ONESKILL_HOME` at a throwaway directory and watch it work.
Provided as-is, without warranty. See [LICENSE](LICENSE).

## Acknowledgments

Built with help from a few AI coding assistants: Claude Code, Codex CLI, and Kimi CLI, which
is apt, given that oneskill's whole job is keeping the skills those tools load in order.

## License

Released under the [MIT License](LICENSE).

---

⭐ If oneskill saved you from a skill that had quietly drifted, a star helps others find it.

<a href="https://star-history.com/#yxhuang/oneskill&Date">
  <img src="https://api.star-history.com/svg?repos=yxhuang/oneskill&type=Date" width="600" alt="Star History Chart">
</a>
