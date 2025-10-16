"""
Character Agent - Individual AI character powered by ASI-1 Mini
Manages character state, memory, and conversations
"""

import time
import json
import asyncio
from typing import Dict, List, Any, Optional
import structlog

from .llm import get_llm_provider, prompts
from .postgres_storage import PostgresStorage
from .config import settings

logger = structlog.get_logger()


GENDER_MAP = {
    0: "Male",
    1: "Female",
    2: "NonBinary",
}

ORIENTATION_MAP = {
    0: "Straight",
    1: "SameGender",
    2: "Bisexual",
    3: "Pansexual",
    4: "Asexual",
}

# Placeholder occupation names (should match frontend)
OCCUPATION_NAMES = [
    "Software Engineer",
    "Doctor",
    "Teacher",
    "Artist",
    "Chef",
    "Musician",
    "Writer",
    "Athlete",
    "Scientist",
    "Entrepreneur",
]

# Placeholder personality names (should match frontend)
PERSONALITY_NAMES = [
    "Adventurous",
    "Caring",
    "Creative",
    "Analytical",
    "Outgoing",
    "Reserved",
    "Optimistic",
    "Pragmatic",
    "Romantic",
    "Mysterious",
]


def get_wealth_level(secret: str) -> tuple[str, str]:
    """
    Derive wealth level from character's secret (deterministic randomness)
    Uses last 2 hex digits (0-255) for distribution

    Distribution:
    - Super Rich (1.17%): 0-2
    - Rich (3.91%): 3-12
    - Comfortable (14.84%): 13-50
    - Middle Class (50.00%): 51-178
    - Poor (25.00%): 179-242
    - Extreme Poverty (5.08%): 243-255

    Returns:
        (level_id, description) tuple
    """
    # Get last 2 hex digits and convert to int (0-255)
    value = int(secret[-2:], 16)

    if value < 3:  # 0-2
        return ("super_rich", "from an extremely wealthy family with generational wealth")
    elif value < 13:  # 3-12
        return ("rich", "from a well-off family with financial security")
    elif value < 51:  # 13-50
        return ("comfortable", "from a comfortable middle-class family")
    elif value < 179:  # 51-178
        return ("middle_class", "from a typical middle-class family")
    elif value < 243:  # 179-242
        return ("poor", "from a struggling working-class family")
    else:  # 243-255
        return ("extreme_poverty", "from a family facing severe financial hardship")


