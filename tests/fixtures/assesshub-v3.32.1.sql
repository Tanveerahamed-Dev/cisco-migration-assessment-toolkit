-- atlas.prior-database-fixture/1
-- source_commit=47a1ff993f3bb9c9b2e4a138be6f073c8614498e
-- source_tree=d4f9db52c0703ab02f25c3f4913d53baac8ddb60
-- storage_git_blob_sha256=f1d8f829c129db35763763b05e05c1220907f5ec851983cd3a4ba3e3208ca976
-- synthetic_data_only=true
BEGIN TRANSACTION;
CREATE TABLE campaigns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
INSERT INTO "campaigns" VALUES(1,'Release 3.32.1 fixture','Synthetic prior-release migration evidence','2026-08-03T17:00:00+00:00');
CREATE TABLE executions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'in_progress',
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    state_json  TEXT NOT NULL
);
INSERT INTO "executions" VALUES(1,1,'Prior run','completed','2026-08-03T17:00:00+00:00','2026-08-03T17:01:00+00:00','{"label":"Prior run","status":"completed","started_at":"2026-08-03T17:00:00+00:00","ended_at":"2026-08-03T17:01:00+00:00"}');
CREATE TABLE gates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    wave        TEXT NOT NULL,
    gate        TEXT NOT NULL,
    decision    TEXT NOT NULL,
    signed_by   TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',
    decided_at  TEXT NOT NULL,
    UNIQUE(campaign_id, wave, gate)
);
CREATE TABLE snapshots (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id    INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    label          TEXT NOT NULL,
    uploaded_at    TEXT NOT NULL,
    script_version TEXT NOT NULL DEFAULT '',
    n_devices      INTEGER NOT NULL DEFAULT 0,
    summary_json   TEXT NOT NULL DEFAULT '{}',
    snapshot_json  TEXT NOT NULL
);
INSERT INTO "snapshots" VALUES(1,1,'Prior snapshot','2026-08-03T17:00:30+00:00','3.32.1',1,'{"health":"synthetic"}','{"script_version":"3.32.1","executive_brief":{"scale":{"n_devices":1}},"devices":{"SYNTHETIC-1":{"hostname":"SYNTHETIC-1"}}}');
CREATE INDEX ix_snapshots_campaign ON snapshots(campaign_id, uploaded_at);
CREATE INDEX ix_executions_snapshot ON executions(snapshot_id, started_at);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('campaigns',1);
INSERT INTO "sqlite_sequence" VALUES('snapshots',1);
INSERT INTO "sqlite_sequence" VALUES('executions',1);
COMMIT;
