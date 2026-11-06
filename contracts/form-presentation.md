# 报价确认表呈现契约

唯一模板为 templates/confirm-form.html，由 scripts/render_form.py 生成。三个入口使用同一份样式、字段、六个加价槽和 QP2 协议。Accio 输出原 widget 围栏块，Codex 输出内嵌片段，宿主不支持或 Accio 超限时输出同一张可离线打开的表。不得手写或重排输出。

以下键值由校验器读取。MAX_CHARS 是 Accio 围栏块上限，TEMPLATE_SHA256 在统一 CRLF 为 LF 后计算。SHAPE_SHA256 基于去除案例数据的标准形态。校验不通过时，停止生成并从发布包恢复文件，禁止自动重签。

```
FORM_CONTRACT=1
FENCE_ID=quotation-confirm-form-v4
MAX_CHARS=12000
SLOTS=6
TEMPLATE_SHA256=2a7c685c1349f773e3d56d0c97752c87e4d09478ec4d60d62c42f21a9ba937d2
SHAPE_SHA256=eab8d88e9f76571078a3022eb977bbff37456f9261870e9427e44a01699d05f8
TEMPLATE=templates/confirm-form.html
GENERATOR=scripts/render_form.py
VERIFIER=scripts/verify_form.py
```

维护者确认模板变更后，用 `python -X utf8 scripts/render_form.py --bless --draft <新测试草稿> --output <测试表单>` 重签，再运行 `python -X utf8 scripts/check_contract.py` 和回归测试。

Accio 发送后使用 verify_sent.py 按本次表单比较原始回复。该结果无法证明用户界面已渲染。最终以用户实际点击和同一案例的 QP2 回传为准。
