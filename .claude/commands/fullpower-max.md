---
description: Absolute-full-power mode — unconstrained effort, dynamic agentic loop, mandatory web research, context-isolated fan-out, test-first, self-refuting verification, iterate until proven.
argument-hint: [the hard task to attack at absolute full power]
model: fable
---
ultrathink.

Attack the task below at maximum capability. Effort beats efficiency: spend
thinking, tool calls, web searches, and subagents freely — never trade depth or
correctness for budget. Stop only when every success criterion is met and
independently proven.

TASK: $ARGUMENTS

Run a DYNAMIC AGENTIC LOOP (evaluator-optimizer + orchestrator-workers +
autonomous act-verify-iterate), not a single pass:

0. ORIENT — for ongoing work, get up to speed first: skim git log, recent
   diffs, and relevant memory so you build on reality, not assumptions.

1. FRAME — restate the goal; write explicit, checkable SUCCESS CRITERIA (what
   "done AND correct" means). These are the loop's exit condition.

2. RESEARCH — always, before any claim:
   - Codebase: graphify-first, then read the real code; cite file:line. Any
     file / function / flag / API you recall from memory must be confirmed to
     EXIST before you rely on it.
   - External / current facts (libraries, versions, peer deps, standards,
     browser support, anything post-training): RUN WEB SEARCH — broad first,
     then narrow, multiple progressive queries, verify against primary sources,
     cite every source. Never answer from memory when the web can confirm it.

3. PLAN & DECOMPOSE — outline the approach and the files in scope. For risky or
   multi-file changes, show the plan and get my go before editing. Split into
   angles; offload heavy or noisy work — broad exploration, running tests,
   fetching docs, log triage — to PARALLEL SUBAGENTS (orchestrator-workers) so
   the verbose output stays in their context and only the conclusions return to
   yours. You own synthesis and de-duplication. Don't over-delegate: a single
   grep or file read is faster done directly than handed to an agent.

4. ACT — surgical changes in the surrounding code's style. For code, work
   test-first: write the test from expected input/output, watch it fail, then
   implement until it passes (let the test, not your own assertion, be the judge).

5. VERIFY BY REFUTATION — never grade your own work. A fresh pass (a
   verification subagent or a clean re-read of ground truth) must actively try
   to DISPROVE each claim before you report it. Run the real tests / build /
   golden / from the main checkout root `py -3.12 -I -B tools/graphify_guarded.py update .` and show the ACTUAL output. Where the proof is
   runtime behaviour, run it — don't infer.

6. EVALUATE -> REFINE — check against the step-1 criteria. If any fails, feed
   the SPECIFIC failure back and LOOP to step 4. Iterate until all hold, then
   ask once, honestly: "is this genuinely complete and correct?" Only then
   declare done.

Standing rules:
- PERSIST: no partial hand-backs, no first-plausible-answer stops, no asking me
  to do steps you can do yourself.
- GROUND & CALIBRATE: every external fact carries a source, every code claim a
  file:line; label the genuinely unverified "unverified." Don't rubber-stamp
  and don't over-escalate — resolve doubt against ground truth (the source, the
  run, the spec).
- VERIFY OR IT DIDN'T HAPPEN: never imply success you didn't observe in real output.
- STAY IN SCOPE: flag out-of-scope issues, don't fold them in.
- GUARDRAILS: don't commit, push, or open PRs unless I ask; branch first if I'm
  on main; bump pyproject only at release-tag time.
- BE STRAIGHT: lead with the answer, rank by severity, recommend don't survey,
  disagree when I'm wrong and say why.
