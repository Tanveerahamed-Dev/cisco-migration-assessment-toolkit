ATLAS - FIELD GUIDE
===================
Atlas, by Tanveer Ahamed - offline network-assessment kit on a stick.
This page is the field discipline. Build/developer docs live in the
repository, not on the stick.

FIRST INSTALL (A FOLDER OR A USB STICK; NO PYTHON OR CHECKOUT)
------------------------------------------------------------
Download the release ZIP and obtain its published SHA-256 from the
release's checksum record through your trusted delivery channel. A hash
only compares selected bytes; it is not a publisher signature.
In Windows PowerShell, set these values to your download and published hash:
  $zip = 'C:\Downloads\Atlas-release.zip'
  $expected = 'PASTE_THE_PUBLISHED_LOWERCASE_SHA256_HERE'
  if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant() -cne $expected) { throw 'ZIP SHA-256 mismatch' }
Choose a NEW writable destination. A USB drive is optional:
  Expand-Archive -LiteralPath $zip -DestinationPath C:\AtlasField
  C:\AtlasField\Atlas\Atlas.exe --selftest
Expect "SELFTEST: PASS", then double-click C:\AtlasField\Atlas\Atlas.exe.
For a USB drive use a new folder such as E:\AtlasField instead.
Never expand a new ZIP over an existing installation. Use compatible UPDATE
or VERIFIED REINSTALL below; RC7 and earlier require VERIFIED REINSTALL.
An optional verified, journaled first copy from the extracted app is:
  C:\AtlasField\Atlas\Atlas.exe --install D:\AtlasField --package $zip --expected-sha256 $expected
This creates D:\AtlasField\Atlas. The source must be a separately
extracted hash-checked bundle. No Python installation or repository is needed.
If this journaled FIRST copy is interrupted, no installed helper or recovery
pointer exists yet. Preserve every destination path and re-run the original
separately extracted bootstrap's --install with the SAME destination, ZIP and
published SHA-256. This retry is permitted only for a matching first-install
journal (had_active false and the same ZIP SHA-256). The wrapper's -Recover
and the UPDATE helper instructions apply to installed operations, not this
bootstrap case. Direct hash-check plus Expand-Archive remains the simplest
first installation.

FIRST RUN / EVERY ENGAGEMENT START
----------------------------------
1. Open the Atlas\ folder in your chosen folder or on the stick.
2. Run:  Atlas.exe --selftest        -> expect "SELFTEST: PASS".
3. Double-click Atlas.exe. It starts AssessHub (the app) and opens
   your browser. Keep the console window open; closing it stops Atlas.
Everything the app stores lives in  Atlas\data\  beside the exe. That is
the ONLY writable folder - updates replace everything else wholesale.
Atlas is also the engine itself. With --run-engine in front of the
engine's own arguments, Atlas.exe runs the assessment engine instead
of the app (see OFFLINE / LIVE NETWORK BOUNDARY). There is no second
engine program on the stick.

READING A SNAPSHOT (THE CORE SCREENS)
-------------------------------------
Open a campaign, then a snapshot. Five views run across the top:
  Overview          fleet posture, health and lifecycle bands,
                    gating items, move-group readiness.
  Trust             what the analysis could NOT see: for each
                    analysis input, how many devices it could not
                    assess, and which. Read it before you quote any
                    number to the client.
  Inventory         devices, VLANs, endpoints, uncollected peers.
  Findings          the prioritised findings, in the engine's order.
  Topology & Paths  the map, the 3-D view (see ATLAS SCOPE), and an
                    IP path question answered from the stored route
                    model - nothing is sent on the network.
Click a linked device name for its Device page. Two of its panels
come straight from the engine's stored rows, in the engine's order:
  "If this device fails"  the severity, VLANs impacted and stranded
                          endpoints the engine found for its loss.
  "Structural links"      its links, whether each is a bridge, and
                          which switch pairs it would sever.
The page does not simulate, rank or fill in either one.
"Tools and downloads" (top right of a snapshot) holds the cutover
plan, the documents and the older full snapshot page.

