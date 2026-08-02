---
description: Config & security audit — hardening / CIS-style posture + software-advisory surface, with evidence-anchored findings.
argument-hint: [snapshot.json | collection dir | --no-collect --collection-dir migration_collection_<stamp>]
---
Audit configured security posture and advisory surface.

TARGET: $ARGUMENTS

Delegate to the **config-security-auditor** subagent. Use the engine's CIS / config-hygiene / security / software-risk axes as the basis. Every finding must carry a rule ID + the offending config line + severity + remediation. Software risk is an "advisory surface OPEN — verify against PSIRT" statement, never a "release vulnerable" claim unless the exact version is provably affected. "Not observed" is never "compliant". Read-only — propose, don't remediate. Read-only also means **no live collection**: re-analyze an existing artifact (`cisco-assess --no-collect --collection-dir migration_collection_<stamp>`, or read the `*.snapshot.json` directly), because a bare `cisco-assess` SSHes to live gear — a read-only SSH session onto production is still a production touch. Only collect if the TARGET above explicitly says to.
