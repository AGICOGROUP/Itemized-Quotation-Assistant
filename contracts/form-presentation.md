# 表单呈现契约（唯一形式）

本文件是被脚本读取的**契约**，不是说明文。`scripts/check_contract.py` 每次运行都会把下面的键值与模板文件、锁文件逐项比对，任一不符即报 `CONTRACT MISMATCH` 并停止产出表单。

## 唯一允许的呈现方式

表单在对话中的呈现形式只有一种：由 `scripts/render_form.py` 生成、首行为 `widget quotation-confirm-form-v4` 的 widget 代码块。除此之外没有第二种介质。

## 机读绑定（改动即视为违约）

```
FORM_CONTRACT=1
FENCE_ID=quotation-confirm-form-v4
MAX_CHARS=12000
SLOTS=6
TEMPLATE_SHA256=20d5a7e4647da052b5c14aa630b085ada129fbc74e1065841a1c3bac6b228edf
SHAPE_SHA256=a6c4008bedb4b15d59cae5babf1f8833fab3e58d524a19eb918761dba05a7978
TEMPLATE=templates/confirm-form.html
GENERATOR=scripts/render_form.py
VERIFIER=scripts/verify_form.py
```

## 禁止项（出现任一即为违约，不得发送）

1. 另存或另发 HTML 页面、图片、PDF、纯文本表格等替代介质。
2. 手打、重排、精简、改写渲染器产出的代码块；只允许整段复制文件内容。
3. 更换围栏标识符，或使用裸 ` ```widget `、` ```html ` 等其它标识。
4. 在代码块外拆出 `<style>`／`<script>`，或在块内出现第二个围栏。
5. 改动 `templates/confirm-form.html` 后不重签锁就发送。
6. 单块超过 12,000 字符仍强行发送（必须减行或改汇总口径）。
7. 槽位数量、链式解锁规则、QP2 字段顺序的任何变动。

## 违约时的处置

- `render_form.py` 报 `template changed` / `shape differs` / `failed self-check` → 不产出文件，按提示重签或修模板，再跑全量测试。
- 已发出的表单被发现不符契约 → 立即声明该表单作废，取回文件重发一份，不做"补一句说明"式修补。

## 重签流程（唯一合法改形状的路径）

```
python scripts/render_form.py --bless --draft draft.json --output form.txt
python scripts/check_contract.py --contract contracts/form-presentation.md   # 用新哈希更新上面的键值
python -m unittest test_grouped test_workflow test_submission
```

重签后必须同步更新本文件的 `TEMPLATE_SHA256` 与 `SHAPE_SHA256`，否则 `check_contract.py` 会一直报不一致。
