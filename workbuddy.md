# WorkBuddy 开发记录

> 本文件记录本项目在 WorkBuddy 中的实际开发过程，用于核验联动活动资格。
> 项目：麦当劳热量改造器（mcd-calorie-remodel）
> 开发日期：2026-10-17
> 开发环境：Windows，WorkBuddy 桌面端，Python 3.12.10，Edge 无头浏览器

---

## 1. 起点

最初的需求只有一句话：在 GitHub 上搜一下麦当劳中国的账号。

搜到 `M-China` 组织后发现两件事：官方 MCP 已经开放了 35 个工具；同时正在办程序员创意开发大赛，榜单前 10 名里 3 个做省钱比价、3 个做趣味人格，热量方向只有 1 个且排在第 10。

于是问题变成：这个赛道还剩下什么没被做。

---

## 2. 关键决策过程

### 2.1 用真实数据判断，不靠感觉

先抓了榜单前 10 名的 README 全文，又补了热量/健身方向 6 个尾部项目，共 16 份，做成 `竞品拆解.md`。

结论来自可核对的数字：热量赛道至少 10 个项目，天花板 149 星；而「特制/去酱/加酱/少酱」在 16 份 README 里出现 0 次。

### 2.2 定位收窄

四个候选空位里，只选「特制热量账」做产品脸，「SKU↔营养对齐」做底座，另外两个写进「不做」。理由：`orderye/mcd-calorie-skill` 做了 13 种场景只有 5 星，广度不是护城河。

### 2.3 先实测再写代码

写了一份 MCP 探针 `probe/mcp_probe.py`，用真实 Token 跑出四件事：

- 服务端 35 个工具，官方文档写 33 个
- `query-meals` / `query-meal-detail` 必须带 `orderType` + `beType`
- 营养表是 TOON 文本，160 行，无 code 列
- 套餐详情有 `rounds[].choices[]`，每个组件带独立 code 与 `diffPrice`

这四条决定了整个产品的可行性，也全部写进了 `实测报告.md`。

---

## 3. WorkBuddy 承担的工作

| 环节 | 产出 | 说明 |
|---|---|---|
| 竞品调研 | `竞品拆解.md` | 抓取 16 份 README，统计能力覆盖，做空位判断 |
| 需求文档 | `产品需求手册.md` | 从 v0.1 规则说明补到 v0.2 可开发状态 |
| MCP 探针 | `probe/mcp_probe.py` | 握手、工具清单、营养表体检、链路探测 |
| 核心引擎 | `engine/` | 对齐、汇总、打分、求解、改造、渲染 |
| 网页演示 | `demo/index.html` | 单文件 146 KB，零外链，免 Token |
| 文档 | `README.md`、`SKILL.md`、`MCP_INTEGRATION.md` | 参赛三件套 |

其中三次「写完才发现问题」都记录在案：

1. 蛋白下限不可达，第一版返回空结果 → 改为降级并明示缺口
2. 维持模式推荐「只有一杯可乐」→ 加主食过滤与区间排序
3. 减脂把 865 卡砍到 482 卡 → 加 30% 降幅和 400 kcal 下限

---

## 4. 验证方式

不靠肉眼，靠可复现的命令：

```bash
python engine/cli.py selftest      # 10 项，全通过
node demo/_test.js                 # 13 项，与 Python 引擎逐项对齐
python engine/verify.py --limit 8  # 菜单价 vs calculate-price，8/8 一致
```

文档里的示例卡片与 CLI 输出做过逐行 diff，两份文档均一致。

参赛声明 `CONTEST_DECLARATION.md` 从官方仓库下载后做了字节级校验，1522 字节，与官方 base64 解码结果完全相同。

---

## 5. 用到的 WorkBuddy 能力

- 文件读写与多文件重构（`engine/`、`demo/`、文档）
- 命令执行（Python、Node、curl、Edge 无头截图）
- 联网检索（GitHub API、raw.githubusercontent.com、官方仓库）
- 图片理解（读无头截图判断布局问题）
- 长上下文维护（跨十余轮保持数据口径一致）

---

## 6. 产物清单

```
README.md                参赛主文档
SKILL.md                 技能定义
MCP_INTEGRATION.md       工具与调用说明
CONTEST_DECLARATION.md   官方声明（原文）
demo/index.html          离线演示
engine/                  核心引擎与数据快照
probe/mcp_probe.py       MCP 探针
竞品拆解.md / 实测报告.md / 产品需求手册.md
```

---

## 7. 说明

- 项目代码与文档由 WorkBuddy 在用户指令下生成，数据来自麦当劳中国官方 MCP。
- 竞品分析中的数字为 2026-10-17 的榜单快照，随榜单变化会失效。
- 本项目非麦当劳官方产品，输出不构成营养或医疗建议。
