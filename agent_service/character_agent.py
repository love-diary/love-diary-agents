"""
Character Agent - Individual AI character powered by ASI-1 Mini
Manages character state, memory, and conversations
"""

import time
import json
from typing import Dict, List, Any, Optional
import structlog

from .asi_mini_client import ASIMiniClient
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

        # LLM client
        self.llm = ASIMiniClient()

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
            "backstory": None,
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
        """Generate background story using ASI-1 Mini"""
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

        prompt = f"""You are creating a background story for a character in a romance game.

Character Details:
- Name: {char['name']}
- Age: {age} (born {char['birthYear']})
- Gender: {gender}
- Occupation: {occupation}
- Personality: {personality}
- Family Background: {wealth_desc}

Player Details:
- Name: {self.state['player_name']}
- Gender: {self.state['player_gender']}

Task: Write a 300-word background story in first person with exactly 4 paragraphs:

Paragraph 1: Family background and upbringing - emphasize how growing up {wealth_desc} shaped my values, worldview, and relationship with money

Paragraph 2: Career journey as a {occupation} - how my family background influenced my career choices and where I am today

Paragraph 3: Current life situation and emotional readiness - my lifestyle now, what I'm looking for, and why I'm open to meeting someone new

Paragraph 4: Our first meeting - describe where and how I first met {self.state['player_name']}, what brought us to that place, and my initial impression

The story should:
- Be written in first person ("I", "me", "my")
- Feel authentic and relatable
- Show both strengths and vulnerabilities
- Match the {personality} personality
- Make the first meeting feel natural and memorable
- Have NO past romantic relationships mentioned

Format: First-person narrative, exactly 300 words, 4 distinct paragraphs, emotional and engaging."""

        response = await self.llm.complete(
            prompt=prompt, reasoning_mode="Complete", max_tokens=1000
        )

        backstory = response["text"]
        self.state["backstory"] = backstory

        logger.info(
            "backstory_generated",
            character_id=self.character_id,
            length=len(backstory),
        )

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

        # Generate response with ASI-1 Mini
        response = await self.llm.chat(
            system=system_prompt,
            messages=[
                {"role": "system", "content": context_prompt},
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

        backstory_preview = self.state.get("backstory", "")[:500]

        return f"""You are {char['name']}, a {age}-year-old {gender} working as a {occupation}.

Your personality: {personality}

Your backstory:
{backstory_preview}...

You are chatting with {self.state['player_name']}. Be warm, authentic, and stay in character.
Show your {personality} personality through your responses. Keep responses natural and conversational (2-4 sentences).

Important guidelines:
- Stay in character as {char['name']}
- Be genuine and show emotion
- Reference your backstory when relevant
- Build on previous conversations
- Ask questions to show interest
- Use natural language, not formal or robotic"""

    def _build_context_prompt(self, memories: List[Dict]) -> str:
        """Build context from recent messages and relevant memories"""
        context = "## Recent conversation:\n"

        # Last 10 messages
        recent = self.state["messages_today"][-10:]
        for msg in recent:
            sender = (
                "You"
                if msg["sender"] == "character"
                else self.state["player_name"]
            )
            context += f"{sender}: {msg['text']}\n"

        if memories:
            context += "\n## Relevant past memories:\n"
            for mem in memories:
                context += f"- {mem['diary_entry'][:150]}...\n"

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

        # Summarize conversation
        conversation_text = ""
        for msg in self.state["messages_today"]:
            sender = "I" if msg["sender"] == "character" else self.state["player_name"]
            conversation_text += f"{sender}: {msg['text']}\n"

        char = self.state["character_data"]
        prompt = f"""Summarize today's conversation from {char['name']}'s perspective.
Write a first-person diary entry (200-300 words).

Conversation:
{conversation_text}

Write as {char['name']}, capturing emotions, thoughts, and feelings about the conversation with {self.state['player_name']}.
Focus on what felt meaningful, any growing connection, and your inner thoughts."""

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

    def get_greeting(self) -> str:
        """Get first greeting message"""
        char = self.state["character_data"]
        return f"Hi {self.state['player_name']}! I'm {char['name']}. It's really nice to meet you! 😊"

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
