-- MasterQUO AI 1.6: signals come from the bot's own strategies (S01-S10), not from the AI agent.
-- The ai_signals table is reused; old Claude proposals stay stored as source='AI' and are no longer shown.
ALTER TABLE ai_signals ADD COLUMN source TEXT NOT NULL DEFAULT 'AI';
ALTER TABLE ai_signals ADD COLUMN setup_id TEXT;
ALTER TABLE ai_signals ADD COLUMN event_id TEXT;
ALTER TABLE ai_signals ADD COLUMN strategy_id TEXT;
ALTER TABLE ai_signals ADD COLUMN strategy_name TEXT;
ALTER TABLE ai_signals ADD COLUMN timeframe TEXT;
ALTER TABLE ai_signals ADD COLUMN setup_score REAL;
CREATE INDEX IF NOT EXISTS ix_ai_signals_setup ON ai_signals(setup_id);
