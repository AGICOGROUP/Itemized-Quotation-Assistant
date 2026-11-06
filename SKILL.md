---
name: "[Harvest] 出口项目分项报价助手"
description: 根据厂家成本表或截图制作出口项目分项报价。先显示可编辑的参数确认表，收集分项加价和退税范围，再按用户确认的参数计算并导出报告和 Excel。支持 Accio 与 Codex，优化了表单兼容性及生成速度。
created_by: main_agent
---
## Workflow
1. **预检和草稿**
确定当前对话宿主。Accio 使用 accio，支持对话内 Visualize 的 Codex 使用 codex，其他宿主使用 browser。同一案例使用唯一的短 ASCII case_id 和同一份 draft.json。
运行 `python -X utf8 scripts/preflight.py --phase form --output-dir <案例工作目录>`。看到 PREFLIGHT OK 才生成表单。Python 3.9+ 必需，Node 可选，Excel 依赖到导出时检查。预检验证安装文件、模板契约和案例目录，无法检查宿主是否实际显示了表单。遇到损坏文件，重新解压完整发布包，保留任务草稿。
按 [输入兼容规范](references/input-compatibility.md) 从本次文件转录，核对明细和合计。明细缺失或合计冲突时先解决。吨单价是舍入后的展示值时，以经确认的总价列计算，重量和显示吨单价留作备查。标题写着报价不能证明是厂家采购成本。草稿保留 `fields`、`items`、`categories`、`item_settings` 及未解决的来源问题。字段契约见 [参数参考](references/parameter-form.md)。未知价格口径填空；税率、利润率和佣金仅按本次明确的值或业务约定预填。相同加价率可合并成一组，保留独立项目选择。

2. **生成并显示确认表**
使用唯一生成器和锁定模板。生成器校验契约、结构、金额合计、分组及宿主长度限制。正常运行无需额外重复执行 check_contract.py 或 verify_form.py。
- Accio：`python -X utf8 scripts/render_form.py --host accio --draft <草稿> --output <form.txt>`。将文件里的整个 widget 块原样作为独立回复发出，围栏顶格，前后不要包裹列表、引用、代码块或正文。若宿主日志可读，运行 `python -X utf8 scripts/verify_sent.py --form <form.txt> --conversation <当前日志>`。不知道日志路径时可省略 `--conversation`，脚本按本次 case_id 查找。SENT OK 只表示回复里的表单块与生成文件逐行一致，不证明界面已渲染；块外另带正文时仍判 SENT OK 并提示行数，下次只发块本身。SENT UNVERIFIED 时不能声称已显示。SENT BROKEN 时用同一份文件重发一次。
- Codex：`python -X utf8 scripts/render_form.py --host codex --draft <草稿> --output <线程可读取的可视化目录>/quotation-confirmation.html`。按 Visualize 的内嵌引用语法显示生成的文件，使用实际绝对路径。按钮走 Codex 的确认消息入口，实际收到 QP2 才算确认。
- 当前宿主不支持内嵌、显示为源码、回复重发后仍显示失败，或 Accio 表单超过长度上限时，执行 `python -X utf8 scripts/render_form.py --host browser --draft <草稿> --output <quotation-confirmation.html>`，让用户打开同一份表单，点确认后将生成的 QP2 提交码发回原对话。文件离线可用。保留原清单和 case_id，不为满足长度限制拆分表单或合并不同计价的项目。
表单继续使用原样式：上方全局参数、独立的不可退税项目、多选加价项目、六个加价槽。4–6 槽由前一槽解锁，已有内容保留。一个项目只能处于一个加价组，未分组项目按原成本比例分摊，0% 组按原价。加价分组和退税范围独立。不要手写、修改或替换模板，不把源代码发给用户当作表单。

3. **接收并绑定确认**
只有实际收到用户提交的 QP2 才继续。使用本次草稿执行 `python -X utf8 scripts/parse_widget_submission.py --draft <草稿> --message @msg.txt --output submission.json`。若消息带有说明文字，只取完整 QP2 行。不得替用户生成确认或复用历史提交。QP2 上限 500 字符，补充说明过长时由用户精简。
用 `python -X utf8 scripts/prepare_input.py --draft <草稿> --submission submission.json --user-message-reference <真实确认引用> --output-dir <案例目录>` 生成 input.json 和带 SHA256 的 confirmation.json。有来源问题时在草稿的 source_resolution 记录真实确认依据。客户已有售价不得叠加利润。非空补充说明在计算前逐条落实并记录 supplement_resolution，保证 input.json 与 confirmation.json 的绑定一致。

4. **汇率、计算和导出**
实时方式查询中国银行美元现汇买入价，记录来源、类型、牌价发布时间和查询时间。查询失败时等待用户改用固定汇率。固定方式采用确认值。
用 quote.py 绑定输入和确认后生成 result.json。成本按行计算假定退税，服务和运输按已确认的不退税范围处理。总报价等于退税后成本加额外费用，再除以 1 减利润率及佣金率。固定及特殊加价项先算，余额按原成本比例分摊。分摊系数异常时在报告中说明并由用户复核。
用 render_report.py 输出总报价、确认参数、总价推导和最终明细。导出 Excel 前执行 `python -X utf8 scripts/preflight.py --phase export --output-dir <案例目录>` 检查环境。用 export_excel.py 生成带公式的 Excel 文件。报告与 Excel 必须包含 case_id、确认哈希和生成时间戳。

## Suggestions
- 若用户提供的成本表格式混乱，优先使用 OCR 工具提取后人工校对，再进入预检流程。
- 对于长期合作客户，可将常用汇率和利润率存入记忆，减少每次确认的步骤。
- 生成表单前，先检查草稿中是否有未解决的来源问题，避免后续反复修改。

## Fallback / Edge Cases
- 若 QP2 提交码解析失败，检查消息中是否包含多余字符，尝试手动提取完整 QP2 行。
- 若 Excel 导出失败，检查是否安装了 openpyxl 库，或尝试以 CSV 格式导出数据。
- 若宿主不支持 widget 显示，立即切换到 browser 模式生成离线 HTML 表单。

## Pitfalls
- 步骤 2：Accio 宿主下表单长度超限会导致显示失败，务必提前检查并切换 browser 模式。
- 步骤 3：不得复用历史 QP2 提交码，每次确认必须基于当前草稿生成新的提交码。
- 步骤 4：汇率查询失败时不要随意猜测，必须等待用户提供固定汇率或重试查询。
