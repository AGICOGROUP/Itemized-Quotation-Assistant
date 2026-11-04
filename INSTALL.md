# Installation and self-check

## 1. Place it in the skills directory

Copy this repository into the target agent's skills directory, keeping the folder name `export-project-quotation`:

```
Windows      %USERPROFILE%\.accio\accounts\<account>\agents\<agent>\agent-core\skills\export-project-quotation\
macOS/Linux  ~/.accio/accounts/<account>/agents/<agent>/agent-core/skills/export-project-quotation/
```

The final layout must be `export-project-quotation/SKILL.md`, plus `scripts/`, `templates/`, `contracts/` and `references/` beside it.

## 2. Dependencies

| Dependency | Purpose | If missing |
|---|---|---|
| Python 3.9+ | all scripts (standard library only) | nothing runs |
| `openpyxl` | three-sheet Excel export | Excel step fails only; calculation and report still work |
| `node` | JavaScript syntax self-check (`node --check`) | that check is skipped; the other gates still run |

Install the Excel dependency with `pip install openpyxl`.

## 3. Self-check (run this first)

```bash
cd export-project-quotation/scripts
python check_contract.py
python -m unittest test_grouped test_workflow test_submission
```

- The first command must print `CONTRACT OK`. It verifies the fence identifier, size cap, slot count, template hash and shape hash in the contract against the template file, both lock files and a live sample render.
- The second must end with `Ran 34 tests ... OK`.

If either fails, the template and its locks disagree (incomplete or modified package). **Do not use it** — fetch a fresh copy.

## 4. Fixed workflow

```bash
# 1) render the parameter confirmation form (nothing is written if self-check fails)
python scripts/render_form.py --draft draft.json --output form.txt
python scripts/verify_form.py --form form.txt      # expect FORM OK
python scripts/check_contract.py                   # expect CONTRACT OK
# 2) paste form.txt verbatim into the chat; wait for the user to return the QP2 string
# 3) decode the confirmation
python scripts/parse_widget_submission.py --draft draft.json --message "@msg.txt" --output submission.json
# 4) bind inputs (produces confirmation.json with a SHA256 of input.json)
python scripts/prepare_input.py --draft draft.json --submission submission.json \
       --user-message-reference "<QP2 string>" --output-dir .
# 5) exchange rate: R = live (Bank of China USD spot buying rate), F = user-fixed rate
python scripts/quote.py --input input.json --confirmation confirmation.json \
       --rate 6.672 --rate-source "https://www.boc.cn/sourcedb/whpj/" \
       --rate-type "USD spot buying rate" --rate-time "<quote time>" --rate-query-time "<fetch time>" --output result.json
# 6) deliverables
python scripts/render_report.py --result result.json --output report.md
python scripts/render_excel.py  --result result.json --output quote.xlsx
```

## 5. Three hard rules

1. Exactly one presentation: the `quotation-confirm-form-v4` widget block produced by `render_form.py`, copied verbatim. Hand-typing or rewriting it is forbidden.
2. No second medium: no HTML page, image, PDF or plain-text table may replace the form.
3. Any template or shape change requires an explicit `--bless` re-sign plus the full test run. Otherwise rendering is refused by the locks — that is intended behavior, not a fault.

## 6. File integrity

`MANIFEST.sha256` records a checksum for every file. Verify from the repository root:

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
