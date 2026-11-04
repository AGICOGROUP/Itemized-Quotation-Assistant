# Itemized Quotation Assistant / 分项报价助手

一个把「厂家成本表 → 分项报价」做成固定流水线的 Agent Skill。目标不是给一个笼统价格，而是把报价拆成可解释、可复核、可调整的分项结构：每项加价有依据，总价能反算，过程可追溯。

An agent skill that turns a supplier cost table into a fully itemized export quotation: deterministic markup rules, export-tax refund handled per item, and a calculation trail you can audit line by line.

---

## 它解决的问题

出口项目报价里最容易出错的三件事：

1. **税与加价混在一起算**。退税按未税成本推，服务与运输类通常不给退税，混算就会系统性高估或低估。
2. **特殊加价靠口头约定**。某几项按 15%、某几项按原价，人均记得住、系统记不住，换个人就变。
3. **报价单不可复核**。只给总价，客户一问"凭什么这项贵 76%"，答不上来。

本项目把这些做成固定流程：表单采集参数 → 位图编码回传 → 哈希绑定核算 → 四段汇报 + 三分页 Excel。

## 核心设计

**单一呈现契约。** 参数确认表单只有一种形态，由脚本生成、模板指纹与形状指纹双重锁定；AI 无法"这次换个样子"。契约文件 `contracts/form-presentation.md` 是机器读取的，`check_contract.py` 逐项核对围栏、字数上限、槽位数与哈希。

**参数不接受自然语言。** 表单产出 QP2 十三字段提交串（位图编码选项），后端解码；`input.json` 与 `confirmation.json` 以 SHA256 绑定，改一个数字就拒绝计算。

**计算口径显式化。**

```
可退税成本   = 成本合计 − 不可退税项
假定退税     = Σ 成本 ÷ (1 + 进项税率) × 退税率
退税后成本   = 成本合计 − 假定退税 + 额外费用
总报价       = 退税后成本 ÷ (1 − 利润率 − 佣金率)
分项报价     = 固定加价项先算，余额按原成本比例分摊
```

**可复核交付。** 每次核算输出四段：总报价 → 采用参数 → 总价计算过程 → 分项报价表；Excel 三个工作表（分项报价 / 参数与汇率 / 计算过程）。

## 目录

```
SKILL.md                        流程、呈现契约、稳定性锁、计算口径
contracts/form-presentation.md  机读契约（围栏/上限/槽位/模板与形状哈希）
templates/                      表单模板 + 两个指纹锁
scripts/                        渲染、校验、解码、绑定、核算、报表、Excel、测试
references/                     输入兼容规则与参数说明
INSTALL.md                      安装与自检
MANIFEST.sha256                 全部文件校验值
```

## 快速开始

```bash
cd scripts
python check_contract.py                                    # 期望 CONTRACT OK
python -m unittest test_grouped test_workflow test_submission   # 期望 34 tests OK
```

依赖：Python 3.9+（标准库）、`openpyxl`（Excel）、`node`（表单语法自检，缺失则跳过该项）。

详细步骤见 [INSTALL.md](INSTALL.md)。

## 状态与边界

- 已覆盖：成本表转录校验、分项加价、出口退税、汇率（实时/固定）、Excel 交付。
- 不承诺：成交价、客户接受度、利润实现。工具只负责把已确认的规则算准、算清。
- 表单渲染受宿主限制：widget 只在生成它的客户端内成形，跨端转发会退化为源码。这是宿主边界，本项目不通过"另做一份 HTML"绕过契约。

## 联系

使用问题或优化建议：钉钉 / 微信 潘晓康。
