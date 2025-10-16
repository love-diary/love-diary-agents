"""
Character Agent - Individual AI character powered by ASI-1 Mini
Manages character state, memory, and conversations
"""

import time
import json
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

    def __init__(self, character_id: int):
        self.character_id = character_id
        self.was_active = True  # Flag for telemetry
        self.player_address: Optional[str] = None

        # LLM client (provider determined by config)
        self.llm = get_llm_provider()

        # Storage client
        self.storage = PostgresStorage()

        # In-memory state (replaces ctx.storage)
        self.state: Dict[str, Any] = {
            "character_id": character_id,
            "player_address": None,
            "player_name": None,
            "player_gender": None,
            "messages_today": [],
            "today_date": None,
            "backstory": None,  # Compressed version for chat
            "backstory_full": None,  # Full version for database
            "character_data": {},
            "affection_level": 0,
            "total_messages": 0,
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

    async def process_message(
        self, player_address: str, player_name: str, message: str
    ) -> Dict[str, Any]:
        """Process incoming message and generate response"""

        # Update player context
        self.state["player_name"] = player_name

        # Check if new day - trigger diary save
        today = time.strftime("%Y-%m-%d")
        if self.state["today_date"] != today:
            await self._save_daily_diary()
            self.state["today_date"] = today
            self.state["messages_today"] = []

        # Add player message to context
        self.state["messages_today"].append(
            {"sender": "player", "text": message, "timestamp": time.time()}
        )

        self.state["total_messages"] += 1

        # Retrieve relevant memories from database
        relevant_memories = await self.storage.search_memories(
            character_id=self.character_id,
            player_address=player_address,
            query=message,
            limit=3,
        )

        # Build prompts
        system_prompt = self._build_system_prompt()
        context_prompt = self._build_context_prompt(relevant_memories)

        # Combine system prompt with context
        combined_system = f"{system_prompt}\n\n{context_prompt}"

        # Generate response with ASI-1 Mini
        response = await self.llm.chat(
            system=combined_system,
            messages=[
                {"role": "user", "content": message},
            ],
            reasoning_mode="Short",  # Fast for chat
            max_tokens=200,
        )

        response_text = response["text"]

        # Add response to messages
        self.state["messages_today"].append(
            {"sender": "character", "text": response_text, "timestamp": time.time()}
        )

        # Calculate affection change
        affection_change = self._calculate_affection(message, response_text)
        self.state["affection_level"] += affection_change

        logger.info(
            "message_processed",
            character_id=self.character_id,
            affection_change=affection_change,
            total_messages_today=len(self.state["messages_today"]),
        )

        return {"text": response_text, "affection_change": affection_change}

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
        return prompts.build_context_prompt(
            recent_messages=self.state["messages_today"],
            player_name=self.state["player_name"],
            memories=memories,
        )

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

    def _calculate_affection(self, player_msg: str, char_response: str) -> int:
        """Calculate affection change based on conversation"""
        # Simple heuristic - replace with smarter logic later
        player_lower = player_msg.lower()

        # Positive keywords
        if any(
            word in player_lower
            for word in [
                "love",
                "beautiful",
                "amazing",
                "wonderful",
                "adore",
                "perfect",
            ]
        ):
            return 3
        elif any(
            word in player_lower
            for word in ["like", "nice", "good", "enjoy", "happy", "fun"]
        ):
            return 2
        elif any(word in player_lower for word in ["thanks", "thank", "appreciate"]):
            return 1

        # Neutral
        return 1

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

        # Save greeting to messages_today
        self.state["messages_today"].append({
            "sender": "character",
            "text": greeting_message,
            "timestamp": time.time(),
        })

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
