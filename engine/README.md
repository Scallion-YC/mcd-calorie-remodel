# engine

核心引擎。零第三方依赖，Python 3.9+。

```
engine/
├── sync.py        从 MCP 同步快照（需要 Token）
├── core.py        对齐 / 汇总 / 打分 / 求解 / 改造 / 渲染
├── cli.py         命令行入口
├── verify.py      用 calculate-price 核验菜单价
├── delivery.py    外送：地址→门店→外卖菜单→核价
└── data/
    ├── menu.json           120 个 SKU（含价格）
    ├── nutrition.json      营养表 160 行
    ├── details/*.json      40 份套餐详情
    ├── aliases.json        命名差异（可口可乐中杯→可乐中杯）
    ├── derived.json        倍数推导（4 块鸡翅 = 2 块 × 2）
    ├── estimates.json      当季新品区间估算（3 项）
    ├── factors.json        特调因子表（8 项，均来自真实特调项）
    ├── taste.json          口感代价权重
    └── zero_whitelist.json 0 卡白名单（4 条，已核对）
```

## 用法

```bash
# 1) 同步（只在需要更新菜单时跑）
set MCD_MCP_TOKEN=你的Token
python engine/sync.py

# 2) 看数据规模与覆盖率
python engine/cli.py coverage

# 3) 列出可完整计算的套餐
python engine/cli.py list

# 4) 出方案
python engine/cli.py plan --mode cut  --kcal 900 --weight 70
python engine/cli.py plan --mode bulk --kcal 1000 --weight 70
python engine/cli.py plan --mode keep --kcal 700 --weight 70 --show 2

# 5) 当季新品估算（不进排序）
python engine/cli.py estimate --name 龙焰鸡腿堡

# 6) 外送
python engine/delivery.py --mode cut --kcal 900 --weight 70

# 7) 自测（14 项验收，离线）
python engine/cli.py selftest
```

## 四条容易踩的规则

1. **先过硬约束再排序**。热量、蛋白先过滤，剩下的才按模式指标排。
2. **partial 不给总数**。组件缺营养时只报已知部分与缺失项，不冒充完整。
3. **0 卡要看白名单**。名单内保留 0（无糖可乐、纯悦），名单外一律视为 unknown。
4. **估算不进排序**。当季新品只给区间与误差带，不与 exact 数据混算。

## 当前数据事实

- 可完整计算（exact）的套餐：31 个
- 组件级命中：107/107（别名 6 项，倍数推导 1 项）
- partial：5 个，卡在当季新品（龙焰系列、大堡口福）
- 菜单价与 `calculate-price` 抽样 8 个，8/8 一致（`python engine/verify.py --limit 8`）
- 特调因子表 8 项（麦香鸡酱/麦香鱼酱/吉士/培根/生菜/切块生菜/黄油/番茄酱），来源为台湾官网，标 `low`，不计入主数值；低于 10 kcal 的项不展示
- 减脂/增肌的蛋白下限在麦当劳单餐基本不可达（37 g / 42 g），引擎会降级并如实报缺口
