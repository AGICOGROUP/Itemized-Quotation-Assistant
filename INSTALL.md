# Installation and self-check

## 1. Place it in the skills directory

Copy this repository into the target agent's skills directory, keeping the folder name `export-project-quotation`:

```
Windows      %USERPROFILE%\.accio\accounts\<account>\agents\<agent>\agent-core\skills\export-project-quotation\
macOS/Linux  ~/.accio/accounts/<account>/agents/<agent>/agent-core/skills/export-project-quotation/
```

The final layout must be `export-project-quotation/SKILL.md`, plus `scripts/`, `templates/`, `contracts/`, `references/` and `agents/` beside it.

## 2. Dependencies

| Dependency | Purpose | If missing |
|---|---|---|
| Python 3.9+ | all scripts (standard library only) | nothing runs |
| `openpyxl` | three-sheet Excel export | only the export phase is blocked; `preflight.py --phase excel` installs it, and calculation plus report still finish |
| `node` | JavaScript syntax self-check (`node --check`) | that check is skipped; the other gates still run |

## 3. Self-check (run this first)

```bash
cd export-project-quotation/scripts
python preflight.py --phase form                                  # expect PREFLIGHT OK (form)
python check_contract.py                                          # expect CONTRACT OK
python -m unittest test_grouped test_workflow test_submission     # expect Ran 34 tests ... OK
```

- The first command checks the installed file set, the contract, directory write access and the Python version, and stops the run if anything is missing.
- The second verifies the fence identifier, size cap, slot count, template hash and shape hash in the contract against the template file, both lock files and a live sample render.
- The third must end with `Ran 34 tests ... OK`.

If either fails, the template and its locks disagree (incomplete or modified package). **Do not use it** — fetch a fresh copy.

## 4. Fixed workflow

```bash
# 0) gate: nothing runs until the form phase reports ready
python scripts/preflight.py --phase form --output-dir .
# 1) render the parameter confirmation form (nothing is written if the locks disagree)
python scripts/render_form.py --host accio --draft draft.json --output form.txt
python scripts/verify_form.py --form form.txt      # expect FORM OK
# 2) send form.txt verbatim as its own reply; then confirm what was actually sent
python scripts/verify_sent.py --form form.txt      # expect SENT OK
# wait for the user to return the QP2 string
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
python scripts/preflight.py --phase excel          # expect PREFLIGHT OK (excel); installs openpyxl if needed
python scripts/render_excel.py  --result result.json --output quote.xlsx
```

## 5. Three hard rules

1. Exactly one presentation, always produced by the generator: `render_form.py --host accio` for the `quotation-confirm-form-v4` widget block, `--host codex` for the inline fragment, `--host browser` for the offline copy of the same form. Hand-typing, editing or re-typesetting any of them is forbidden.
2. No substitute medium. An image, PDF, prose table or ad-hoc HTML page may never stand in for the form; the offline HTML is allowed only as the `--host browser` output of the same template, unchanged.
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
