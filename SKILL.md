---
name: "[Harvest] 出口项目分项报价与Excel导出"
description: 根据厂家成本表制作出口项目分项报价；通过对话内Widget表单确认参数（含可选汇率模式），计算并展示原价、加价规则及最终报价，最后生成包含分项明细、参数设置及计算过程的Excel汇总表供用户下载。严格绑定单一表单呈现方式，禁止使用HTML或其他替代格式。
created_by: main_agent
---
## Workflow
1. **读取与标准化**：读取{cost_file}或{screenshot}，按 [references/input-compatibility.md](references/input-compatibility.md) 转录。逐项求和必须与表内小计/合计对上；对不上先说明差额，不得自行抹平。产出 `work/{case_id}/draft.json`，其中 `fields`、`items`、`categories`、`item_settings` 四部分齐全。
2. **生成确认表单**：执行 `python scripts/render_form.py --draft draft.json --output form.txt`。渲染器在写文件前自动运行内部校验（围栏、长度、占位符、括号配平、`node --check`），任何一项不过就报错且**不产出文件**。脚本输出**完整的 widget 代码块**（首行 ```widget quotation-confirm-form-v4，末行 ```）。将 `form.txt` 全文原样贴入回复：用工具读文件后整段复制，**禁止在回复里重新手打或改写任何字符**。发前可再跑 `python scripts/verify_form.py --form form.txt` 复核，看到 `FORM OK`。
   - **唯一呈现方式**：表单必须且只能通过 `quotation-confirm-form-v4` Widget 呈现。严禁生成 HTML 页面、图片或其他格式的表单。
   - 禁止手写、改写、精简、重排表单；禁止更换标识符或改成裸 ```widget。
   - 表单外观由 `templates/confirm-form.html` 唯一决定，不随项目变化；变化的只有项目明细、成本合计、预置加价组和税额提示。
   - 生成后跑 `python scripts/check_contract.py`，必须看到 `CONTRACT OK`：它核对 [contracts/form-presentation.md](contracts/form-presentation.md) 里的围栏、上限、槽位数与两个哈希是否与模板、锁文件、样例渲染一致。
   - 脚本对整块长度做硬校验（上限 12,000 字符），超限直接报错并且不产出文件。此时**不要**硬发，按脚本提示减少行数或改用汇总口径。
   - **发送后必须回读校验**：贴出表单后立刻跑 `python scripts/verify_sent.py`。它读宿主持久化的会话记录（`~/.accio/accounts/*/conversations/dm/*.jsonl`），核对**实际发出的那条消息**，而不是 `form.txt`。必须看到 `SENT OK`。
     - 输出 `SENT BROKEN` 时，看 `fence line` 一行：它打印真实首行。据此改正后重发一次（最多两次）；重发后仍不支持，按 Pitfalls 处理。
     - 这一步是唯一能发现"文件对、消息错"的手段：围栏被合并进上一句、被列表或引用包裹、被缩进、首行混入全角空格或不可见字符、丢失闭合围栏，在 `form.txt` 里全都看不出来。
3. **接收确认**：等用户点"确认参数并计算"并回传 QP2 串。用 `scripts/parse_widget_submission.py --draft draft.json --message "@msg.txt" --output submission.json` 解码。不得从自然语言里"猜"参数。
4. **绑定输入**：`scripts/prepare_input.py --draft draft.json --submission submission.json --user-message-reference "<原始QP2串>" --output-dir .`，产出 `input.json` 与带 SHA256 的 `confirmation.json`。两者不一致时 `quote.py` 会拒绝计算，这是设计行为，不要去改记录。
5. **汇率**：QP2 末尾 `R` = 实时，取中国银行美元现汇买入价（[牌价页](https://www.boc.cn/sourcedb/whpj/)，记录牌价发布时间与查询时间）；`F` = 用户填的固定汇率，直接采用，不联网。未取到汇率就停，不要用估值。
6. **计算与交付**：`scripts/quote.py`（带 `--confirmation`）→ `result.json`；`scripts/render_report.py` → 四段汇报；`scripts/render_excel.py` → 三分页 Excel（分项报价 / 参数与汇率 / 计算过程）。汇报顺序固定：总报价 → 本次采用参数 → 总价计算过程 → 最终分项报价及计算表。

## 表单结构（固定）

| 区域 | 内容 |
|---|---|
| 成本区 | 成本合计（只读，脚本填入）、成本口径、进项税率、假定退税率 |
| 利润率区 | 目标利润率、佣金率 |
| 不可退税项目 | 全项目勾选清单 + 自动合计金额（只读） |
| 特殊加价率 | 6 个槽位，一行一条（左列加价率、右列适用项目），4/5/6 接在 1/2/3 下方。链式解锁：3 填了才激活 4，4 填了才激活 5，5 填了才激活 6；清空则下游重新灰显（已填内容的槽位保持可用，不清数据）。每槽=一个加价率 + 多选适用项目 |
| 其他 | 额外费用、分摊规则、报价币种、汇率方式、固定汇率、价格口径、补充说明 |

提交串固定为 QP2 十三字段，`MAXLEN=500`，超长前端拦截。groups 的顺序就是槽位顺序：第 i 个 token 对应"特殊加价率 i"，比例后接按 `draft.items` 顺序的 base64url 位图。

槽位锁定：`lock()` 逐条判断，第 i 条（i≥4）可用 = 上一条比率非空 或 本条已有比率/已选项目；1–3 恒可用。不清数据，只切换 `input.disabled` 与勾选框；灰显时 summary 显示"填写上一条加价率后启用"。

## 呈现契约（唯一形式，机读绑定）

[contracts/form-presentation.md](contracts/form-presentation.md) 是契约本体，写明唯一介质、禁止项与重签流程；其中一段是机器读取的键值，`scripts/check_contract.py` 与 `render_form.py` 的 `contract_guard()` 都会逐项比对模板、锁文件与样例渲染，不符即 `CONTRACT MISMATCH`，不产出、不发送。

| 契约项 | 值 |
|---|---|
| 围栏 | ` ```widget quotation-confirm-form-v4 ` |
| 整块上限 | 12,000 字符 |
| 加价率槽位 | 6 个，一行一条，4/5/6 链式解锁 |
| 生成器 | `scripts/render_form.py`（唯一） |
| 校验 | `scripts/verify_form.py` + `scripts/check_contract.py` |

禁止项（出现任一即违约）：另发 HTML/图片/PDF/纯文本表格；手打或改写代码块；更换围栏标识；把 `<style>`／`<script>` 拆到围栏外或在块内出现第二个围栏；改模板不重签就发送；超 12,000 字符硬发；改动槽位数、链式解锁规则或 QP2 字段顺序。

**发送形态红线**——下列形态都不会报错，只会让宿主把整块当普通代码块显示成源码：

| 形态 | 结果 |
|---|---|
| 围栏行前有空格、全角空格或制表符 | 变成缩进代码块，显示源码 |
| 整块放进列表项（`- `、`1. `）或引用块（`> `） | 显示源码 |
| 整块外面再套一层代码块 | 显示源码 |
| 围栏行与 `<style>` 写在同一行 | 不渲染 |
| 围栏标识写成 `html`、`widget`（无 id）、`v4` 拼错 | 显示源码 |
| 整块超过 12,000 字符 | 整块不显示 |

因此围栏行必须顶格、单独成行、与 `form.txt` 逐字节一致；整块前后不加任何文字、符号或空行以外的东西。

违约处置：不发送、不"补一句说明"；已发出的表单被发现不符契约，直接声明作废并重发一份。

跨客户端说明（如实告知，不自行换介质）：Widget 只由当前宿主渲染，转发或复制到别处会退化成源码。这种情况只能靠"对方在自己的会话里用同一套渲染器生成同形状表单"解决，不能用另做一份 HTML 绕过契约。

## 稳定性锁

1. **模板指纹** `templates/confirm-form.sha256`：模板字节被改过就报 `template changed`。
2. **形状指纹** `templates/form-shape.sha256`：项目数据归一化后算形状哈希；不同项目、不同行数必须是同一形状，漂移即报 `shape differs`。
3. **渲染自检** `verify_form.check_block`：围栏首行、闭合、仅两个围栏、≤12,000 字符、占位符无残留、括号配平、`node --check`、payload 可解析。

改模板/改形状必须显式重签：`python scripts/render_form.py --bless --draft draft.json --output form.txt`（`--bless` 会同步重签契约哈希），随后跑全量测试 `python -m unittest test_grouped test_workflow test_submission`（34 项）。

## 宿主解析事实（从客户端安装包 `app.asar` 中取得的实际实现）

| 事实 | 内容 |
|---|---|
| 解析语法 | `(?<=^|\n)` + ` ```widget ` + `[ \t]+` + `[A-Za-z0-9_-]+` + `[^\n]*\n` + 正文 + `(?:\n```[^\S\n]*(?=\n|$)\|$)` |
| 标识符 | 允许字母、数字、下划线、连字符（`quotation-confirm-form-v4` 合规）；`title="..."` 是旧语法 |
| 位置 | 围栏必须位于消息开头或换行之后（前面不能紧跟文字） |
| 分隔符 | `widget` 与 id 之间只能是 ASCII 空格或制表符（全角空格、不换行空格会失败） |
| 闭合 | 必须是独立一行、只含 ``` ，其后只允许空格/制表符 |
| 降级 | `unknownProtocol` / `malformedPayload` / `rendererError` → **raw-text（显示源码）**；`streaming` → `render-partial` |

由此可判：**显示源码** ≠ 文件有问题，也 ≠ 超长（超长是整块不显示）。它意味着块已被切出但渲染这一步降级，或整条消息没被当作 widget 解析（围栏行不符合上表）。

## 计算口径

- 可退税成本 = 合计 − 不可退税；假定退税 = Σ 成本 ÷ (1+进项税率) × 退税率；退税后成本 = 合计 − 退税 + 额外费用。
- 总报价 = 退税后成本 ÷ (1 − 利润率 − 佣金率)；固定项先算，余额按原成本比例分摊；实际利润率必须落在容差内。
- `source_kind=supplier_cost` 才可加价；`sales_quote` 一律停止加价。
- 服务/运输类（设计、运输、安装调试）退税按 0 处理；勾入不可退税即等于退税 0。

## Pitfalls

- 步骤2 排障先分症状：
  - **显示成源码**（用户看到 `<style>`、`#qf{...}`）：`python scripts/verify_sent.py` 直接给出实际发出的首行与判定，**不要向用户索取截图或让他手工取证**。`SENT BROKEN` ⇒ 按打印的 `fence line` 改正后重发；`SENT OK` 却仍显示源码 ⇒ 属于宿主渲染降级（见上表），如实说明并让用户升级客户端或在同一客户端的另一个会话重试，**不要改包、不要换介质**。
  - **整块消失**：总字符数超 12,000，宿主直接丢弃。
- 报告或排障说明中，**必须**给出两行原始事实：`verify_form` 的 `FORM OK/NOT SENDABLE`、`verify_sent` 的 `SENT OK/SENT BROKEN` 与其打印的 `fence line`。缺这两行就只是描述现象，不能作为结论。
- 步骤2：不要把 `<style>`／`<script>` 拆出围栏，也不要在代码块内嵌套第二个围栏，渲染会失败。
- 呈现：任何"另做一份 HTML 给对方"的提议都违反契约。对方看不到表单时，按上文跨客户端说明处理，不换介质。
- 分摊：槽位把多数项目钉在低加价时，通用分摊系数会被推到极端值（曾出现 6.03）。总价对但分项不可解释，须在回复中明确指出并请用户复核分配。

## Fallback / Edge Cases

- **QP2 超长**：前端拦截并提示精简补充说明；后端拒绝处理。
- **汇率失败**：暂停计算，请用户切固定汇率；不使用缓存估值。
- **金额冲突**：明细与合计差异 >1 元时在回复中列明差额并请用户指定口径，不自行取舍。
- **项目过多**：超过表单容量时报错，改为"工序/子系统"级汇总后重做，不拆成两张表。
- **吨单价与总价不符**：表内四位小数单价是显示值，成本以总价为准；不强行凑数，重量与单价留 metadata 备查。
