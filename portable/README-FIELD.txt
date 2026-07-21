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
keeps a timestamped copy in  data\backups\  (newest 3 are kept). Atlas
only ever rotates files it wrote itself, so your own copies parked in
that folder are never deleted - and never counted as backups.

If a boot prints "refusing to start - integrity check failed":
  1. Close Atlas. The damaged file is left as it was found.
  2. RENAME it - do NOT copy over it:
       data\assesshub.db          -> data\assesshub.db.corrupt
       data\assesshub.db-journal  -> data\assesshub.db-journal.corrupt
                                     (only if that file exists)
     A damaged database can often still be salvaged; overwriting it
     destroys the only copy of everything collected since the last start.
  3. Copy the newest  data\backups\assesshub-<stamp>.db  to
     data\assesshub.db
  4. Start Atlas and CHECK THE CAMPAIGN LIST - that is what tells you the
     restore worked. (--selftest does not open the database; it only
     checks that files and folders are present.)
EXPECT TO LOSE work done since Atlas last started: backups are taken at
boot, not continuously. Keep the .corrupt files until you have confirmed
what survived.
Never delete data\ to "fix" a problem - it is the client's evidence.

A boot saying "cannot open the store" is NOT corruption - usually Atlas
is already running in another window. Close it and start again.

EJECT DISCIPLINE
----------------
1. Close the Atlas console window (Ctrl+C or the X).
2. CLOSE THE BROWSER TAB Atlas opened - and if it started the browser
   itself, close that browser window too. Atlas opens the browser with
   the stick as its working directory, so the browser keeps files on
   the stick open even after Atlas exits. Windows will refuse to eject
   (and an update will fail with "IN USE") until it is closed.
3. Windows "Safely Remove Hardware" / Eject.
4. Then pull the stick. Yank-pulls are what the backups exist for; do
   not make them the routine.

REDACTION - BEFORE ANYTHING LEAVES THE SITE
-------------------------------------------
Deliverables carry client IPs/MACs/serials. --redact pseudonymizes them
across the whole output set (snapshot, workbook, explorer).

READ THIS BEFORE YOU TRAVEL: redaction runs the ENGINE, and the engine
needs two inputs THE STICK DOES NOT CARRY - your assessment template
(.xlsx) and a devices.json. Copy both onto the stick beforehand if you
may need to redact on site. Without them the command stops with
"Template not found" or "Devices file not found".

Then run this as ONE line (do not split it):
  Atlas.exe --run-engine --no-collect --collection-dir <folder> --devices-file <devices.json> --template <template.xlsx> --output <D:\out\Assessment.xlsx> --redact

Send --output to a folder OUTSIDE Atlas\ : an update replaces everything
except data\, so deliverables written beside Atlas.exe are lost.
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

If the update reports "IN USE": Atlas or the browser it opened is
still running and holding files on the stick. Close both (see EJECT
DISCIPLINE above) and run it again.
