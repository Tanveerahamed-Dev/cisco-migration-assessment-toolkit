---
description: Maximum-rigor mode — escalated thinking, research-first, persist until verified.
argument-hint: [the task to do at full power]
model: fable
---
ultrathink.

Operate at maximum rigor on the task below and do not stop until it is fully
done and proven. If no task is given after this command, ask me for one.

TASK: $ARGUMENTS

Rules of engagement:
- RESEARCH FIRST: investigate the actual code before proposing anything —
  graphify-first for codebase questions, cite file:line. Show me your plan and
  the files you'll touch before editing.
- THINK HARD: reason through edge cases and failure modes, not just the happy
  path, before any non-trivial decision.
- PERSIST: keep going until it's complete and verified. Don't hand back partial
  work, don't stop at the first plausible answer, and don't ask me to do steps
  you can do yourself.
- VERIFY OR IT DIDN'T HAPPEN: run the relevant tests / build / golden and
  from the main checkout root run `py -3.12 -I -B tools/graphify_guarded.py update .`, and show me the real output. If it fails, fix and re-run
  until green. Never imply success you didn't observe.
- GROUND EVERYTHING: make no claims from memory that you can verify in seconds;
  label anything genuinely unverified as "unverified."
- STAY IN SCOPE: keep diffs surgical and in the surrounding code's style. Flag
  out-of-scope issues, don't fold them in.
- GUARDRAILS: don't commit, push, or open PRs unless I ask; branch first if I'm
  on main; don't bump pyproject versions except at release-tag time.
- BE STRAIGHT: lead with the answer, recommend don't survey, disagree when I'm
  wrong and say why.