class CharacterAgent:
    """
    Individual character agent managing conversation and memory
    """

    def __init__(self, character_id: int, storage: Optional[PostgresStorage] = None):
        self.character_id = character_id
        self.was_active = True  # Flag for telemetry
        self.player_address: Optional[str] = None

        # LLM client (provider determined by config)
        self.llm = get_llm_provider()

        # Storage client (shared instance passed from manager)
        self.storage = storage

        # Compression lock - ensures messages wait for background compression to finish
        self.compression_lock = asyncio.Lock()

        # In-memory state (replaces ctx.storage)
        self.state: Dict[str, Any] = {
            "character_id": character_id,
            "player_address": None,
            "player_name": None,
            "player_gender": None,
            "messages_today": [],  # Rolling window of last 15 messages (for UI display)
            "messages_for_compression": [],  # Accumulates messages until compression
            "today_date": None,
            "backstory": None,  # Compressed version for chat
            "backstory_full": None,  # Full version for database
            "character_data": {},
            "affection_level": 10,  # Initial: 10, Max: 1000
            "total_messages": 0,
            "conversation_summary": "",  # Compressed conversation history
            "last_compression_at": 0.0,  # Timestamp of last compression
            "pending_affection_delta": 0,  # Affection change from background compression
        }

    async def initialize(
        self,
        character_data: Dict,
        player_address: str,
        player_name: str,
        player_gender: str,
    ):
        """Initialize new agent with character and player data"""
        self.player_address = player_address

        self.state.update(
            {
                "player_address": player_address,
                "player_name": player_name,
                "player_gender": player_gender,
                "character_data": character_data,
                "today_date": time.strftime("%Y-%m-%d"),
                "messages_today": [],
                "created_at": time.time(),
            }
        )

        logger.info(
            "agent_initialized",
            character_id=self.character_id,
            character_name=character_data.get("name"),
        )

    async def generate_backstory(self) -> str:
        """Generate background story using LLM"""
        char = self.state["character_data"]

        # Parse character traits
        gender = GENDER_MAP.get(char["gender"], "NonBinary")
        occupation = OCCUPATION_NAMES[char["occupationId"] % len(OCCUPATION_NAMES)]
        personality = PERSONALITY_NAMES[
            char["personalityId"] % len(PERSONALITY_NAMES)
        ]
        age = 2025 - char["birthYear"]

        # Get wealth level from secret (deterministic randomness)
        wealth_level, wealth_desc = get_wealth_level(char["secret"])

        # Build prompt using template
        prompt = prompts.build_backstory_prompt(
            character_name=char["name"],
            age=age,
            birth_year=char["birthYear"],
            gender=gender,
            occupation=occupation,
            personality=personality,
            wealth_desc=wealth_desc,
            player_name=self.state["player_name"],
            player_gender=self.state["player_gender"],
        )

        response = await self.llm.complete(
            prompt=prompt, reasoning_mode="Complete", max_tokens=1000
        )

        backstory = response["text"]

        logger.info(
            "backstory_generated",
            character_id=self.character_id,
            length=len(backstory),
        )

        # Generate compressed summary for efficient chat usage
        summary_prompt = prompts.build_backstory_summary_prompt(
            backstory=backstory,
            character_name=char["name"],
            player_name=self.state["player_name"],
        )

        summary_response = await self.llm.complete(
            prompt=summary_prompt,
            reasoning_mode="Short",  # Fast compression
            max_tokens=250,
        )

        backstory_summary = summary_response["text"]

        # Store both versions:
        # - Full: for database archive and display
        # - Compressed: for efficient chat usage
        self.state["backstory_full"] = backstory
        self.state["backstory"] = backstory_summary

        logger.info(
            "backstory_compressed",
            character_id=self.character_id,
            original_length=len(backstory),
            compressed_length=len(backstory_summary),
            compression_ratio=f"{len(backstory_summary)/len(backstory)*100:.1f}%",
        )

        # Return full version for display to user
        return backstory

    def _should_compress_conversation(self) -> bool:
        """Check if conversation should be compressed"""
        message_count = len(self.state["messages_for_compression"])

        # Estimate tokens (rough: 1 word ≈ 1.3 tokens)
        conversation_text = str(self.state.get("conversation_summary", ""))
        for msg in self.state["messages_for_compression"]:
            conversation_text += msg["text"]

        estimated_tokens = len(conversation_text.split()) * 1.3

        # Compress if: 15+ messages OR 800+ tokens
        return message_count >= 15 or estimated_tokens > 800

    async def compress_and_update_affection(self):
        """
        Background task: Compress conversation and store affection delta
        Called AFTER HTTP response is sent
        Acquires lock to prevent concurrent message processing
        """
        async with self.compression_lock:
            try:
                logger.info(
                    "background_compression_started",
                    character_id=self.character_id,
                    messages_to_compress=len(self.state["messages_for_compression"]),
                )

                affection_delta = await self._compress_conversation()

                # Store delta for next message to apply
                self.state["pending_affection_delta"] = affection_delta

                logger.info(
                    "background_compression_complete",
                    character_id=self.character_id,
                    affection_delta=affection_delta,
                )

            except Exception as e:
                logger.error(
                    "background_compression_failed",
                    character_id=self.character_id,
                    error=str(e),
                )

    async def _compress_conversation(self) -> int:
        """
        Compress conversation and get affection delta
        Returns: affection_delta (-5 to +5)
        """
        char = self.state["character_data"]

        # Build compression prompt using messages_for_compression
        prompt = prompts.build_conversation_compression_prompt(
            character_name=char["name"],
            player_name=self.state["player_name"],
            conversation_summary=self.state.get("conversation_summary", ""),
            recent_messages=self.state["messages_for_compression"],
        )

        logger.info(
            "compressing_conversation",
            character_id=self.character_id,
            messages_to_compress=len(self.state["messages_for_compression"]),
        )

        # Use LLM to compress and analyze affection
        response = await self.llm.complete(
            prompt=prompt,
            reasoning_mode="Complete",  # Deep analysis
            max_tokens=400,
        )

        result_text = response["text"]

        # Parse result (format: SUMMARY: ... AFFECTION_DELTA: X REASONING: ...)
        try:
            lines = result_text.strip().split("\n")
            summary = ""
            affection_delta = 0
            reasoning = ""

            for line in lines:
                if line.startswith("SUMMARY:"):
                    summary = line.replace("SUMMARY:", "").strip()
                elif line.startswith("AFFECTION_DELTA:"):
                    delta_str = line.replace("AFFECTION_DELTA:", "").strip()
                    # Extract number (handle "+3" or "3" or "-2")
                    import re
                    match = re.search(r'[-+]?\d+', delta_str)
                    if match:
                        affection_delta = int(match.group())
                        # Clamp to -5 to +5
                        affection_delta = max(-5, min(5, affection_delta))
                elif line.startswith("REASONING:"):
                    reasoning = line.replace("REASONING:", "").strip()

            # Update conversation summary
            self.state["conversation_summary"] = summary
            self.state["last_compression_at"] = time.time()

            # Clear only messages_for_compression (keep messages_today for UI display)
            self.state["messages_for_compression"] = []

            logger.info(
                "conversation_compressed",
                character_id=self.character_id,
                affection_delta=affection_delta,
                new_summary_length=len(summary),
                reasoning=reasoning,
            )

            return affection_delta

        except Exception as e:
            logger.error(
                "compression_parse_failed",
                character_id=self.character_id,
                error=str(e),
                llm_response=result_text,
            )
            # Fallback: no affection change if parsing fails
            return 0

    async def process_message(
        self, player_address: str, player_name: str, message: str
    ) -> Dict[str, Any]:
        """Process incoming message and generate response"""

        # Wait for any ongoing background compression to finish
        # This ensures we get the correct pending_affection_delta
        async with self.compression_lock:
            # Update player context
            self.state["player_name"] = player_name

            # Check if new day - trigger diary save
            today = time.strftime("%Y-%m-%d")
            if self.state["today_date"] != today:
                await self._save_daily_diary()
                self.state["today_date"] = today
                self.state["messages_today"] = []
                self.state["messages_for_compression"] = []  # Clear compression list too
                self.state["conversation_summary"] = ""  # Reset summary for new day
                self.state["pending_affection_delta"] = 0  # Reset pending affection

            # STEP 1: Apply pending affection from previous background compression
            affection_from_compression = self.state.get("pending_affection_delta", 0)
            if affection_from_compression != 0:
                self.state["affection_level"] += affection_from_compression
                # Clamp affection to 0-1000 range
                self.state["affection_level"] = max(0, min(1000, self.state["affection_level"]))
                # Clear pending delta after applying
                self.state["pending_affection_delta"] = 0

                logger.info(
                    "applied_pending_affection",
                    character_id=self.character_id,
                    affection_delta=affection_from_compression,
                    new_affection_level=self.state["affection_level"],
                )

                # Save updated affection to database immediately
                await self.storage.update_progress(
                    character_id=self.character_id,
                    player_address=player_address,
                    affection_level=self.state["affection_level"],
                    total_messages=self.state["total_messages"],
                )

            # STEP 2: Add player message to both lists
            player_message = {"sender": "player", "text": message, "timestamp": time.time()}

            # Add to both lists
            self.state["messages_today"].append(player_message)
            self.state["messages_for_compression"].append(player_message)

            # Maintain rolling window for messages_today (max 15)
            if len(self.state["messages_today"]) > 15:
                self.state["messages_today"].pop(0)  # Remove oldest

            self.state["total_messages"] += 1

            # STEP 3: Retrieve relevant memories from database
            relevant_memories = await self.storage.search_memories(
                character_id=self.character_id,
                player_address=player_address,
                query=message,
                limit=3,
            )

            # STEP 4: Build prompts
            system_prompt = self._build_system_prompt()
            context_prompt = self._build_context_prompt(relevant_memories)

            # Combine system prompt with context
            combined_system = f"{system_prompt}\n\n{context_prompt}"

            # STEP 5: Generate response with ASI-1 Mini (FAST - no compression blocking)
            response = await self.llm.chat(
                system=combined_system,
                messages=[
                    {"role": "user", "content": message},
                ],
                reasoning_mode="Short",  # Fast for chat
                max_tokens=200,
            )

            response_text = response["text"]

            # STEP 6: Add response to messages with affection change
            character_message = {
                "sender": "character",
                "text": response_text,
                "timestamp": time.time(),
            }
            # Add affectionChange if it's non-zero (for display in chat)
            if affection_from_compression != 0:
                character_message["affectionChange"] = affection_from_compression

            # Add to both lists
            self.state["messages_today"].append(character_message)
            self.state["messages_for_compression"].append(character_message)

            # Maintain rolling window for messages_today (max 15)
            if len(self.state["messages_today"]) > 15:
                self.state["messages_today"].pop(0)  # Remove oldest

            logger.info(
                "message_processed",
                character_id=self.character_id,
                affection_from_compression=affection_from_compression,
                current_affection=self.state["affection_level"],
                total_messages_today=len(self.state["messages_today"]),
            )

            return {
                "text": response_text,
                "affection_change": affection_from_compression,  # Show affection from previous compression
                "should_compress": self._should_compress_conversation(),  # Tell caller to schedule compression
            }

    def _build_system_prompt(self) -> str:
        """Build system prompt from character traits"""
        char = self.state["character_data"]

        gender = GENDER_MAP.get(char["gender"], "NonBinary")
        occupation = OCCUPATION_NAMES[char["occupationId"] % len(OCCUPATION_NAMES)]
        personality = PERSONALITY_NAMES[
            char["personalityId"] % len(PERSONALITY_NAMES)
        ]
        age = 2025 - char["birthYear"]

        # Backstory is already compressed summary (no need for preview)
        backstory = self.state.get("backstory", "")

        return prompts.build_system_prompt(
            character_name=char["name"],
            age=age,
            gender=gender,
            occupation=occupation,
            personality=personality,
            backstory=backstory,
            player_name=self.state["player_name"],
            player_gender=self.state["player_gender"],
        )

    def _build_context_prompt(self, memories: List[Dict]) -> str:
        """Build context from recent messages and relevant memories"""
        context = ""

        # Add conversation summary if available
        if self.state.get("conversation_summary"):
            context += f"## Previous conversation summary:\n{self.state['conversation_summary']}\n\n"

        # Add recent messages and memories
        context += prompts.build_context_prompt(
            recent_messages=self.state["messages_today"],
            player_name=self.state["player_name"],
            memories=memories,
        )

        return context

    async def _save_daily_diary(self):
        """Save today's conversation as diary entry"""
        if not self.state["messages_today"]:
            return

        logger.info(
            "diary_save_started",
            character_id=self.character_id,
            message_count=len(self.state["messages_today"]),
        )

        # Build prompt using template
        char = self.state["character_data"]
        prompt = prompts.build_diary_prompt(
            character_name=char["name"],
            player_name=self.state["player_name"],
            conversation_messages=self.state["messages_today"],
        )

        diary_response = await self.llm.complete(
            prompt=prompt, reasoning_mode="Complete", max_tokens=400
        )

        diary_entry = diary_response["text"]

        # Save to database
        await self.storage.save_diary_entry(
            character_id=self.character_id,
            player_address=self.state["player_address"],
            date=self.state["today_date"],
            entry=diary_entry,
            message_count=len(self.state["messages_today"]),
        )

        logger.info(
            "diary_saved",
            character_id=self.character_id,
            entry_length=len(diary_entry),
        )


    async def generate_greeting(self) -> str:
        """Generate first greeting message using LLM based on backstory"""
        char = self.state["character_data"]

        # Extract the last paragraph of full backstory (how they first met)
        backstory_full = self.state.get("backstory_full", "")
        paragraphs = backstory_full.split('\n\n')
        backstory_ending = paragraphs[-1] if paragraphs else backstory_full[-200:]

        # Build greeting prompt
        prompt = prompts.build_greeting_prompt(
            character_name=char["name"],
            player_name=self.state["player_name"],
            backstory_ending=backstory_ending,
        )

        # Generate greeting with LLM
        response = await self.llm.complete(
            prompt=prompt,
            reasoning_mode="Short",
            max_tokens=100,
        )

        greeting_message = response["text"].strip()

        logger.info(
            "greeting_generated",
            character_id=self.character_id,
            greeting_length=len(greeting_message),
        )

        # Save greeting to both lists
        greeting_msg = {
            "sender": "character",
            "text": greeting_message,
            "timestamp": time.time(),
        }
        self.state["messages_today"].append(greeting_msg)
        self.state["messages_for_compression"].append(greeting_msg)

        return greeting_message

    def get_state(self) -> Dict[str, Any]:
        """Export state for hibernation"""
        return self.state.copy()

    async def restore_state(self, state: Dict[str, Any]):
        """Restore state from hibernation"""
        self.state = state
        self.player_address = state.get("player_address")

        logger.info(
            "agent_state_restored",
            character_id=self.character_id,
            total_messages=state.get("total_messages", 0),
        )
