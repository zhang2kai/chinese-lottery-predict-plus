# Chinese Lottery Predict Plus

一个面向 AI Agent 的中文 Skill。它基于可核验的真实历史开奖数据，统计双色球（SSQ）或大乐透（DLT）的号码频次，并生成仅供娱乐的合法号码组合。

历史频次不能预测未来开奖结果。本项目不保证中奖，不提供投注技巧、追号、倍投或投资回报建议。

## 特点

- 按数据发布者可信度选择来源，不绑定某个搜索工具。
- 明确校验号码范围、数量、唯一性、期号和来源元数据。
- 默认披露最近 `100` 期的统计窗口和数据截止点。
- 使用标准库 Python 脚本统计和生成，避免依赖 Agent 手工计数。
- 支持随机种子，便于复现和测试。
- 内置组合概率、大数定律频次基线和可选奖金情景 EV，详见 [数学模型](references/mathematical-models.md)。
- 单次最多展示 `20` 注，不主动建议增加预算。

## 仓库结构

```text
.
├── SKILL.md
├── references/
│   ├── lottery-rules.md
│   ├── data-sources.md
│   ├── mathematical-models.md
│   └── output-format.md
├── scripts/
│   └── analyze_draws.py
└── tests/
    └── test_analyze_draws.py
```

## 安装

```bash
npx skills add https://github.com/zhang2kai/chinese-lottery-predict-plus.git --skill chinese-lottery-predict-plus
```

## 脚本用法

先按 [标准输入格式](references/data-sources.md#标准输入格式) 准备经过来源核对的数据，再运行：

```bash
python3 scripts/analyze_draws.py draws.json --window 100 --count 5
```

需要复现相同组合时，增加随机种子：

```bash
python3 scripts/analyze_draws.py draws.json --window 100 --count 5 --seed 20260911
```

脚本负责校验输入、统计历史频次、计算数学模型和生成合法组合，不负责联网抓取。Agent 必须先从真实来源取得数据，并保留来源名称、URL 和带时区的检索时间。EV 默认不输出数值；可通过 `--payouts` 提供完整税前奖金情景，输入格式见数学模型说明。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

## 风险提示

彩票开奖是随机事件。历史频次不能预测未来结果；每个合法号码组合在公平开奖中的理论机会相同。所有生成结果仅供娱乐，请只使用可承受损失的娱乐预算。
