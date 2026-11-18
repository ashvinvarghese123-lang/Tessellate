-- 012_ensure_registry_account.sql
-- Ensure the default Registry account exists and is ready for login on all environments.

INSERT INTO registry_account (username, email, password_hash, failed_logins, locked_until, active)
VALUES ('registry', 'registry@college.edu', 'scrypt$mcQasuxKJ0R502KCi7F75g==$0Bq0luPaWvhp5CiarQq82id8QVpCPaNujBufi/K0/os=', 0, NULL, true)
ON CONFLICT (username) DO UPDATE
SET password_hash = 'scrypt$mcQasuxKJ0R502KCi7F75g==$0Bq0luPaWvhp5CiarQq82id8QVpCPaNujBufi/K0/os=',
    failed_logins = 0,
    locked_until = NULL,
    active = true;