EVERY VALUE CARRIES A STATE. A dash with a label is NOT zero and NOT
healthy - read the label and the reason under it:
  Not collected         a blind spot: the evidence was never captured.
  Collected, empty      captured, and nothing of that kind was there.
  Not assessed          the engine had nothing it could judge.
  Analysis unavailable  that analysis step failed in this run.
  Unverified            the value failed a check.
The Evidence button beside a value opens its source records and the
limits that apply to it.

LOWER BOUNDS. Some failure-impact counts are only a floor: the true
impact can be larger, for example behind a neighbour the collection
did not reach. On the Device page and in Topology & Paths such a
count reads >= N, with the reason on a line below it, and its
Evidence lists a witness reference. A Findings total that the engine
publishes only as a minimum also reads >= N. The Failure impact tab
under Tools and downloads spells it out, and the cutover plan writes
LOWER BOUND, at least N. NOT ASSESSED in the cutover plan or the
keystone list marks what could not be ranked - never a clean result.

ATLAS SCOPE (THE 3-D VIEW OF A SNAPSHOT)
----------------------------------------
On a snapshot's page in the app, click "Open in Atlas Scope". The
same snapshot opens as a 3-D investigation view in the same browser, at
/scope/snapshots/<id>/ on the Atlas address. The view reads that
snapshot from Atlas when the page opens: nothing is copied off the
stick and nothing is sent anywhere else. It is read-only - it cannot
change the snapshot or anything else Atlas stores.
No link on the page means this build cannot show the view; everything
else still works without it. On the stick, the --selftest line
"atlas-scope-dist" must read [ ok ] - if it says FAIL, the stick is
damaged or incomplete: update it (see UPDATE).
The view draws what the collection recorded. A device, link or finding
the collection did not see is simply not there - an empty or quiet
view is NOT a clean bill of health.
The same view also opens inside Topology & Paths as 3-D investigation.
Atlas Scope ships as a labelled PREVIEW: its acceptance is not
complete. Its status bar is marked Preview on every view and at every
window size, and the app marks Preview beside "Open in Atlas Scope"
and beside the 3-D investigation heading. Use it to look around, and
check anything it shows on the core screens before you act on it or
repeat it to the client.

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

WHAT ATLAS KEEPS, AND WHAT IT WILL NOT DELETE
---------------------------------------------
Atlas keeps snapshots, not raw captures. A ZIP or folder you ingest is
copied to this computer's temporary folder for the engine run, and
Atlas deletes that copy when the run ends (a failed deletion is not
reported); your collection folder is only read.
The ingest never connects to a device.
An execution run that binds its post-change snapshot makes a
comparison receipt: a permanent decision record. Atlas refuses to
delete a snapshot a receipt names, an execution run that holds one,
or a campaign that contains one. A campaign, snapshot or execution
run WITHOUT a receipt can be deleted (a campaign from its own page).
IN-APP DELETE IS NOT DISPOSAL: a deleted row leaves the app's lists,
but its bytes can stay readable inside data\assesshub.db (Atlas does
not make the database overwrite or compact freed space), and the
start-time copies in data\backups\ can still hold it.
There is NO purge in the app, by decision. Disposing of client data
means removing the whole data\ folder and every other copy listed
below, outside Atlas (see DISPOSING OF CLIENT DATA).
The app does NOT redact documents you download (see REDACTION).

