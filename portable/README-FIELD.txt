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

Run this as ONE line (nothing else needs to be on the stick):
  Atlas.exe --redact-folder <collection folder> --out <D:\share>

Atlas builds the inputs the engine needs, renders the whole document
family, and checks the result before reporting success - if anything is
still unredacted it FAILS and says so rather than handing you a file
that looks safe. Expect several minutes for a large fleet.

The seven Word documents each open with a Document Control table whose
Status row marks them a generated draft that has not been reviewed. Take
it literally: nothing here has been peer-reviewed or approved. The
workbook, the explorer and the executive deck carry NO such marking, and
the deck is the one most likely to be put in front of a client - so say
it out loud rather than relying on the page. Approval is recorded back
in the repo; this stick has no way to know whether it happened.

WHAT REDACTION DOES NOT REMOVE - read this before sending anything:
HOSTNAMES AND DESCRIPTIONS ARE KEPT ON PURPOSE (a deliverable full of
anonymous boxes is unreadable). Device names and interface descriptions
routinely carry the customer and site - DOH-DC-CORE1, SITE-A-CORE - so a
redacted set still identifies the client. IPs, MACs and serials are
pseudonymized; hostnames are not. Read the documents before they leave.
Atlas verifies that the redaction actually ran and that no private
address survives in the snapshot; it does not certify every field of
every file.

--out must be OUTSIDE the Atlas\ folder (an update replaces everything
there except data\), and it will not write into the collection folder
either. Atlas refuses both rather than lose your work.

The raw captures are NOT touched by the command above. To also scrub
cleartext secrets out of them IN PLACE (they stay usable for later
comparisons), add:  --redact-collection
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
