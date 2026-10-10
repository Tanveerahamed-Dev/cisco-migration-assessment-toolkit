"""W59 PR-1 SSH interop fixtures. ``raw_peer`` is stdlib-only and imported by tests; ``launcher`` (stdlib and pytest)
starts ``server``, which runs ONLY as a subprocess from the isolated fixture virtualenv
(tools/requirements-ssh-fixture-test.txt) and is never imported."""
