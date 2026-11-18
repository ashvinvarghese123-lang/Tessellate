-- 013_easy_passwords.sql
-- Add plain_password column so passwords can be visible in Registry

ALTER TABLE department_account ADD COLUMN IF NOT EXISTS plain_password TEXT;

-- Update registry account with easy-to-remember password: registry123
UPDATE registry_account
SET password_hash = 'scrypt$9QvKak0lXPJtZcp09GFWBw==$CSkKrZB6hs1Nq5w1846rNruzzYHg/WPAFlGscAs/V1s=',
    failed_logins = 0,
    locked_until = NULL,
    active = true
WHERE username = 'registry';

-- Set initial plain passwords for standard departments
UPDATE department_account SET plain_password = username || '123' WHERE plain_password IS NULL;