DISPOSING OF CLIENT DATA (MANUAL, OUTSIDE ATLAS)
------------------------------------------------
Do this only at the end of an engagement, and only when the client
agreement allows it. It is not a repair: for a damaged database,
follow CORRUPTION instead. Never edit the database or try to remove
single records - receipts are permanent by design.
  1. First hand over or archive everything the agreement says to
     keep: the deliverables, and the receipts and execution records
     they rest on.
  2. Close Atlas and its browser tab (EJECT DISCIPLINE, steps 1-2).
  3. Find every copy. Client data can be in all of these places:
     Inside Atlas\data\ on the stick:
       assesshub.db, and assesshub.db-journal if it exists
       any .corrupt files you made (see CORRUPTION)
       backups\          start-time copies of the database, and any
                         copies you parked there yourself
       release-backups\  database copies and hash receipts kept by
                         updates and rollbacks
       *.log             engine logs (they name devices and hosts)
     Beside Atlas\ on the stick, after any update or rollback,
     finished or interrupted: every folder whose name starts with
     Atlas. or .Atlas. can hold client data - Atlas.data-handoff (the
     whole data folder), Atlas.incoming\data, Atlas.previous\data,
     the Atlas.failed-* folders, and .Atlas.database-preflight (a copy
     of assesshub.db, left behind if the updater cannot remove it).
     Folders you chose: the raw captures of a live collection (the
     --collection-dir folder; without that option the engine makes a
     migration_collection_<date> folder in the folder the run was
     started from, even inside Atlas\), every --output folder and the
     documents beside it, and every --out folder.
     On the laptop: documents downloaded from the app (usually the
     Downloads folder), engine logs in the folder an engine run was
     started from, and anything named assesshub_* or atlas_redact_*
     in the temporary folder (%TEMP%). Atlas removes those after each
     run, but a removal that failed is not reported. Also any tmp*
     file in %TEMP%: an upload larger than 1 MB is spooled there
     while Atlas reads it, and a power loss or a pulled stick can
     leave it behind.
     The browser on the laptop: its cache and site data can keep
     pages and data Atlas served. Use a browser profile kept only for
     Atlas and delete that profile, or clear that browser's cache and
     site data for the Atlas address.
  4. Delete them with Windows Explorer, not through the app. Remove
     Atlas\data\ as a whole - the database together with backups\
     and release-backups\ - and the client data inside the Atlas.*
     and .Atlas.* folders, so no older copy is left behind. The empty
     data folder itself can stay.
  5. Deleting a file does not make it unrecoverable. On a USB stick
     or an SSD, neither does overwriting it: wear levelling writes to
     other memory cells, so old copies can survive an overwrite tool
     as well as a delete. BitLocker To Go turned on AFTER client data
     was written, with "Encrypt used disk space only", leaves the
     space that was free at that moment unencrypted, so data deleted
     earlier can stay readable. The honest options: encrypt the stick
     from its first use (LOSS OF STICK) and, at disposal, reformat it
     and destroy every saved copy of its recovery key; or physically
     destroy the stick. Where the agreement requires it, follow your
     organisation's media-sanitisation procedure for the stick and
     the laptop.
The next start begins with a new, empty database.

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
Redaction exists ONLY as a command: the app does NOT redact the
documents you download from its pages.

Run this as ONE line (nothing else needs to be on the stick):
  Atlas.exe --redact-folder <collection folder> --out <D:\share>

Atlas builds the inputs the engine needs, renders the whole document
family, and checks the result before reporting success. That check is
NARROWER than it sounds: it covers two things, not every field of every
file. Read WHAT REDACTION DOES NOT REMOVE below before you send
anything. Expect several minutes for a large fleet.

The seven Word documents each carry a Document Control table, just after
the cover page, whose Status row marks them a generated draft that has
not been reviewed. Take it literally: nothing here has been peer-reviewed
or approved. AssessHub Design/MOP downloads add a visible and machine-readable
UNAPPROVED DRAFT marker when their configured approval gates are missing,
revoked, unreadable, or ownership-uncertain. This field redaction command is
deliberately ungated, so its Design/MOP carry only the generic draft control.
The workbook, explorer and executive deck carry NO such marking, and the
deck is the item most likely to be put in front of a client - say the posture
out loud rather than relying on the page. Approval is recorded per engagement
by whoever runs the assessment; a generated document never creates approval.

WHAT REDACTION DOES NOT REMOVE - read this before sending anything:
HOSTNAMES AND DESCRIPTIONS ARE KEPT ON PURPOSE (a deliverable full of
anonymous boxes is unreadable). Device names and interface descriptions
routinely carry the customer and site - DOH-DC-CORE1, SITE-A-CORE - so a
redacted set still identifies the client. IPs, MACs and serials are
pseudonymized; hostnames are not. Read the documents before they leave.
Atlas verifies that the redaction actually ran and that no private
address survives in the snapshot; it does not certify every field of
every file.

IF THE SET IS SHORT, ATLAS SAYS SO. Each document is written
independently and a failed one does not stop the run, so a set can come
out complete-looking but missing a document or two. Atlas compares what
landed against what this command should have produced and prints
"INCOMPLETE SET", naming each document and why: ABSENT (never written),
UNUSABLE (there but empty or truncated - a full disk does this), or
STALE (left by an earlier run into the same folder, so it may belong to
another job - only possible with --reuse-out, see below). The same list
is written to INCOMPLETE-SET.txt in your --out folder. That is NOT a
leak warning: what THIS RUN wrote is redacted. It means the SET is
short - re-run into an empty folder, or tell the recipient which
documents are not included.

