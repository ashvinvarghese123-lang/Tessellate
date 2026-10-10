-- College Registry: a separate, data-only account type (no timetable powers, no department priority)
CREATE TABLE IF NOT EXISTS registry_account (
  id SERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL, email TEXT NOT NULL, password_hash TEXT NOT NULL,
  failed_logins SMALLINT NOT NULL DEFAULT 0, locked_until TIMESTAMPTZ,
  password_changed_at TIMESTAMPTZ NOT NULL DEFAULT now(), active BOOLEAN NOT NULL DEFAULT TRUE);
CREATE TABLE IF NOT EXISTS registry_challenge (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id INT NOT NULL REFERENCES registry_account(id) ON DELETE CASCADE,
  code_hash TEXT NOT NULL, expires_at TIMESTAMPTZ NOT NULL, attempts SMALLINT NOT NULL DEFAULT 0,
  sends SMALLINT NOT NULL DEFAULT 1, last_sent_at TIMESTAMPTZ NOT NULL DEFAULT now(), used BOOLEAN NOT NULL DEFAULT FALSE);
CREATE TABLE IF NOT EXISTS registry_session (
  token_hash TEXT PRIMARY KEY, account_id INT NOT NULL REFERENCES registry_account(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL, revoked BOOLEAN NOT NULL DEFAULT FALSE);
CREATE TABLE IF NOT EXISTS registry_reset (
  token_hash TEXT PRIMARY KEY, account_id INT NOT NULL REFERENCES registry_account(id) ON DELETE CASCADE,
  expires_at TIMESTAMPTZ NOT NULL, used BOOLEAN NOT NULL DEFAULT FALSE);
