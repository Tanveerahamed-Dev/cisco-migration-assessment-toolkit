---
description: Morning briefing — assemble "what to look at today" from local repo state (rot, open items, lessons-promotion queue, quality scorecard). Read-only, no egress. Phase-0 of the autonomous-brain plan.
argument-hint: (none)
---
Produce the engineer's morning briefing — the "every time I log in, something good" digest.

1. Run: `bash .claude/hooks/morning-briefing.sh`
2. Present its output to the user as the briefing. Then add ONE line — "First move:" — naming the single highest-impact item from the "What to look at today" list, using your judgment about impact and effort.
3. This is a READ-ONLY digest: do NOT fetch anything external, do NOT write to devices, do NOT modify project state beyond the dated file the script itself writes under `docs/briefings/`.
4. If the script errors or prints nothing, report exactly what it printed — do NOT improvise a briefing from memory (grounded-only; an invented briefing is worse than none).
