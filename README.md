# skx

`skx` 管理 Claude Code、Codex CLI、Kimi CLI 三端的 skill 软链接。它把
`agent-env` 中的自制/第三方本体、外部安装器管理的本体和 Claude 插件放进同一张覆盖
矩阵，帮助发现升级或手工安装造成的漂移。

项目刻意保持简单：一个 Python 3 文件，只用标准库，不安装依赖。`list` 和 `doctor`
只读；`adopt`、`sync` 遇到移动或替换会先展示计划并要求确认。

## 安装

仓库内直接运行：

```bash
/home/you/oneskill/bin/skx --version
```

也可以把入口软链到已有的 `PATH` 目录：

```bash
ln -s /home/you/oneskill/bin/skx ~/.local/bin/skx
```

不要复制脚本；默认 manifest 路径按脚本真实位置定位，软链安装仍会读取本仓库的
`skills.json`。

## 常用命令

先扫描现状并生成 manifest 草稿：

```bash
skx scan --write
```

只在单端出现的 skill 会保留单端作用域，并带上
`待人工确认是否为有意的单端专属`，不会自动认定为 shared。扫描还会读取 Claude 的
`~/.claude/plugins/installed_plugins.json`，把已安装插件登记为 `plugin`、
`claude-only`；插件由 Claude 自己管理，`skx sync` 不碰插件缓存。

查看覆盖矩阵：

```bash
skx list
skx list --json
```

状态分为软链健康、缺失和异常。异常包括断链/孤儿链、软链目标错误、真实目录或文件
遮蔽、多余项。JSON 输出只含一个合法 JSON 值，可直接作为 GUI 数据源。

只读诊断：

```bash
skx doctor
skx doctor --json
```

每个问题都附一条供人工复制的建议命令，`doctor` 自己不执行修复。有问题时退出码为
1，无问题时为 0。扫描草稿里尚未人工确认的单端作用域也会列为 `scope_review`，避免
初次扫描把孤立安装静默当成正常状态。

收编某端新建的真实 skill 目录：

```bash
skx adopt ~/.codex/skills/my-skill
skx adopt ~/.kimi-code/skills/vendor-skill --vendor
skx adopt ~/.codex/skills/codex-only --scope codex
skx adopt ~/.codex/skills/two-clients --scope codex,kimi
skx adopt ~/.codex/skills/my-skill --dry-run
```

默认作用域是 `shared`。普通收编把本体放到
`agent-env/<发起端>/skills/<name>`；`--vendor` 放到 `agent-env/vendor/<name>`。
工具会逐项打印移动/替换计划并从 stdin 读取 `y/N`。`--yes` 用于明确授权的自动化和
集成测试，不建议日常盲用。冲突项不会删除，而会改名成带时间戳的
`.skx-backup-*` 后再补链。

按 manifest 对账：

```bash
skx sync --dry-run
skx sync
```

缺失且本体存在的软链直接补齐；断链、错误目标、真实文件/目录等替换操作逐项确认。
无法自动解决的本体缺失、插件缺失和 manifest 外多余项只报告。命令是幂等的：完成
一次同步后再次运行会输出 `同步完成：零改动。`

## manifest 格式

默认清单是仓库根目录的 `skills.json`，格式版本为 1。条目按名字排序，便于人工审查
和 git diff：

```json
{
  "version": 1,
  "skills": [
    {
      "name": "refine-prompt",
      "source": "self",
      "body": "/home/you/skill-library/claude/skills/refine-prompt",
      "scope": "shared"
    },
    {
      "name": "mail-attachment-organizer",
      "source": "self",
      "body": "/home/you/skill-library/codex/skills/mail-attachment-organizer",
      "scope": ["codex"],
      "review": "待人工确认是否为有意的单端专属"
    }
  ]
}
```

- `source`：`self`、`vendor`、`external`、`plugin` 之一。
- `body`：skill 本体的绝对路径；external 一般位于 `~/.agents/skills/`。
- `scope`：`shared` 或端名数组，端名只能是 `claude`、`codex`、`kimi`。
- `review`：扫描草稿的提醒字段，人工确认后可保留或删除。
- `plugin_id`：插件条目可带的 Claude 插件完整标识。

## 测试路径重定向

以下环境变量把所有可变路径导向测试沙箱：

| 变量 | 默认值 | 用途 |
|---|---|---|
| `SKX_HOME` | `$HOME` | 三端目录的家目录基准，同时决定 `.agents` 和 Claude 插件登记路径 |
| `SKX_AGENT_ENV` | `/home/you/skill-library` | skill 库根目录 |
| `SKX_MANIFEST` | 仓库根目录 `skills.json` | manifest 文件路径 |

集成测试只在 `/tmp` 下创建假 home 和假 agent-env，不接触真实配置：

```bash
python3 -m unittest discover -s tests -v
```

测试覆盖三端健康、单端缺失、真实目录遮蔽、断链/孤儿链、doctor 建议、adopt 全流程、
dry-run、sync 幂等和 JSON 纯净输出。
