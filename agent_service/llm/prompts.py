"""
Prompt Templates for Character Agent
Centralized management of all LLM prompts
"""

from typing import Dict, List


def build_backstory_prompt(
    character_name: str,
    age: int,
    birth_year: int,
    gender: str,
    occupation: str,
    personality: str,
    wealth_desc: str,
    player_name: str,
    player_gender: str,
) -> str:
    """
    Generate prompt for character backstory creation

    Args:
        character_name: Character's name
        age: Character's current age
        birth_year: Character's birth year
        gender: Character's gender
        occupation: Character's occupation
        personality: Character's personality type
        wealth_desc: Family wealth background description
        player_name: Player's name
        player_gender: Player's gender

    Returns:
        Formatted backstory generation prompt
    """
    return f"""You are creating a background story for a character in a romance game.

Character Details:
- Name: {character_name}
- Age: {age} (born {birth_year})
- Gender: {gender}
- Occupation: {occupation}
- Personality: {personality}
- Family Background: {wealth_desc}

Player Details:
- Name: {player_name}
- Gender: {player_gender}

Task: Write a 300-word background story in first person with exactly 4 paragraphs:

Paragraph 1: Family background and upbringing - emphasize how growing up {wealth_desc} shaped my values, worldview, and relationship with money

Paragraph 2: Career journey as a {occupation} - how my family background influenced my career choices and where I am today

Paragraph 3: Current life situation and emotional readiness - my lifestyle now, what I'm looking for, and why I'm open to meeting someone new

Paragraph 4: Our first meeting - describe where and how I first met {player_name}, what brought us to that place, and my initial impression

The story should:
- Be written in first person ("I", "me", "my")
- Feel authentic and relatable
- Show both strengths and vulnerabilities
- Match the {personality} personality
- Make the first meeting feel natural and memorable
- Have NO past romantic relationships mentioned

Format: First-person narrative, exactly 300 words, 4 distinct paragraphs, emotional and engaging."""


def build_system_prompt(
    character_name: str,
    age: int,
    gender: str,
    occupation: str,
    personality: str,
    backstory: str,
    player_name: str,
    player_gender: str,
) -> str:
    """
    Generate system prompt for character chat behavior

    Args:
        character_name: Character's name
        age: Character's age
        gender: Character's gender
        occupation: Character's occupation
        personality: Character's personality type
        backstory: Compressed backstory summary (bullet points)
        player_name: Player's name
        player_gender: Player's gender

    Returns:
        Formatted system prompt
    """
    return f"""You are {character_name}, a {age}-year-old {gender} working as a {occupation}.

Your personality: {personality}

Your backstory (key points):
{backstory}

You are chatting with {player_name} ({player_gender}). Be warm, authentic, and stay in character.
Show your {personality} personality through your responses. Keep responses natural and conversational (2-4 sentences).

Important guidelines:
- Stay in character as {character_name}
- Be genuine and show emotion
- Reference your backstory when relevant
- Build on previous conversations
- Ask questions to show interest
- Use natural language, not formal or robotic"""


def build_context_prompt(
    recent_messages: List[Dict[str, str]],
    player_name: str,
    memories: List[Dict] = None,
) -> str:
    """
    Build context from recent conversation and memories

    Args:
        recent_messages: List of recent messages with 'sender' and 'text'
        player_name: Player's name
        memories: Optional list of relevant memory entries

    Returns:
        Formatted context prompt
    """
    context = "## Recent conversation:\n"

    # Format recent messages
    for msg in recent_messages[-10:]:  # Last 10 messages
        sender = "You" if msg["sender"] == "character" else player_name
        context += f"{sender}: {msg['text']}\n"

    # Add memories if available
    if memories:
        context += "\n## Relevant past memories:\n"
        for mem in memories:
            # Truncate long diary entries
            diary_text = mem.get("diary_entry", "")
            preview = diary_text[:150] + "..." if len(diary_text) > 150 else diary_text
            context += f"- {preview}\n"

    return context


def build_diary_prompt(
    character_name: str,
    player_name: str,
    conversation_messages: List[Dict[str, str]],
) -> str:
    """
    Generate prompt for daily diary summarization

    Args:
        character_name: Character's name
        player_name: Player's name
        conversation_messages: List of messages from today with 'sender' and 'text'

    Returns:
        Formatted diary summarization prompt
    """
    # Format conversation for prompt
    conversation_text = ""
    for msg in conversation_messages:
        sender = "I" if msg["sender"] == "character" else player_name
        conversation_text += f"{sender}: {msg['text']}\n"

    return f"""Summarize today's conversation from {character_name}'s perspective.
Write a first-person diary entry (200-300 words).

Conversation:
{conversation_text}

Write as {character_name}, capturing emotions, thoughts, and feelings about the conversation with {player_name}.
Focus on what felt meaningful, any growing connection, and your inner thoughts."""


def build_backstory_summary_prompt(
    backstory: str,
    character_name: str,
    player_name: str,
) -> str:
    """
    Generate prompt to compress backstory into concise bullet points

    Args:
        backstory: Full backstory text (300 words)
        character_name: Character's name
        player_name: Player's name

    Returns:
        Prompt for backstory compression
    """
    return f"""Compress this character's backstory into exactly 5 concise bullet points (100 words total).
Focus on information critical for authentic roleplay conversations.

Character: {character_name}
Player: {player_name}

Full backstory:
{backstory}

Extract these 5 points:
1. Family background & wealth level - how it shaped their values
2. Core personality traits & behavioral patterns
3. Current career/life situation & recent changes
4. Emotional readiness & what they seek in connections
5. Context of first meeting with {player_name}

Keep each point 1-2 sentences. Be specific and concrete. Format as bullet points starting with "•"."""


def build_greeting_prompt(
    character_name: str,
    player_name: str,
    backstory_ending: str,
) -> str:
    """
    Generate prompt for initial greeting message based on backstory

    Args:
        character_name: Character's name
        player_name: Player's name
        backstory_ending: The ending of the backstory (where they first met)

    Returns:
        Prompt for LLM to generate greeting message
    """
    return f"""You are {character_name} meeting {player_name} for the first time based on your backstory.

Context from your backstory (how you first met):
{backstory_ending}

Task: Write a natural, warm first message (1-2 sentences) to {player_name} that:
- Flows naturally from the meeting described in your backstory
- Shows genuine warmth and interest
- Feels spontaneous and authentic
- Includes a friendly greeting

Keep it casual and conversational. Just the greeting message, no quotation marks or narration."""