One exception, and the note says so itself: if the folder ALSO holds
DO-NOT-SEND-NOT-REDACTED.txt, a previous run into it could not be
certified, and any document listed as STALE was written by THAT run -
so it is not covered by this run's check and may be UNREDACTED. Read
that file first and do not send the folder until you have dealt with it.

ONE --out FOLDER PER JOB. Atlas REFUSES to render into a folder that
already holds a deliverable set, and says so in seconds rather than
after a ten-minute run: "already holds a redacted deliverable set".
The reason is the STALE case above. If two jobs share a folder and one
document fails to write, the OTHER job's copy is left sitting under
exactly the right name - and redaction keeps hostnames and site codes,
so it identifies that client inside this delivery. Use an empty folder
and this cannot happen. To render into a folder anyway - re-running the
SAME job after a short set is the normal reason - add:  --reuse-out

Exit codes:  0 = complete and verified.  3 = produced, but the set is
short - what this run wrote is redacted, there is just less of it (read
the note if DO-NOT-SEND-NOT-REDACTED.txt is also present).  1 = failed;
do not send.

This command produces eleven items: the workbook, the source-bound Protocol
Assurance JSON export, the explorer, seven Word documents and the deck.
It also keeps the manifest-owned topology.dot/topology.mmd and run-metadata
sidecars so later manifest verification does not point to deleted staging files.
The Cutover Plan and the NRFU / Acceptance Test
Plan are NOT among them - those two are generated in AssessHub, not by
this command, so a set with no warning is complete WITHOUT them.
A Post-Implementation Review (PIR) is conditional post-execution: it is
generated only from an AssessHub execution run and is not a CLI artifact.

--out must be OUTSIDE the Atlas\ folder (an update replaces everything
there except data\), and it will not write into the collection folder
either. Atlas refuses both rather than lose your work.

The raw captures are NOT touched by the command above. To also scrub
cleartext secrets out of them IN PLACE (they stay usable for later
comparisons), add:  --redact-collection
Rule: raw captures and unredacted output never leave the site except on
this (encrypted) stick.

PROVING A DELIVERABLE SET IS THE ONE YOU PRODUCED
-------------------------------------------------
Every assessment run drops a  <name>.run_manifest.json  beside the
workbook: a hash-chained ledger of the run plus a SHA-256 of each file it
produced. To check a set that has been sitting on a share, or that came
back to you from the client:
  Atlas.exe --verify-manifest <path to run_manifest.json>

"manifest OK" means the ledger still matches its own seal and every file
listed hashes to what was sealed. It exits non-zero if not, and names the
files: MISMATCH = changed since the run, MISSING = not in that folder,
INVALID = the manifest pointed somewhere outside it and was not opened.
Artifact bytes are checked by default. Only when the manifest was
deliberately separated from its files, inspect its sealed metadata alone:
  Atlas.exe --verify-manifest <path to run_manifest.json> --metadata-only
That mode explicitly reports that artifact bytes were NOT checked.

The engine performs this same full chain, metadata and artifact-byte check
immediately after it writes each run manifest. Run the command above again
after copying or receiving a set to catch damage introduced later.

WHAT THIS PROVES, AND WHAT IT DOES NOT: the seal is UNKEYED, and the code
that writes it ships in this app. It catches a careless edit, a dropped
file or a truncated ledger - it does NOT stop someone who re-seals the
manifest after editing it, because they can recompute a clean seal. Do
not present it to a client as proof nobody tampered with anything.
The one check a re-seal cannot beat is comparing against a chain_root you
recorded somewhere else at the time of the run:
  Atlas.exe --verify-manifest <path to run_manifest.json> --expect-root <chain_root>
So when you hand a set over, copy the chain_root into the report. Open the
run_manifest.json in Notepad and take the full "chain_root" value - the
console line at the end of a run shortens it, and a shortened one will not
match.

