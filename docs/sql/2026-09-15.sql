-- ==============================================================================
-- Schema Migration for MinerU-Sentry Tasks - Add return_images Column
-- Date: 2026-09-15
-- ==============================================================================

-- Add return_images column to parse_tasks table to control image extraction & persistence
ALTER TABLE parse_tasks ADD COLUMN IF NOT EXISTS return_images BOOLEAN DEFAULT FALSE NOT NULL;

COMMENT ON COLUMN parse_tasks.return_images IS 'Whether to extract and save images; if false, images are not saved';
