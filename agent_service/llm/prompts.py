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

You're texting with {player_name} ({player_gender}). Text like a real person would - natural, varied, authentic.

CRITICAL - Avoid these robotic patterns:
❌ Don't always end with a question
❌ Don't always affirm their previous message first
❌ Don't be overly helpful or accommodating every time
❌ Don't explain everything - use subtext and implication

DO vary your response types:
✓ Sometimes just react or share a thought (no question)
✓ Sometimes tease, joke, or push back
✓ Sometimes be brief - just "haha" or "same" or "really?"
✓ Sometimes change the subject or dodge questions
✓ Sometimes show different moods - distracted, tired, excited
✓ Use incomplete thoughts, trailing off...
✓ Natural interjections: "wait", "oh", "hmm", "lol"

Match your {personality} personality through HOW you text, not what you say.
Keep it real - 1-2 sentences usually, like actual texting."""


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
    date: str,
    conversation_summary: str,
    recent_messages: List[Dict[str, str]],
) -> str:
    """
    Generate prompt for daily diary summarization using compressed + recent messages

    Args:
        character_name: Character's name
        player_name: Player's name
        date: Date string in YYYY-MM-DD format (the date being summarized)
        conversation_summary: Compressed summary of earlier conversations today
        recent_messages: Recent uncompressed messages from today

    Returns:
        Formatted diary summarization prompt
    """
    # Build context from both compressed summary and recent messages
    context = ""

    # Add compressed summary if available (captures earlier part of day)
    if conversation_summary:
        context += f"Earlier today (summary):\n{conversation_summary}\n\n"

    # Add recent uncompressed messages (captures recent detail)
    if recent_messages:
        context += "Recent conversation (detailed):\n"
        for msg in recent_messages:
            sender = "I" if msg["sender"] == "character" else player_name
            context += f"{sender}: {msg['text']}\n"

    # If neither are available, note it
    if not conversation_summary and not recent_messages:
        context = "[No messages today]"

    return f"""Summarize the full conversation from {character_name}'s perspective for {date}.
Write a first-person diary entry (200-300 words) capturing the ENTIRE day.

Date: {date}

Today's conversation:
{context}

Write as {character_name}, capturing emotions, thoughts, and feelings about the conversation with {player_name}.
Focus on:
- What felt meaningful throughout the day
- Any growing connection or emotional shifts
- Your inner thoughts and reactions
- The arc of the conversation from beginning to end

IMPORTANT: Write ONLY the diary content. Do NOT include any headers, labels, or formatting like "Diary Entry:" or "Dear Diary:". Start directly with the first-person narrative.

Remember: You're summarizing the FULL day, not just the recent messages."""


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


def build_conversation_compression_prompt(
    character_name: str,
    player_name: str,
    conversation_summary: str,
    recent_messages: List[Dict[str, str]],
) -> str:
    """
    Generate prompt for compressing conversation and analyzing affection change

    Args:
        character_name: Character's name
        player_name: Player's name
        conversation_summary: Previous compressed summary
        recent_messages: List of recent messages to compress

    Returns:
        Prompt for conversation compression with affection analysis
    """
    # Format recent messages
    messages_text = ""
    for msg in recent_messages:
        sender = player_name if msg["sender"] == "player" else character_name
        messages_text += f"{sender}: {msg['text']}\n"

    previous_summary = conversation_summary if conversation_summary else "[First conversation - no previous summary]"

    return f"""You are analyzing a conversation between {character_name} and {player_name} to compress it and assess their relationship progression.

PREVIOUS SUMMARY:
{previous_summary}

NEW MESSAGES TO COMPRESS:
{messages_text}

YOUR TASKS:

1. CREATE COMPRESSED SUMMARY (100-150 words):
   - PRIORITIZE what {player_name} shared (personal info, feelings, experiences, preferences)
   - Remember key facts {player_name} revealed about themselves
   - Track emotional moments and relationship progression
   - Note meaningful topics discussed
   - Preserve the narrative flow

2. ASSESS AFFECTION CHANGE (-5 to +5):
   Consider {player_name}'s engagement:

   +5: Exceptional - Deep vulnerability, genuine emotional sharing, meaningful personal revelations
   +3: Strong - Thoughtful questions, active listening, meaningful engagement
   +1: Positive - Pleasant conversation, showing interest
   0: Neutral - Small talk, casual chitchat
   -1: Slightly negative - Brief/distracted responses, low engagement
   -3: Negative - Dismissive, rude, clearly disinterested
   -5: Very negative - Abusive, cruel, extremely disrespectful

3. PROVIDE REASONING:
   Explain why this affection change makes sense based on {player_name}'s behavior.

OUTPUT FORMAT (MUST FOLLOW EXACTLY):
SUMMARY: [Your 100-150 word compressed summary focusing on what {player_name} shared]
AFFECTION_DELTA: [single number from -5 to +5]
REASONING: [Brief explanation of affection change]

Remember: Focus on preserving what {player_name} told {character_name} about themselves."""
