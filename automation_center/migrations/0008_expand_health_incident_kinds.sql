-- Mở rộng kind của health_incidents cho watchdog yêu cầu sửa code mồ côi.
--
-- SQLite/D1 không ALTER được CHECK.  Bảng production hiện chỉ có bốn hàng,
-- nhưng vẫn dựng lại đủ cột và chỉ số thay vì sửa 0005_health_watchdog.sql đã
-- được D1 ghi nhận.  Migration 0008 này chạy sau toàn bộ 0001–0007, nên thứ tự
-- replay từ đầu khớp với thứ tự apply trên D1 production; phải áp nó trước khi
-- deploy Worker ghi kind mới.

DROP INDEX IF EXISTS idx_health_incident_open;
DROP INDEX IF EXISTS idx_health_incident_recent;
DROP INDEX IF EXISTS idx_health_incident_unnotified;

CREATE TABLE health_incidents_next (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN (
    'runner_offline', 'run_orphaned', 'access_token_expiring',
    'code_request_orphaned'
  )),
  subject TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  opened_at TEXT NOT NULL,
  resolved_at TEXT,
  notified_at TEXT,
  notify_error TEXT NOT NULL DEFAULT ''
);

INSERT INTO health_incidents_next (id, kind, subject, detail, opened_at, resolved_at, notified_at, notify_error)
  SELECT id, kind, subject, detail, opened_at, resolved_at, notified_at, notify_error
  FROM health_incidents;

DROP TABLE health_incidents;
ALTER TABLE health_incidents_next RENAME TO health_incidents;

CREATE UNIQUE INDEX idx_health_incident_open
  ON health_incidents(kind, subject) WHERE resolved_at IS NULL;

CREATE INDEX idx_health_incident_recent
  ON health_incidents(opened_at DESC);

CREATE INDEX idx_health_incident_unnotified
  ON health_incidents(notified_at, opened_at) WHERE notified_at IS NULL;
