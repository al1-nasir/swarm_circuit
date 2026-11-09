-- Persistent per-run notification cursors; original outbox remains the transactional source.
CREATE TABLE ui_stream_heads (
  run_id TEXT PRIMARY KEY REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
  sequence INTEGER NOT NULL CHECK(sequence>=0)
) STRICT;
CREATE TABLE ui_stream_notifications (
  notification_id TEXT PRIMARY KEY REFERENCES ui_outbox(notification_id) ON DELETE CASCADE,
  run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
  sequence INTEGER NOT NULL CHECK(sequence>=1),
  UNIQUE(run_id,sequence)
) STRICT;
INSERT INTO ui_stream_notifications(notification_id,run_id,sequence)
SELECT notification_id,run_id,ROW_NUMBER() OVER (PARTITION BY run_id ORDER BY created_at_ms,notification_id)
FROM ui_outbox;
INSERT INTO ui_stream_heads(run_id,sequence)
SELECT run_id,MAX(sequence) FROM ui_stream_notifications GROUP BY run_id;
CREATE TRIGGER outbox_stream_append AFTER INSERT ON ui_outbox
BEGIN
  INSERT INTO ui_stream_heads(run_id,sequence) VALUES (NEW.run_id,1)
  ON CONFLICT(run_id) DO UPDATE SET sequence=sequence+1;
  INSERT INTO ui_stream_notifications(notification_id,run_id,sequence)
  SELECT NEW.notification_id,NEW.run_id,sequence FROM ui_stream_heads WHERE run_id=NEW.run_id;
END;
