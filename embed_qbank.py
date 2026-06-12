"""Embed questionnaire.json into the explorer template's QBANK sentinel block.

The AS engagement question bank (240 senior-engineer questions, 12 domains) is static
knowledge, so it ships INSIDE cisco_toolkit/blast_radius_explorer.html rather than per
snapshot. Re-run this after editing questionnaire.json:

    python embed_qbank.py

CRLF-preserving (newline=""), and any literal '</' in the data is escaped to '<\\/' so
the JSON can never break out of the <script> block (same rule write_html_explorer uses).
"""

import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "questionnaire.json")
TPL = os.path.join(ROOT, "cisco_toolkit", "blast_radius_explorer.html")
START = "/* ===QBANK-START=== */"
END = "/* ===QBANK-END=== */"

REQUIRED = {"id", "domain", "phase", "question", "rationale", "evidence", "red_flag", "go_no_go"}


def main() -> None:
    with open(SRC, encoding="utf-8") as f:
        bank = json.load(f)
    if not isinstance(bank, list) or not bank:
        raise SystemExit("questionnaire.json must be a non-empty JSON array")
    for i, item in enumerate(bank):
        missing = REQUIRED - set(item)
        if missing:
            raise SystemExit(f"item {i} ({item.get('id', '?')}) missing keys: {sorted(missing)}")
    payload = json.dumps(bank, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")

    with open(TPL, encoding="utf-8", newline="") as f:
        html = f.read()
    a = html.index(START) + len(START)
    b = html.index(END)
    html = html[:a] + "\nconst AB_QBANK=" + payload + ";\n" + html[b:]
    with open(TPL, "w", encoding="utf-8", newline="") as f:
        f.write(html)
    print(f"embedded {len(bank)} questions / {len({i['domain'] for i in bank})} domains "
          f"({len(payload):,} bytes) into {os.path.relpath(TPL, ROOT)}")


if __name__ == "__main__":
    main()