CREDENTIALS
-----------
Live collection prompts in the console - once per username, per-device
overrides via password_env. Credentials are NEVER written to the stick.
Anything that asks you to save a password on the stick is a bug: don't.

UPDATE (new Atlas version)
--------------------------
Close the running Atlas application first. On THIS computer, use the
INSTALLED executable and the new ZIP's independently obtained published hash:
  C:\AtlasField\Atlas\Atlas.exe --update C:\Downloads\Atlas-update.zip --expected-sha256 PASTE_THE_PUBLISHED_LOWERCASE_SHA256_HERE
Run from a folder OUTSIDE Atlas\ so the terminal does not hold its directory.
Atlas copies its installed maintenance code (never data\) into a private
same-drive helper, then exits so Windows can release its executable and DLLs.
"scheduled" means dispatched, NOT complete. The command prints a result
file outside Atlas\; wait until that file says "status":"complete" and
"exit_code":0 before starting Atlas again. A "refused" result needs inspection;
preserve all Atlas* paths. The optional make_stick.ps1 wrapper waits for this
result and returns the transaction's actual exit code; it needs only Atlas.exe.
Maintenance request, recovery and result records can contain local installation
paths and failure reasons. Keep them private with the kit; do not include them
in shared deliverables.
If interruption leaves Atlas\Atlas.exe absent, open Atlas.maintenance.json
beside Atlas\: it names the retained installed-version recovery helper.
Run that exact helper executable with --recover and the installation parent
folder. Supply a fresh result file outside all application/helper directories:
  C:\AtlasField\Atlas.maintenance-<recorded-nonce>\Atlas\Atlas.exe --recover C:\AtlasField --maintenance-result C:\AtlasField\Atlas.maintenance-result.0123456789abcdef0123456789abcdef.json
Use the actual recorded helper name, and replace the example result nonce
with a fresh 32-character lowercase hex value. Inspect the printed failure
reason and terminal result, including its actual exit_code. The optional
wrapper supports explicit -Recover; it must not reinterpret a new update
as a request to replay an older recorded operation. Recovery completes only
the recorded interrupted transaction. Inspect its outcome before separately
requesting any new update or rollback.
When --recover is launched through the active Atlas.exe, it schedules the
recorded helper and closes to release its own Windows image handles. As with
an update, wait for the printed receipt's terminal status and exit_code;
dispatch exit zero is not completion. The wrapper's -Recover waits for that
same terminal receipt and returns its actual result.
If the active executable still exists, Atlas reports "portable maintenance is
incomplete" and refuses to open a new empty store until recovery is finished.
Never copy new files over the active Atlas\ tree. The updater verifies and
preflights Atlas.incoming on the destination drive, preserves a hash-bound
pre-update database backup, moves data\ to Atlas.data-handoff, switches and
verifies the application with no client data inside its tree, and only then attaches
data\ with one exact directory rename. It holds .Atlas.update.lock so a second
updater cannot touch a live transaction. The old complete application remains
at Atlas.previous, and Atlas.rollback-slot.json binds that exact pair. If
interrupted, preserve the journal and recorded helper and use explicit
recovery above. Do not launch whichever version happens to occupy Atlas\
to restart the recorded operation.
Software fault-injection tests cover each recorded phase; only the physical
field packet can prove real USB power-loss behavior.

Explicit application rollback (newer database retained separately):
  C:\AtlasField\Atlas\Atlas.exe --rollback
The older application must open a same-drive copy of the retained database
before Atlas switches it in. If that compatibility check fails, use:
  C:\AtlasField\Atlas\Atlas.exe --rollback --restore-pre-update-database
Only the database backup named and hashed by Atlas.rollback-slot.json is
eligible. Atlas first preserves the newer database and a hash receipt in
data\release-backups\. Those hashes are local consistency evidence, not a
signature or independent custody record.

Verification runs inside the installed frozen Atlas, including full SBOM
schema validation. Its SHA-bound compatibility policy permits additional
runtime dependencies with complete bound notices/SBOM, while preserving every
installed dependency version, schema, toolchain, native-package and frontend
pin. A changed pin or unsupported schema is refused; do not bypass it.
That includes security fixes which change a dependency or build tool.
Use VERIFIED REINSTALL for such successors and for RC7-and-earlier kits,
whose executable has no frozen update door. Compatibility refusal is not
evidence that the new ZIP is invalid.
Strict current-source release/build gates remain separate and unchanged.
After a compatible update, the next update uses the newly installed verifier.
Maintenance helpers contain application code only. Later invocations retire
only completed helpers with an exact verified application and request.json;
unknown content, interrupted helpers and original refusals remain preserved.

