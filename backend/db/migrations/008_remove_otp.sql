-- Migration 008: Remove OTP Authentication System
-- Completely remove OTP challenge and temporary signup tables

DROP TABLE IF EXISTS login_challenge CASCADE;
DROP TABLE IF EXISTS signup_request CASCADE;
DROP TABLE IF EXISTS registry_challenge CASCADE;
