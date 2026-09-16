-- Jessica 4.0 — Supabase Schema
-- Run this in your Supabase SQL Editor:
-- https://supabase.com → your project → SQL Editor → New Query

-- ── Email log table ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS jessica_emails (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  direction   TEXT NOT NULL CHECK (direction IN ('sent', 'received')),
  from_email  TEXT NOT NULL,
  to_email    TEXT NOT NULL,
  subject     TEXT NOT NULL DEFAULT '',
  body        TEXT NOT NULL DEFAULT '',
  status      TEXT NOT NULL DEFAULT 'ok',
  error       TEXT NOT NULL DEFAULT '',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for fast lookups by direction and date
CREATE INDEX IF NOT EXISTS idx_jessica_emails_direction   ON jessica_emails (direction);
CREATE INDEX IF NOT EXISTS idx_jessica_emails_created_at  ON jessica_emails (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jessica_emails_to_email    ON jessica_emails (to_email);
CREATE INDEX IF NOT EXISTS idx_jessica_emails_from_email  ON jessica_emails (from_email);

-- Full text search index
CREATE INDEX IF NOT EXISTS idx_jessica_emails_subject_fts
  ON jessica_emails USING gin(to_tsvector('english', subject || ' ' || body));

-- ── Row Level Security ────────────────────────────────────────
ALTER TABLE jessica_emails ENABLE ROW LEVEL SECURITY;

-- Allow service role full access (used by the agent backend)
CREATE POLICY "service_role_all"
  ON jessica_emails FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- ── Agent memory store (supplement to LangGraph store) ───────
-- Optional: use this if you want direct Supabase-side memory queries
CREATE TABLE IF NOT EXISTS jessica_memory (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      TEXT NOT NULL,
  namespace    TEXT NOT NULL DEFAULT 'jessica_memory_store',
  key          TEXT NOT NULL,
  value        JSONB NOT NULL DEFAULT '{}',
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, namespace, key)
);

CREATE INDEX IF NOT EXISTS idx_jessica_memory_user ON jessica_memory (user_id, namespace);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_jessica_memory_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER jessica_memory_updated_at
  BEFORE UPDATE ON jessica_memory
  FOR EACH ROW EXECUTE FUNCTION update_jessica_memory_updated_at();

ALTER TABLE jessica_memory ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_memory_all"
  ON jessica_memory FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- ── Per-user Google OAuth tokens (encrypted at rest) ──────────
-- Production-grade replacement for the single shared token.json file.
-- Each user connects their own Google account; the full authorized-user
-- credentials blob (including the refresh token) is encrypted with Fernet in
-- the application layer BEFORE insert (see google_token_store.py) and stored
-- in `encrypted_creds`. `expiry` and `scopes` are non-sensitive metadata kept
-- for quick "connected? / expiring?" lookups only.
CREATE TABLE IF NOT EXISTS jessica_google_tokens (
  user_email       TEXT PRIMARY KEY,
  encrypted_creds  TEXT NOT NULL,
  expiry           TIMESTAMPTZ,
  scopes           JSONB NOT NULL DEFAULT '[]',
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Reuse the memory table's timestamp trigger pattern for updated_at.
CREATE OR REPLACE FUNCTION update_jessica_google_tokens_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER jessica_google_tokens_updated_at
  BEFORE UPDATE ON jessica_google_tokens
  FOR EACH ROW EXECUTE FUNCTION update_jessica_google_tokens_updated_at();

ALTER TABLE jessica_google_tokens ENABLE ROW LEVEL SECURITY;

-- Service role only — these are secrets; no anon/authenticated access.
CREATE POLICY "service_role_google_tokens_all"
  ON jessica_google_tokens FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- ── Scheduled Emails Table ─────────────────────────────────────

CREATE TABLE IF NOT EXISTS jessica_scheduled_emails (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  to_email     TEXT NOT NULL,
  subject      TEXT NOT NULL,
  body         TEXT NOT NULL,
  scheduled_at TIMESTAMPTZ NOT NULL,
  status       TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed')),
  sent_at      TIMESTAMPTZ,
  error        TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_jessica_scheduled_pending 
  ON jessica_scheduled_emails (status, scheduled_at) 
  WHERE status = 'pending';

-- ── Row Level Security for Scheduled Emails ───────────────────
ALTER TABLE jessica_scheduled_emails ENABLE ROW LEVEL SECURITY;

-- Allow service role full access (used by the agent backend and email worker)
CREATE POLICY "service_role_scheduled_all"
  ON jessica_scheduled_emails FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);
