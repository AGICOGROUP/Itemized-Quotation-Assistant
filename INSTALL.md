# 分项报价助手 · 核心技能安装包

版本：2026-11-04（契约绑定版）

## 包含内容

```
export-project-quotation/
  SKILL.md                        流程与呈现契约（唯一形式）
  contracts/form-presentation.md  机读契约：围栏、字数上限、槽位数、模板与形状哈希
  templates/confirm-form.html     表单模板（唯一外观来源）
  templates/confirm-form.sha256   模板指纹锁
  templates/form-shape.sha256     形状指纹锁
  scripts/                        渲染、校验、解码、核算、报表、Excel、测试
  references/                     输入兼容与参数说明
  MANIFEST.sha256                 全部文件校验值
```

## 安装

1. 解压，把 `export-project-quotation/` 整个目录放到目标 Agent 的技能目录：
   Windows `%USERPROFILE%\.accio\accounts\<account>\agents\<agent>\agent-core\skills\`
   或 macOS/Linux `~/.accio/accounts/<account>/agents/<agent>/agent-core/skills/`
2. 依赖：Python 3.9+（标准库即可）；`openpyxl`（导出 Excel）；`node`（表单语法自检，缺了只会降级为跳过 `node --check`，其余校验照做）。
3. 安装后自检（在工作目录执行）：

```
cd export-project-quotation/scripts
python check_contract.py
python -m unittest test_grouped test_workflow test_submission
```

第一条应输出 `CONTRACT OK`；第二条应输出 34 项测试全部 `OK`。
任何一条不过，说明包里的模板与锁文件不匹配，不要使用，重新取包。

## 使用（固定六步）

```
python scripts/render_form.py --draft draft.json --output form.txt   # 生成表单，内部自检不过即不写文件
python scripts/verify_form.py --form form.txt                        # 应输出 FORM OK
python scripts/check_contract.py                                     # 应输出 CONTRACT OK
# 把 form.txt 全文原样贴进对话，等用户回传 QP2 串
python scripts/parse_widget_submission.py --draft draft.json --message "@msg.txt" --output submission.json
python scripts/prepare_input.py --draft draft.json --submission submission.json --user-message-reference "<QP2 串>" --output-dir .
python scripts/quote.py --input input.json --confirmation confirmation.json --rate <汇率> ... --output result.json
python scripts/report.py  → render_report.py / render_excel.py
```

## 三条硬规则

1. 表单只允许一种呈现：`quotation-confirm-form-v4` 的 widget 代码块，由 `render_form.py` 生成，整段复制，禁止手打改写。
2. 禁止用 HTML 页面、图片、PDF、纯文本表格等第二种介质替代。
3. 改模板或改形状必须 `--bless` 重签并跑全量测试；否则渲染会被锁拒绝，这是设计行为。

## 校验清单

见同目录 `MANIFEST.sha256`，可在解压目录执行：

```
python -c "import hashlib,pathlib;[print(hashlib.sha256(p.read_bytes()).hexdigest(), p) for p in sorted(pathlib.Path('.').rglob('*')) if p.is_file()]"
```
