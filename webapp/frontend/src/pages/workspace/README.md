# Native workspace application parts

These page parts belong to the Atlas application: engagement navigation and its
request lifecycle, snapshot-bound device evidence, and the provisional selection
and tool frame. They follow the page-renderer boundary already used by `pages/core`.

Keep their application state and source admission here, with their existing tests.
The shared Design library lives in `src/components` and retains its complete public
barrel, prop, documentation, preview and visual contracts. Reusable primitives added
to that library must satisfy all of those contracts. This page boundary does not
change the Design discovery rule, its exclusions, baselines or any test assertion.
