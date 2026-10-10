-- Self-service department sign-up (run once on an existing database)
CREATE TABLE IF NOT EXISTS signup_request (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  department_name TEXT NOT NULL,
  email TEXT NOT NULL,
  username TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  code_hash TEXT NOT NULL DEFAULT '',          -- HMAC of the emailed code, never the code
  expires_at TIMESTAMPTZ NOT NULL,
  attempts SMALLINT NOT NULL DEFAULT 0,
  sends SMALLINT NOT NULL DEFAULT 1,
  last_sent_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  used BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE UNIQUE INDEX IF NOT EXISTS department_account_email_key ON department_account (lower(email));
