-- ============================================================================
-- Migration: 001 - Initial Schema
-- Description: Create agent_states table for character agent persistence
-- Author: Love Diary Team
-- Date: 2025-10-15
-- ============================================================================

-- Agent States Table
-- Stores persistent state for each character-player relationship
CREATE TABLE IF NOT EXISTS agent_states (
    -- Primary Key: Unique per character-player pair
    character_id INTEGER NOT NULL,
    player_address TEXT NOT NULL,

    -- Player Information (set once at creation)
    -- Structure: {name: str, gender: str, timezone: int}
    player_info JSONB NOT NULL,

    -- Player timezone extracted for indexing (-12 to +12)
    -- Used for batch diary generation by timezone
    player_timezone SMALLINT NOT NULL,

    -- Character NFT Data (from blockchain, never changes)
    -- Structure: {name, birthYear, birthTimestamp, gender, sexualOrientation,
    --             occupationId, personalityId, language, mintedAt, isBonded, secret}
    character_nft JSONB NOT NULL,

    -- AI-Generated Character Background (500-800 words)
    -- Generated once at character creation
    backstory TEXT,

    -- Evolving Relationship Summary (500-1000 words)
    -- Regenerated every 50-100 messages to capture relationship history
    relationship_context TEXT,
    context_message_count INTEGER DEFAULT 0,
    context_updated_at TIMESTAMP,

    -- Relationship Progress Metrics
    -- Updated after each message
    affection_level INTEGER DEFAULT 0,
    total_messages INTEGER DEFAULT 0,

    -- Ephemeral State Snapshot
    -- Structure: {messages_today: [{sender, text, timestamp}], today_date: str}
    -- Only populated during hibernation, NULL when agent is active
    hibernate_data JSONB,

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    hibernated_at TIMESTAMP,

    PRIMARY KEY (character_id, player_address)
);

-- Index for finding all agents owned by a player
CREATE INDEX IF NOT EXISTS idx_agent_states_player
    ON agent_states(player_address);

-- Index for timezone-based operations (batch diary generation)
CREATE INDEX IF NOT EXISTS idx_agent_states_timezone
    ON agent_states(player_timezone);

-- ============================================================================
-- Migration Tracking Table (optional, for future migrations)
-- ============================================================================
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TIMESTAMP DEFAULT NOW()
);

-- Record this migration
INSERT INTO schema_migrations (version, name)
VALUES (1, '001_initial_schema')
ON CONFLICT (version) DO NOTHING;

-- ============================================================================
-- Verification Queries (run these to verify the migration worked)
-- ============================================================================

-- Check table exists
-- SELECT COUNT(*) FROM agent_states;

-- Check indexes
-- SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'agent_states';

-- Check migration was recorded
-- SELECT * FROM schema_migrations;
