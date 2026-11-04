# 安装与自检

## 1. 放进技能目录

把本仓库内容放进目标 Agent 的技能目录，目录名保持 `export-project-quotation`：

```
Windows   %USERPROFILE%\.accio\accounts\<account>\agents\<agent>\agent-core\skills\export-project-quotation\
macOS/Linux  ~/.accio/accounts/<account>/agents/<agent>/agent-core/skills/export-project-quotation/
```

最终结构应为 `export-project-quotation/SKILL.md`、`.../scripts/`、`.../templates/`、`.../contracts/`。

## 2. 依赖

| 依赖 | 用途 | 缺失后果 |
|---|---|---|
| Python 3.9+ | 全部脚本（仅标准库） | 无法运行 |
| `openpyxl` | 导出三分页 Excel | 只有 Excel 失败，核算与报表正常 |
| `node` | 表单 JS 语法自检（`node --check`） | 该步降级跳过，其余校验照做 |

安装 `openpyxl`：`pip install openpyxl`

## 3. 自检（务必先跑）

```bash
cd export-project-quotation/scripts
python check_contract.py
python -m unittest test_grouped test_workflow test_submission
```

- 第一条应输出 `CONTRACT OK`：核对契约里的围栏标识、字数上限、槽位数、模板哈希、形状哈希与模板文件、两个锁文件、一次样例渲染是否一致。
- 第二条应输出 `Ran 34 tests ... OK`。

任一条不过：说明模板与锁文件不匹配（包不完整或被改过），**不要使用**，重新取包。

## 4. 固定流程

```bash
# 1) 生成参数确认表单（内部自检不过则不写文件）
python scripts/render_form.py --draft draft.json --output form.txt
python scripts/verify_form.py --form form.txt      # 期望 FORM OK
python scripts/check_contract.py                   # 期望 CONTRACT OK
# 2) 把 form.txt 全文原样贴进对话，等待用户回传 QP2 串
# 3) 解码确认
python scripts/parse_widget_submission.py --draft draft.json --message "@msg.txt" --output submission.json
# 4) 绑定输入（生成带 SHA256 的 confirmation.json）
python scripts/prepare_input.py --draft draft.json --submission submission.json \
       --user-message-reference "<QP2 串>" --output-dir .
# 5) 汇率：R=实时（中国银行美元现汇买入价），F=用户固定汇率
python scripts/quote.py --input input.json --confirmation confirmation.json \
       --rate 6.672 --rate-source "https://www.boc.cn/sourcedb/whpj/" \
       --rate-type "美元现汇买入价" --rate-time "<牌价时间>" --rate-query-time "<查询时间>" --output result.json
# 6) 交付
python scripts/render_report.py --result result.json --output report.md
python scripts/render_excel.py  --result result.json --output quote.xlsx
```

## 5. 三条硬规则

1. 表单只允许一种呈现：`quotation-confirm-form-v4` 的 widget 代码块，由 `render_form.py` 生成，整段复制，禁止手打或改写。
2. 禁止用 HTML 页面、图片、PDF、纯文本表格等第二种介质替代。
3. 改模板或改形状必须 `--bless` 重签并跑全量测试，否则渲染被锁拒绝（这是设计行为，不是故障）。

## 6. 文件校验

`MANIFEST.sha256` 记录全部文件校验值，可在仓库根目录核对：

```bash
python - <<'PY'
import hashlib, pathlib
for line in open('MANIFEST.sha256', encoding='utf-8'):
    h, rel = line.strip().split('  ', 1)
    p = pathlib.Path(rel)
    ok = p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() == h
    print('OK ' if ok else 'BAD', rel)
PY
```