If the update reports "IN USE": Atlas or the browser it opened is
still running and holding files on the stick. Close both (see EJECT
DISCIPLINE above) and run it again.

VERIFIED REINSTALL (EARLIER KITS OR CHANGED SECURITY/TOOLCHAIN PINS)
-----------------------------------------------------------------
The supported successor path is a NEW installation beside the old kit.
Retain the old kit unchanged; never overwrite it or copy a new database back
into it. No host Python, checkout or USB drive is required. A published hash
selects exact bytes; it does not authenticate their publisher.

1. Stop EVERY Atlas server, engine, redaction and maintenance process. Keep
   both kits closed throughout copying and preflight. If the old kit has a
   journal or pending worker, finish its recorded recovery first. If
   assesshub.db-journal, assesshub.db-wal or assesshub.db-shm remains, STOP;
   preserve it with the old kit and resolve database recovery before copying.
2. Obtain the new ZIP and published SHA-256 through the trusted delivery
   channel. Repeat the FIRST INSTALL hash check and Expand-Archive into a
   fresh bootstrap folder. Use THAT new executable and the SAME hash:
  C:\AtlasDownload\Atlas\Atlas.exe --install C:\AtlasNext --package C:\Downloads\Atlas-new.zip --expected-sha256 PASTE_THE_PUBLISHED_LOWERCASE_SHA256_HERE
   This new frozen verifier checks its own release, independently of old pins.
