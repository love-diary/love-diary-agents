"""
PostgreSQL Storage Client
Handles all database operations for agent state persistence using Supabase
"""

import asyncpg
import json
from typing import Dict, Optional, Any
import structlog

from .config import settings

logger = structlog.get_logger()


class PostgresStorage:
    """
    PostgreSQL storage client for agent states

    Expected JSONB Schemas:

    player_info = {
        "name": str,         # Player's display name
        "gender": str,       # "Male" | "Female" | "NonBinary"
        "timezone": int      # -12 to +12 (UTC offset)
    }

    character_nft = {
        "name": str,              # Character name
        "birthYear": int,         # Birth year (e.g., 1998)
        "birthTimestamp": int,    # Unix timestamp
        "gender": int,            # 0=Male, 1=Female, 2=NonBinary
        "sexualOrientation": int, # 0-4
        "occupationId": int,      # 0-9
        "personalityId": int,     # 0-9
        "language": int,          # 0=EN
        "mintedAt": int,          # Unix timestamp
        "isBonded": bool,         # Bonding status
        "secret": str             # bytes32 as hex
    }

    hibernate_data = {
        "messages_today": [       # List of message objects
            {
                "sender": str,    # "player" | "character"
                "text": str,      # Message content
                "timestamp": float # Unix timestamp
            }
        ],
        "today_date": str,        # ISO date "YYYY-MM-DD"
        "backstory": str          # Compressed backstory (bullet points)
    }
    """

    def __init__(self):
        self.database_url = settings.DATABASE_URL
        self.pool: Optional[asyncpg.Pool] = None
        self.is_initialized = False

    async def initialize(self):
        """Initialize PostgreSQL connection pool"""
        if self.is_initialized:
            return

        try:
            self.pool = await asyncpg.create_pool(
                self.database_url,
                min_size=2,
                max_size=10,
                command_timeout=60
            )
            self.is_initialized = True
            logger.info("postgres_storage_initialized")
        except Exception as e:
            logger.error("postgres_init_failed", error=str(e))
            raise

    async def agent_state_exists(
        self, character_id: int, player_address: str
    ) -> bool:
        """Check if agent state exists for this character-player pair"""
        try:
            # Normalize address to lowercase (addresses are stored lowercase)
            player_address_normalized = player_address.lower()

            async with self.pool.acquire() as conn:
                result = await conn.fetchval(
                    """
                    SELECT EXISTS(
                        SELECT 1 FROM agent_states
                        WHERE character_id = $1 AND player_address = $2
                    )
                    """,
                    character_id,
                    player_address_normalized
                )
                return result
        except Exception as e:
            logger.error(
                "agent_exists_check_failed",
                character_id=character_id,
                error=str(e)
            )
            return False

    async def load_agent_state(
        self, character_id: int, player_address: str
    ) -> Optional[Dict[str, Any]]:
        """Load complete agent state from database"""
        try:
            # Normalize address to lowercase (addresses are stored lowercase)
            player_address_normalized = player_address.lower()

            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT
                        character_id,
                        player_address,
                        player_info,
                        player_timezone,
                        character_nft,
                        backstory,
                        relationship_context,
                        context_message_count,
                        context_updated_at,
                        affection_level,
                        total_messages,
                        hibernate_data,
                        created_at,
                        updated_at,
                        hibernated_at
                    FROM agent_states
                    WHERE character_id = $1 AND player_address = $2
                    """,
                    character_id,
                    player_address_normalized
                )

                if not row:
                    return None

                # Parse JSONB fields (asyncpg may return them as strings or dicts)
                def parse_json_field(value):
                    if value is None:
                        return None
                    if isinstance(value, str):
                        return json.loads(value)
                    return value

                # Convert row to dict
                state = {
                    "character_id": row["character_id"],
                    "player_address": row["player_address"],
                    "player_info": parse_json_field(row["player_info"]),
                    "player_timezone": row["player_timezone"],
                    "character_nft": parse_json_field(row["character_nft"]),
                    "backstory": row["backstory"],
                    "relationship_context": row["relationship_context"],
                    "context_message_count": row["context_message_count"],
                    "context_updated_at": row["context_updated_at"],
                    "affection_level": row["affection_level"],
                    "total_messages": row["total_messages"],
                    "hibernate_data": parse_json_field(row["hibernate_data"]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "hibernated_at": row["hibernated_at"],
                }

                logger.info(
                    "agent_state_loaded",
                    character_id=character_id,
                    total_messages=state["total_messages"]
                )

                return state

        except Exception as e:
            logger.error(
                "agent_state_load_failed",
                character_id=character_id,
                error=str(e)
            )
            return None

    async def save_agent_state(
        self,
        character_id: int,
        player_address: str,
        player_info: Dict[str, Any],
        character_nft: Dict[str, Any],
        backstory: Optional[str] = None,
        relationship_context: Optional[str] = None,
        context_message_count: int = 0,
        affection_level: int = 0,
        total_messages: int = 0,
        hibernate_data: Optional[Dict[str, Any]] = None
    ):
        """
        Save complete agent state (INSERT or UPDATE)

        Uses UPSERT pattern: INSERT with ON CONFLICT DO UPDATE
        """
        try:
            # Normalize address to lowercase for consistent storage
            player_address_normalized = player_address.lower()

            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO agent_states (
                        character_id,
                        player_address,
                        player_info,
                        player_timezone,
                        character_nft,
                        backstory,
                        relationship_context,
                        context_message_count,
                        affection_level,
                        total_messages,
                        hibernate_data
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    ON CONFLICT (character_id, player_address)
                    DO UPDATE SET
                        backstory = COALESCE(EXCLUDED.backstory, agent_states.backstory),
                        relationship_context = COALESCE(EXCLUDED.relationship_context, agent_states.relationship_context),
                        context_message_count = EXCLUDED.context_message_count,
                        affection_level = EXCLUDED.affection_level,
                        total_messages = EXCLUDED.total_messages,
                        hibernate_data = EXCLUDED.hibernate_data,
                        updated_at = NOW()
                    """,
                    character_id,
                    player_address_normalized,
                    json.dumps(player_info),
                    player_info["timezone"],  # Extract timezone for indexing
                    json.dumps(character_nft),
                    backstory,
                    relationship_context,
                    context_message_count,
                    affection_level,
                    total_messages,
                    json.dumps(hibernate_data) if hibernate_data else None
                )

                logger.info(
                    "agent_state_saved",
                    character_id=character_id,
                    total_messages=total_messages
                )

        except Exception as e:
            logger.error(
                "agent_state_save_failed",
                character_id=character_id,
                error=str(e)
            )
            raise

    async def update_progress(
        self,
        character_id: int,
        player_address: str,
        affection_level: int,
        total_messages: int
    ):
        """
        Quick update for frequently changing fields (after each message)
        """
        try:
            # Normalize address to lowercase
            player_address_normalized = player_address.lower()

            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE agent_states
                    SET
                        affection_level = $3,
                        total_messages = $4,
                        updated_at = NOW()
                    WHERE character_id = $1 AND player_address = $2
                    """,
                    character_id,
                    player_address_normalized,
                    affection_level,
                    total_messages
                )
        except Exception as e:
            logger.error(
                "progress_update_failed",
                character_id=character_id,
                error=str(e)
            )
            raise

    async def update_relationship_context(
        self,
        character_id: int,
        player_address: str,
        relationship_context: str,
        context_message_count: int
    ):
        """Update relationship context (every 50-100 messages)"""
        try:
            # Normalize address to lowercase
            player_address_normalized = player_address.lower()

            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE agent_states
                    SET
                        relationship_context = $3,
                        context_message_count = $4,
                        context_updated_at = NOW(),
                        updated_at = NOW()
                    WHERE character_id = $1 AND player_address = $2
                    """,
                    character_id,
                    player_address_normalized,
                    relationship_context,
                    context_message_count
                )

                logger.info(
                    "relationship_context_updated",
                    character_id=character_id,
                    message_count=context_message_count
                )

        except Exception as e:
            logger.error(
                "context_update_failed",
                character_id=character_id,
                error=str(e)
            )
            raise

    async def save_hibernation_state(
        self,
        character_id: int,
        player_address: str,
        hibernate_data: Dict[str, Any],
        affection_level: int,
        total_messages: int
    ):
        """Save agent state on hibernation"""
        try:
            # Normalize address to lowercase
            player_address_normalized = player_address.lower()

            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE agent_states
                    SET
                        hibernate_data = $3,
                        affection_level = $4,
                        total_messages = $5,
                        hibernated_at = NOW(),
                        updated_at = NOW()
                    WHERE character_id = $1 AND player_address = $2
                    """,
                    character_id,
                    player_address_normalized,
                    json.dumps(hibernate_data),
                    affection_level,
                    total_messages
                )

                logger.info(
                    "hibernation_state_saved",
                    character_id=character_id
                )

        except Exception as e:
            logger.error(
                "hibernation_save_failed",
                character_id=character_id,
                error=str(e)
            )
            raise

    async def clear_hibernation_data(
        self, character_id: int, player_address: str
    ):
        """Clear hibernate_data after agent wakes up"""
        try:
            # Normalize address to lowercase
            player_address_normalized = player_address.lower()

            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE agent_states
                    SET
                        hibernate_data = NULL,
                        updated_at = NOW()
                    WHERE character_id = $1 AND player_address = $2
                    """,
                    character_id,
                    player_address_normalized
                )
        except Exception as e:
            logger.error(
                "clear_hibernation_failed",
                character_id=character_id,
                error=str(e)
            )
            # Non-critical error, don't raise

    async def get_hibernated_agent_count(self) -> int:
        """Get count of all hibernated agents"""
        try:
            async with self.pool.acquire() as conn:
                count = await conn.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM agent_states
                    WHERE hibernated_at IS NOT NULL
                    """
                )
                return count or 0
        except Exception as e:
            logger.error("hibernated_count_failed", error=str(e))
            return 0

    # ========================================================================
    # Diary Methods (Stubs for now - will implement when diary table is ready)
    # ========================================================================

    async def save_diary_entry(
        self,
        character_id: int,
        player_address: str,
        date: str,
        entry: str,
        message_count: int
    ):
        """Save daily diary entry (stub - table not created yet)"""
        logger.info(
            "diary_entry_saved_stub",
            character_id=character_id,
            date=date,
            entry_length=len(entry)
        )
        # TODO: Implement when diary_entries table is created
        pass

    async def search_memories(
        self,
        character_id: int,
        player_address: str,
        query: str,
        limit: int = 3
    ) -> list:
        """Search diary entries (stub - will implement with pgvector)"""
        logger.info(
            "memory_search_stub",
            character_id=character_id,
            query_length=len(query)
        )
        # TODO: Implement when diary_entries table is created with pgvector
        return []

    async def save_character_profile(
        self, character_id: int, character_data: Dict, backstory: str
    ):
        """
        Save character profile (currently handled by save_agent_state)
        Kept for compatibility with agent_manager.py
        """
        # This is now part of agent_states, no separate action needed
        logger.info(
            "character_profile_save_noop",
            character_id=character_id
        )
        pass

    async def close(self):
        """Close connection pool"""
        if self.pool:
            await self.pool.close()
            logger.info("postgres_storage_closed")
