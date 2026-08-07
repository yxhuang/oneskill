# oneskill

[![CI](https://github.com/yxhuang/oneskill/actions/workflows/ci.yml/badge.svg)](https://github.com/yxhuang/oneskill/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](../LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
![Zero dependencies](https://img.shields.io/badge/dependencies-none-brightgreen.svg)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/yxhuang/oneskill/pulls)

**所有 AI 编程 CLI，共用一个技能库。**

[English](../README.md) | 简体中文

Claude Code、Codex CLI、Kimi CLI 都会加载 skill，也就是一个带 `SKILL.md` 的文件夹，
告诉 agent 某件事该怎么做。三家用的是同一种格式，可每个工具只认自己的目录。于是你写好
一个 skill，得复制三份；时间一长，三份各自被改过，慢慢就不一样了，你也记不清哪份才是
对的。

oneskill 让每个 skill 只留一份，用软链接到各个工具。一条命令就能看清：哪些三端都有、
哪些只在某一端、哪些已经悄悄坏了。

<p align="center">
  <img src="demo.svg" width="720"
       alt="osk list 的输出：覆盖矩阵分成三段，三端共享、单端专属、需要处理，其中一个技能在 Claude 端被真实目录盖住了软链。">
</p>

最下面那行标红的，正是这个工具存在的理由。某次工具升级把软链换成了真实目录，Claude
从此用上一份自己的副本，不再跟着库走。这种事光靠眼睛根本看不出来，`osk doctor` 会把
该怎么修直接告诉你。

## 它解决什么

软链这东西用久了会坏，而且坏得一点声响都没有：

- 工具升级时可能把软链盖成真实文件，两份从此各走各的；
- 新 skill 建在你当时用的那个工具里，然后就一直留在那；
- 卸载旧 skill，会留下一条指向空目录的死链。

这些都不会报错。你的 agent 只是悄悄看不到你写的 skill 了，或者一直在用一份过时的。

## 快速上手

```bash
curl -fsSL https://raw.githubusercontent.com/yxhuang/oneskill/main/install.sh | sh

osk init          # 选定技能库放在哪
osk scan --write  # 把你各个工具里已有的 skill 盘点出来
osk adopt --all   # 一次收编全部未纳管的 skill，每挪一处都会先问你
osk list          # 看覆盖矩阵
```

已有的 skill 会标成 `unmanaged`（未纳管）。`osk adopt --all` 能一次全收编：想稳妥就先
`--dry-run` 看一遍，确认没问题再加 `--yes` 一口气跑完。也可以照 `osk doctor` 给的命令一个个
来，`osk adopt <路径>` 会把本体移进库里，原地换成软链，再链到其余工具。要是你之前把同一个
skill 手动复制到了两个工具里，收编一次就把它们并成一份，多出来的那份会挪去备份，不会删。

需要 Python 3.9 以上。一个文件，没有任何依赖，不用编译。

## 平台

支持 Linux 和 macOS，每次提交 CI 都会在这两个平台上各跑一遍（Python 3.9 和 3.13）。
**Windows 请走 WSL**：oneskill 靠软链工作，而 Windows 原生建软链要开发者模式或管理员
权限，安装脚本也是 POSIX shell。在 WSL 里它就是个普通的 Linux 程序，装上就能用。

## 顺带还是个 skill 包管理器

可以直接从 GitHub 装 skill，一次装进所有工具：

```bash
osk install gh:anthropics/skills/skills/skill-creator@main --review
osk update            # 重新拉取远程 skill，只有内容真变了才升级
osk uninstall <name>  # 各端断链，本体留作备份
```

下载走 GitHub 的 tarball 接口，只用到 Python 标准库，连 `git` 都不需要。清单里会记下每个
skill 的来源、拉到的是哪个 commit、什么时候装的，`osk list` 会显示锁定的版本。

第三方 skill 等于第三方提示词，你的 agent 会照着里面写的执行。装之前用 `--review` 把整个
`SKILL.md` 打出来看清楚，只装你信得过的来源。

## 收上来，和放下去

现在管跨端 skill 的工具不止一个，[cc-switch](https://github.com/farion1231/cc-switch)
是其中做得最全的——有桌面界面、能切 provider、能浏览注册表。值得先弄清楚各自是朝哪个
方向跑的，因为方向决定了它能替你干什么。

**安装器那类工具是往下放。** 你去浏览远程仓库或注册表，点安装，skill 落到各个工具的目录
里。起点是别人维护的那份目录清单。

**oneskill 是往上收。** 起点是你硬盘上已经有的东西：自己写的、某个厂商的安装器顺手塞进来
的、半年前手动拷进第二个工具后就忘了的那份。`osk scan` 先就地盘点，`osk adopt` 把它们并成
一份本体，`osk doctor` 则一直盯着——盯的就是某次工具升级悄悄把软链换成真实目录的那一刻。

两者在中间是有重叠的：oneskill 也能从 GitHub 装，cc-switch 也用软链。但两头不一样，
所以各自缺的东西也不一样：

|  | oneskill | 安装器那类 |
|---|---|---|
| 收编硬盘上已有的 skill | `osk scan` / `osk adopt` | 基本不覆盖 |
| 漂移检测 | `osk doctor` | 不是重点 |
| 浏览注册表并安装 | `osk search` + `osk install` | 更全，还有界面 |
| 交互方式 | CLI，可脚本化，agent 能直接调 | 通常是桌面应用 |
| provider / MCP / 提示词管理 | 不在范围内 | 一般都带 |

⚠️ **别让两个工具管同一个目录。** 如果 oneskill 和另一个管理器都往 `~/.claude/skills/`
写软链，它们会互相覆盖，最后哪边都不对。选一个作为 skill 这块的权威。

真要两个都用，就把两边的库都指到 `~/.agents/skills`。这个路径是社区正在形成的约定，
oneskill 在 `osk init` 时会推荐它，cc-switch 从 v3.13 起也支持——这样至少本体还是一份。

## 命令

| 命令 | 作用 |
|---|---|
| `osk list` | 全工具覆盖矩阵，加 `--json` 输出机器可读格式 |
| `osk doctor` | 找出跑偏的地方：断链、被真实目录盖住的软链、和清单对不上。只读，只打印修复命令，绝不代跑 |
| `osk adopt <路径>` / `osk adopt --all` | 收编某个工具里的一个 skill，或一次收编全部未纳管的 |
| `osk search <关键词>` | 搜 skills.sh 公共注册表，列出结果和对应的安装命令，自己绝不动手装 |
| `osk install <源>` | 从本地目录或 `gh:owner/repo[/子目录][@ref]` 安装 |
| `osk outdated [名字]` | 走 GitHub 接口查远程 skill 有没有更新。不下载、不改动任何 skill，查完 `osk list` 会用 `↑` 标出来 |
| `osk update [名字]` | 更新一个或全部远程 skill |
| `osk uninstall <名字>` | 各端断链，本体留作带时间戳的备份 |
| `osk sync` | 拿磁盘上的实际情况和清单对账，可重复跑 |
| `osk scan --write` | 按当前环境生成清单 |
| `osk init` | 首次配置 |

## 原理

一个目录放所有 skill 的本体，各工具的 skills 目录里全是指过来的软链。清单记着「本该是什么
样」，这样有没有跑偏，一对比就知道，不用猜。

```
  ~/skill-library/pdf-editing/SKILL.md   ← 唯一的真实副本
        ↑              ↑            ↑
  ~/.claude/     ~/.codex/    ~/.kimi-code/
    skills/        skills/       skills/
```

## 它不删东西

管软链免不了要挪真实目录，所以 oneskill 每一步都给你留了退路：

- 每一步有破坏性的操作，都会先把涉及的完整路径列出来，问过你再动手；
- 冲突的东西只改名，不删除。工具目录里那份副本，会挪出该工具的加载路径，放到
  `~/.oneskill/backups/<工具>/` 下带时间戳的位置；库里的本体，则在原地留一份带时间戳的
  备份。整个代码里没有一处 `rmtree`；
- `--dry-run` 到处都能加，只打印计划，什么都不动；
- 操作中途失败，会回滚到动手前的样子；
- `list` 和 `doctor` 只读，随时跑都安全。

最坏的情况，也不过是多出一次重命名，绝不会丢文件。

## 常见问题

**它是自动的吗？会盯着我的 skill 目录吗？**
不会，这是特意这么设计的。没有常驻进程，没有监听，没有后台任务。你整套 skill 的状态，
一条 `osk list` 随时能看全，每处要修的地方它都给现成的命令。如果你本来就在用 AI agent，
最顺手的做法是在 agent 的规则文件里（`CLAUDE.md`、`AGENTS.md` 这类）写一句「新建或安装
skill 之后跑一下 `osk adopt`」，让 agent 顺手替你维护，比任何文件监听都靠谱。

**我的 skill 已经到处都是了，接进来麻烦吗？**
`osk scan --write` 一次全盘点出来，`osk adopt --all` 一次全收编。不加 `--yes` 的话，每挪
一处都会问你。同一个 skill 在几个工具里的手动副本会并成一份，多余的挪到工具目录之外备好。
想一个个来也行，`osk doctor` 会按 skill 去重，每个只给你一条 `adopt` 命令。

**能加别的工具吗（Gemini CLI、Copilot CLI 这些）？**
能。工具的路径集中写在 `bin/osk` 顶上的一个映射里，加一条，scan、list、sync、install 就
全都认了。

**为什么 Claude Code 的插件 skill 不共享？**
它们放在带版本号的缓存路径里，插件一升级软链就断；内容也跟 Claude 专有的那套东西绑得很
深。oneskill 干脆如实把它们标成 `claude-only`，不假装能共享。

## 现状

还年轻。安全这块有 46 个离线测试盯着，CI 在 Linux 和 macOS 上跑 Python 3.9 和 3.13，
不过目前也就在不多几台机器上用过。要是你在别的环境上碰到问题，欢迎报 bug，对我很有帮助。

```bash
python3 -m unittest discover -s tests
```

已经做完的：`adopt --all` 批量收编。往后打算做的：支持更多工具，以及一个基于
`osk list --json` 的图形界面（JSON 字段已经稳定，现在就能照着对接）。

## 参与

欢迎提 issue 和 PR，尤其欢迎来自别人机器上的 bug 反馈。要动代码的话，先打开这个防护钩子，
免得把本机路径带进提交：

```bash
git config core.hooksPath .githooks
```

它会拦下 `skills.json`（这是机器本地的东西，`osk scan --write` 能重新生成），以及暂存内容
里任何形如 `/home/<用户名>` 的绝对路径。

## 免责声明

oneskill 会去动你各个工具 skill 目录里的真实目录。它是按「不删东西」来设计的：冲突改名
备份、每步破坏性操作都先确认、哪儿都能 `--dry-run` 预览；即便如此，用它的风险还是由你自己
承担。想稳妥就先 `--dry-run`，或者把 `ONESKILL_HOME` 指到一个临时目录，先看看它怎么干活。
软件按原样提供，不含任何担保，详见 [LICENSE](../LICENSE)。

## 致谢

开发中用到了这几个 AI 编程助手：Claude Code、Codex CLI、Kimi CLI。也算应景，毕竟 oneskill
要管的，正是这些工具加载的 skill。

## 许可

基于 [MIT 许可证](../LICENSE)发布。

---

⭐ 如果 oneskill 帮你揪出过一个偷偷跑偏的 skill，点个 star，让更多人找到它。

<a href="https://star-history.com/#yxhuang/oneskill&Date">
  <img src="https://api.star-history.com/svg?repos=yxhuang/oneskill&type=Date" width="600" alt="Star History Chart">
</a>
