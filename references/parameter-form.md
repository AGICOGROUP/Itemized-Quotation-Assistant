# 对话内分类表单契约

新任务统一使用 `templates/confirm-form.html`（由 `render_form.py` 填充，形状唯一、不可手写改造）。保留双列全局参数：成本、税费、佣金、币种、汇率、额外费用及补充说明全部放在上方；整体目标利润率与下方特殊规则之间用一条 hr 分割线；以 h3 显示“整体目标利润率”“特殊加价率 1–6”。每个特殊加价率上方填比例，下方点击展开勾选多个项目；固定六个槽位，一行一条（左列比率、右列适用项目），4/5/6 接在下方；链式解锁：3 填了激活 4，4 填了激活 5，5 填了激活 6，清空则下游重新灰显（已有内容的槽位不灰、不丢数据）。不提供手工“添加”按钮。全部在当前对话的同一个表单中，只用一个“确认参数并计算”按钮。预勾选项目来自 draft 的 categories/item_settings，未勾选的自动归入通用分摊。Accio 与 Codex 通过各自的入口显示同一张表。宿主无法内嵌时，允许打开由同一生成器输出的离线表单，确认后将提交码发回原对话。

## 草稿

每次从本次资料建立唯一case_id。items每行必须包含唯一稳定id、name、cost（十进制元字符串）；保留来源与数量信息。仅明细计价，小计和父级不重复计入。缺价、总额冲突及不明计价范围仍须解决。

fields包含cost_total（只读当次合计）、cost_basis（人民币；可退税项含税）、margin（25）、commission（7.5）、vat（13）、refund（13）、allocation（按厂家原成本比例分摊）、currencies（人民币、美元）、fx_rule（实时：中行美元现汇买入价）、extra_cost（0）、summary（选填）。每项有key、label、value、type、required，可有readonly/max/options。数字采用number，百分比填25而非0.25，税率上限100。同时提供 source_kind。只有确认是厂家采购成本才预填 supplier_cost，未知留空由用户填写。

categories是类别数组，每个对象有id、name、mode、markup，例如：
```json
[{"id":"general","name":"通用分摊类","mode":"proportional","markup":"0"},
 {"id":"markup15","name":"成本加价类","mode":"markup","markup":"15"},
 {"id":"original","name":"原价类","mode":"original","markup":"0"}]
```

通用分摊类承担整体销售利润目标，实际加价率经计算求出，绝不是成本加价25%。markup类别共用成本加价率，original类别原价。支持增加不同加价率及其适用项目；清空该类项目即可不使用该类。按本次用户规则预分类；原案例钢结构/耐火材料15%、设计/编程0%只作匹配明确时的建议，不凭合并项目局部关键词硬套。

item_settings与items一一对应，稳定ID不能重复或遗漏：
```json
{"item_id":"row-1","category_id":"general","override_mode":"inherit","override_value":"","tax_mode":"global_refund","vat":"13","refund":"13"}
```

override_mode可为inherit（跟随类别）、markup（独立成本加价百分比）、fixed（独立人民币报价）；后两者填写override_value。已有单项覆盖转换为独立特殊类型预选该项目，固定报价明确标元。前端按稳定ID勾选，不要求手输名称；勾选到另一类型自动从原类型移除，取消后回到通用类。同一项仅有一个有效类型，后端仍拒绝重复或漏项。0%表示原价，不另设原价项目区。无所选项目的类型不生效。不可退税项目也以预填名称列表编辑，金额自动汇总。所有全局参数直接显示，保留原双列布局，不隐藏到更多参数。

tax_mode独立于加价分类：global_refund采用全局税率；none不退税；custom用本行vat/refund。未知范围留空待确认。不得按类别或名称强推税务，不可将原案例419万元当新项目默认。不可退税金额按行汇总，不再显示旧nonrefundable/steel_markup/refractory_markup/original_items/nonrefundable_items控制项。

## 一次确认

运行 `render_form.py --draft <draft.json> --output <持久目录/form.txt>`。脚本产出**已带围栏的完整代码块**（首行 ```widget quotation-confirm-form-v4），把该文件全文原样贴入回复即可，不要二次加工。整块长度超过 12,000 字符时脚本报错且不产出文件——此时按提示减少行数或改用汇总口径，绝不硬发。

汇率在同一次确认里可选：`汇率方式`下拉为“实时：中行美元现汇买入价”（默认）或“手动固定汇率”，选固定时填写CNY/USD数值；draft里的`fx_rule`不能设为只读，否则改汇率会被拒绝。

点击确认用`window.__widgetSendMessage`提交，**消息必须≤500字符**：宿主实现为`if(typeof t!=='string'||t.length>500)return;`，超长静默丢弃、不触发新回合，表现为“显示已提交但没有下一步”。因此不得提交JSON，统一提交QP1紧凑串：`QP2|case_id|margin|commission|vat|refund|extra_cost|source_kind|summary_b64|groups|nonrefund_bm|fx_mode|fx_rate`（`fx_mode`为`R`实时或`F`固定，`F`时`fx_rate`必填；旧`QP1`仍可解码，视为实时）；groups为`[F]<比例>:<bitmap>`分号连接（F表示固定报价），bitmap为按draft.items顺序的base64url位图。编码前先算长度，超限在表单内报错，不发送。

agent收到QP1/QP2串后用`scripts/parse_widget_submission.py`还原完整submission.json，其中`fx`给出`mode`与`rate`，并已把`fx_rule`写成可读文本。报告之外还要用`scripts/render_excel.py`输出xlsx分项报价表。widgetState仅保存草稿，不等于确认；API缺失或长度超限明确显示未提交，不虚构成功。技能编辑、样式反馈不构成报价确认。

收到真实提交后保存submission.json，用prepare_input.py绑定draft和真实消息引用，生成input.json及confirmation.json（含时间和SHA256）。保留完整提交。以实际提交类别及单项设置为准，不回退默认。补充梗概非空必须逐条落实supplement_resolution；超出支持口径需适配，不能忽略。

确认后再取当次汇率、核算与校验。无分摊基数、固定报价超过总价或无法实现目标时不擅改类别比例，不输出声称达到目标的正式报价。最后分项表必须显示原价、规则、代入公式、人民币及美元报价。旧inline-form和item_rules只用于旧任务兼容，新任务默认分类表单。