3. Make an offline backup of the complete old data\, including all hidden
   files, backups, release-backups, logs and empty directories. Keep it outside
   both kits, preferably on separately custodied media. Verify EVERY path,
   directory, file length and SHA-256 before using the copy. The following
   PowerShell recipe uses fresh example paths; stop on any error or mismatch.
   It refuses links/junctions and never removes or overwrites the old kit.

  $ErrorActionPreference = 'Stop'
  $oldData = 'C:\AtlasField\Atlas\data'
  $backup = 'C:\AtlasOfflineBackup'
  $stage = 'C:\AtlasReinstallStage'
  $nextData = 'C:\AtlasNext\Atlas\data'
  $candidate = 'C:\AtlasNext\Atlas\Atlas.exe'
  function Data-Inventory([string]$root) {
    $item = Get-Item -LiteralPath $root -Force
    if (-not $item.PSIsContainer) { throw 'Data root is not a directory' }
    $ancestor = $item
    while ($ancestor) { if ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Redirected data ancestor' }; $ancestor = $ancestor.Parent }
    $prefix = $item.FullName.TrimEnd('\') + '\'
    $stack = New-Object System.Collections.Stack
    $rows = New-Object 'System.Collections.Generic.List[string]'
    $stack.Push($item)
    while ($stack.Count -gt 0) {
      $directory = Get-Item -LiteralPath ($stack.Pop().FullName) -Force
      if ($directory.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Redirected data directory' }
      foreach ($entry in @(Get-ChildItem -LiteralPath $directory.FullName -Force)) {
        if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Redirected data member' }
        $relative = $entry.FullName.Substring($prefix.Length)
        if ($entry.PSIsContainer) { $rows.Add('D  ' + $relative); $stack.Push($entry) } else { $rows.Add('F  ' + $relative + '  ' + $entry.Length + '  ' + (Get-FileHash -LiteralPath $entry.FullName -Algorithm SHA256).Hash.ToLowerInvariant()) }
      }
    }
    @($rows.ToArray() | Sort-Object)
  }
  function Same-Inventory($expected, [string]$root) { if (Compare-Object @($expected) @(Data-Inventory $root)) { throw 'Data inventory mismatch' } }
  foreach ($suffix in @('-journal', '-wal', '-shm')) { if (Test-Path -LiteralPath ($oldData + '\assesshub.db' + $suffix)) { throw 'Database is not quiescent' } }
  foreach ($fresh in @($backup, $stage, ($backup + '.inventory.txt'))) { if (Test-Path -LiteralPath $fresh) { throw 'Choose fresh backup/staging/inventory paths' } }
  $original = @(Data-Inventory $oldData)
  Copy-Item -LiteralPath $oldData -Destination $backup -Recurse -Force
  Same-Inventory $original $backup
  Same-Inventory $original $oldData
  $original | Out-File -LiteralPath ($backup + '.inventory.txt') -Encoding UTF8 -NoClobber
  New-Item -ItemType Directory -Path $stage | Out-Null
  Copy-Item -LiteralPath $backup -Destination ($stage + '\data') -Recurse -Force
  Same-Inventory $original ($stage + '\data')

4. Preflight a separate database COPY with the new candidate before adopting
   any data. This migrates only a disposable copy and proves every prior
   table, column and row remains. Keep the request and receipt outside Atlas\.

  New-Item -ItemType Directory -Path ($stage + '\preflight') | Out-Null
  $copy = $stage + '\preflight\assesshub.db'
  Copy-Item -LiteralPath ($backup + '\assesshub.db') -Destination $copy
  $sha = (Get-FileHash -LiteralPath $copy -Algorithm SHA256).Hash.ToLowerInvariant()
  $nonce = [guid]::NewGuid().ToString('N')
  $request = [ordered]@{database_name='assesshub.db';input_copy_bytes=[int64](Get-Item -LiteralPath $copy).Length;input_copy_sha256=$sha;nonce=$nonce;requested_action='open_migrate_copy_and_report';schema='atlas.database-preflight-request/1'}
  $marker = $stage + '\preflight\atlas-db-preflight.json'
  [IO.File]::WriteAllText($marker, ($request | ConvertTo-Json -Compress) + "`n", [Text.UTF8Encoding]::new($false))
  $env:ATLAS_PORTABLE_DATABASE_PREFLIGHT = $nonce
  try { $raw = & $candidate --database-preflight $copy; if ($LASTEXITCODE -ne 0) { throw 'Candidate database preflight refused' } } finally { Remove-Item Env:\ATLAS_PORTABLE_DATABASE_PREFLIGHT -ErrorAction SilentlyContinue }
  $receipt = ($raw | Where-Object { $_.TrimStart().StartsWith('{') } | Select-Object -Last 1) | ConvertFrom-Json
  if ($receipt.schema -ne 'atlas.database-preflight/1' -or $receipt.status -ne 'pass' -or $receipt.quick_check -ne 'ok' -or $receipt.logical_migration.schema -ne 'atlas.database-logical-migration/1' -or $receipt.logical_migration.status -ne 'pass' -or $receipt.request_nonce -ne $nonce -or $receipt.input_copy_binding.database_name -ne 'assesshub.db' -or $receipt.input_copy_binding.bytes -ne $request.input_copy_bytes -or $receipt.input_copy_binding.sha256 -ne $sha -or $receipt.request_sha256 -ne (Get-FileHash -LiteralPath $marker -Algorithm SHA256).Hash.ToLowerInvariant() -or $receipt.migrated_copy_sha256 -ne (Get-FileHash -LiteralPath $copy -Algorithm SHA256).Hash.ToLowerInvariant() -or $receipt.migrated_copy_bytes -ne (Get-Item -LiteralPath $copy).Length) { throw 'Preflight receipt binding differs' }
  if (@($receipt.logical_migration.prior_table_preservation | Where-Object { $_.status -ne 'preserved' }).Count) { throw 'Prior data was not preserved' }
  $raw | Set-Content -LiteralPath ($stage + '\preflight-receipt.json') -Encoding UTF8
  Same-Inventory $original $oldData
  Same-Inventory $original $backup

5. Adopt only the successfully preflighted copy. Retain the unmodified staged
   database and new empty data directory as additional rollback evidence.
   Staging and AtlasNext must be on the SAME volume for these directory moves.

  if (@(Get-ChildItem -LiteralPath $nextData -Force).Count) { throw 'New kit data is not empty' }
  Move-Item -LiteralPath ($stage + '\data\assesshub.db') -Destination ($stage + '\unmigrated-staging.db')
  Copy-Item -LiteralPath $copy -Destination ($stage + '\data\assesshub.db')
  Move-Item -LiteralPath $nextData -Destination ($stage + '\empty-new-data')
  Move-Item -LiteralPath ($stage + '\data') -Destination $nextData
  Same-Inventory $original $oldData
  Same-Inventory $original $backup

6. Run the new kit's --selftest, start it, and check the existing campaigns,
   snapshots, execution receipts and expected documents before new work.
   Retain the unchanged old kit, offline backup, staging and receipt. If the
   new kit refuses, close it and use the retained old kit with its ORIGINAL
   data; do not put the migrated/newer database into the older application.
   Preserve any new work separately before choosing rollback. The hosted
   synthetic reinstall proof does not certify an arbitrary historical database
   or a distinct security/toolchain successor; each candidate preflight is required.

MANAGED WINDOWS POWERSHELL POLICY
---------------------------------
The bundled transaction uses Windows PowerShell. Group Policy AllSigned,
RemoteSigned, AppLocker or application control can refuse its unsigned script;
the command's -ExecutionPolicy Bypass does NOT override those controls. Keep the
refusal and ask the managed-device owner for an approved execution path. Do not
change policy to get a green result. Where the new EXE and normal file copying
are permitted, FIRST INSTALL by hash-check plus Expand-Archive, followed by the
same VERIFIED REINSTALL backup/copy/preflight/adoption discipline, avoids the
transaction script. If that is also blocked, stop for the managed-device owner.
Managed-policy acceptance remains an external field gate.
For this fallback, Expand-Archive the hash-checked ZIP into the fresh
AtlasNext folder, then run its verifier before copying any data:
  C:\AtlasNext\Atlas\Atlas.exe --verify-release --zip C:\Downloads\Atlas-new.zip --expected-sha256 PASTE_THE_PUBLISHED_LOWERCASE_SHA256_HERE
Require SELF_CONSISTENCY_PASS and exit 0. Selftest MUST use a fresh database in
a separate disposable directory, outside BOTH kits and the reserved offline
backup/staging paths. Do not run default --selftest here: it creates data\backups
in the new kit, which step 5 correctly refuses as nonempty. For the example paths:
  $ErrorActionPreference = 'Stop'
  $selftestRoot = 'C:\AtlasSelftest'
  if (Test-Path -LiteralPath $selftestRoot) { throw 'Choose a fresh external selftest directory' }
  New-Item -ItemType Directory -Path $selftestRoot | Out-Null
  & C:\AtlasNext\Atlas\Atlas.exe --selftest --db ($selftestRoot + '\selftest.db')
  if ($LASTEXITCODE -ne 0) { throw 'Candidate selftest refused' }
  if (Test-Path -LiteralPath C:\AtlasNext\Atlas\data) { throw 'Extracted kit unexpectedly contains data' }
  New-Item -ItemType Directory -Path C:\AtlasNext\Atlas\data | Out-Null
Continue with VERIFIED REINSTALL step 3, then its preflight and adoption steps.
Keep the disposable selftest directory separate; never reuse it as the backup,
staging or new data directory, or adopt any data from it. The new data directory
must remain empty until step 5; never use a populated directory as the destination.

OFFLINE / LIVE NETWORK BOUNDARY
-------------------------------
The portable profile guards the Python socket paths used by Atlas against
non-loopback DNS, TCP and UDP by default while keeping AssessHub on numeric
loopback (127.0.0.1 or ::1). This is defense in depth, not an OS firewall:
the disconnected-NIC field test is the hard no-internet check. For an
explicitly authorized read-only SSH collection, use the engine door with the
engagement's reviewed devices file and workbook template, for example:
  Atlas.exe --allow-live-network --run-engine --devices-file D:\job\devices.json --template D:\job\template.xlsx --output D:\job\Assessment.xlsx --collection-dir D:\job\collection
Always pass --collection-dir and --output, each to a folder outside
Atlas\: without --collection-dir the raw captures land in a new
migration_collection_<date> folder in whatever folder the command was
started from, and only the engine log is moved into Atlas\data.
The browser ingest routes remain offline; the bare `--allow-live-network`
server form changes reachability but does not itself start a collection.
This enables network reachability only. It does NOT authorize a collection,
change device credentials, permit device writes, or weaken the read-only role.
