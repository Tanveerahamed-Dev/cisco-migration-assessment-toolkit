ATLAS - FIELD GUIDE
===================
Atlas, by Tanveer Ahamed - offline network-assessment kit on a stick.
This page is the field discipline. Build/developer docs live in the
repository, not on the stick.

FIRST RUN / EVERY ENGAGEMENT START
----------------------------------
1. Plug in, open the  Atlas\  folder on the stick.
2. Run:  Atlas.exe --selftest        -> expect "SELFTEST: PASS".
3. Double-click Atlas.exe. It starts the cockpit and opens your browser.
   Keep the console window open; closing it stops Atlas.
Everything the app stores lives in  Atlas\data\  beside the exe. That is
the ONLY writable folder - updates replace everything else wholesale.

LOSS OF STICK (prepare BEFORE the first engagement)
---------------------------------------------------
Client evidence lives on this stick; a lost unencrypted stick is a
client-data incident. Mitigation: BitLocker-To-Go, enabled once:
  1. In Explorer, right-click the stick drive.
  2. "Turn on BitLocker" -> "Use a password to unlock the drive".
  3. Save the recovery key somewhere that is NOT the stick.
The stick then prompts for its password on every machine.

READ-ONLY STICK
---------------
If Atlas prints "the data folder is not writable" and exits: the stick's
write-lock switch is on, or the folder/drive is read-only on this
machine. Clear that and start again - Atlas refuses to run rather than
silently lose work.

CORRUPTION (stick yanked / laptop died mid-write)
-------------------------------------------------
At every boot Atlas integrity-checks its database and, when it changed,
keeps a timestamped copy in  data\backups\  (newest 3 are kept).
If a boot prints "refusing to start - integrity check failed":
  1. Close Atlas. The damaged file is left exactly as it was found.
  2. Copy the newest  data\backups\assesshub-*.db  over
     data\assesshub.db
  3. Start Atlas again and run  Atlas.exe --selftest
Never delete data\ to "fix" a problem - it is the client's evidence.

EJECT DISCIPLINE
----------------
1. Close the Atlas console window (Ctrl+C or the X).
2. Windows "Safely Remove Hardware" / Eject.
3. Then pull the stick. Yank-pulls are what the backups exist for; do
   not make them the routine.

REDACTION - BEFORE ANYTHING LEAVES THE SITE
-------------------------------------------
Deliverables carry client IPs/MACs/serials. Produce a share-safe set:
  Atlas.exe --run-engine --no-collect --collection-dir <folder>
            --devices-file devices.json --template <template>.xlsx
            --output Assessment.xlsx --redact
To also scrub cleartext secrets out of the RAW capture folder in place
(kept comparable for --compare / --trend), add:  --redact-collection
Rule: raw captures and unredacted output never leave the site except on
this (encrypted) stick.

CREDENTIALS
-----------
Live collection prompts in the console - once per username, per-device
overrides via password_env. Credentials are NEVER written to the stick.
Anything that asks you to save a password on the stick is a bug: don't.

UPDATE (new Atlas version)
--------------------------
On the build machine:
  powershell -File portable\make_stick.ps1 -Dest E:\
(or copy the new  Atlas\  folder over this one, keeping  data\ ).
Everything is replaced EXCEPT  data\  - campaigns, snapshots and backups
survive every update. Afterwards run  Atlas.exe --selftest  once.
