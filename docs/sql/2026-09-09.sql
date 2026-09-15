-- ==============================================================================
-- Schema Definition for MinerU-Sentry Tasks and Segments
-- Date: 2026-09-09
-- ==============================================================================

-- 1. Main Parsing Tasks Table
CREATE TABLE IF NOT EXISTS parse_tasks (
    id VARCHAR(32) PRIMARY KEY,
    create_by VARCHAR(32) DEFAULT '' NOT NULL,
    create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_by VARCHAR(32),
    update_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    file_name VARCHAR(255) NOT NULL,
    file_hash VARCHAR(64) NOT NULL,
    file_path VARCHAR(1024) NOT NULL,
    file_size BIGINT DEFAULT 0 NOT NULL,
    total_pages INTEGER,
    status VARCHAR(32) DEFAULT 'pending' NOT NULL,
    backend VARCHAR(64) DEFAULT 'hybrid-engine' NOT NULL,
    effort VARCHAR(32) DEFAULT 'medium' NOT NULL,
    parse_method VARCHAR(32) DEFAULT 'auto' NOT NULL,
    formula_enable BOOLEAN DEFAULT TRUE NOT NULL,
    table_enable BOOLEAN DEFAULT TRUE NOT NULL,
    start_page_id INTEGER DEFAULT 0 NOT NULL,
    end_page_id INTEGER DEFAULT 99999 NOT NULL,
    last_processed_page INTEGER,
    output_dir VARCHAR(1024) NOT NULL,
    final_md_path VARCHAR(1024),
    error_message TEXT,
    is_resumed BOOLEAN DEFAULT FALSE NOT NULL,
    parent_task_id VARCHAR(32)
);

COMMENT ON TABLE parse_tasks IS 'Document parsing task metadata and status';
COMMENT ON COLUMN parse_tasks.file_hash IS 'SHA-256 hash of the input document for deduplication and auto-resume';
COMMENT ON COLUMN parse_tasks.status IS 'Current status: pending, waking_gpu, processing, completed, failed, interrupted';
COMMENT ON COLUMN parse_tasks.last_processed_page IS 'Last successfully parsed page index (0-indexed)';

CREATE INDEX IF NOT EXISTS idx_parse_tasks_hash ON parse_tasks (file_hash);
CREATE INDEX IF NOT EXISTS idx_parse_tasks_status ON parse_tasks (status);
CREATE INDEX IF NOT EXISTS idx_parse_tasks_created_at ON parse_tasks (create_at);

-- 2. Parsing Segments Table (No Foreign Keys as per skill specification)
CREATE TABLE IF NOT EXISTS task_segments (
    id VARCHAR(32) PRIMARY KEY,
    create_by VARCHAR(32) DEFAULT '' NOT NULL,
    create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_by VARCHAR(32),
    update_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    task_id VARCHAR(32) NOT NULL,
    segment_order INTEGER DEFAULT 0 NOT NULL,
    start_page INTEGER NOT NULL,
    end_page INTEGER NOT NULL,
    status VARCHAR(32) DEFAULT 'pending' NOT NULL,
    mineru_task_id VARCHAR(128),
    segment_dir VARCHAR(1024),
    md_path VARCHAR(1024),
    middle_json_path VARCHAR(1024),
    error_message TEXT
);

COMMENT ON TABLE task_segments IS 'Individual execution segments for multi-segment and resumed tasks';
COMMENT ON COLUMN task_segments.task_id IS 'Associated task id (logical relation, no foreign key)';

CREATE INDEX IF NOT EXISTS idx_task_segments_task_id ON task_segments (task_id);
