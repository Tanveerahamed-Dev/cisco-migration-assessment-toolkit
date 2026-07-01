---
description: Regenerate the deliverable set (workbook, explorer, runbook, design, MOP, CRD, engagement, archreview, ops handbook, deck) from an existing snapshot, then QA it.
argument-hint: [snapshot.json | output stem]
---
Regenerate the deliverables from an existing run — no re-collection.

INPUT: $ARGUMENTS

1. Regenerate via the engine from the snapshot (use `--no-collect` against the matching collection, or the snapshot directly). The generators: workbook (`excel.py`), explorer (`html.py`), runbook (`runbook.py`), design (`design.py`), MOP (`mop.py`), CRD (`crd.py`), engagement (`engagement.py`), archreview (`archreview.py`), ops handbook (`ops.py`), deck (`deck.py`). Toggle off any you don't need: `--no-html` (explorer), `--no-docx` (runbook), `--no-pptx` (deck), `--no-design`, `--no-mop`, `--no-crd`, `--no-engagement`, `--no-opshandbook`, `--no-archreview`; the workbook is always produced.
2. Then hand the regenerated set to the **deliverable-qa-reviewer** subagent for an independent consistency / single-source-of-truth / hallucination check before declaring them ready.

Report what was produced (paths) and the QA verdict per artifact. Don't bump the pyproject version.
