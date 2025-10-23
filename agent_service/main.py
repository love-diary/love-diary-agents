"""
Love Diary - Agent Service
FastAPI server for managing character agents
"""

import os
import time
from fastapi import FastAPI, Header, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import structlog
from pathlib import Path

from .agent_manager import AgentManager
from .config import settings
from .diary_scheduler import DiaryScheduler, set_diary_scheduler

# Setup structured logging
logger = structlog.get_logger()

# Initialize FastAPI app
app = FastAPI(
    title="Love Diary Agent Service",
    description="ASI-powered character agent management",
    version="0.1.0",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for character images
IMAGES_DIR = Path(os.getenv("IMAGES_DIR", "/var/www/love-diary-images"))
if IMAGES_DIR.exists():
    app.mount("/character-images", StaticFiles(directory=str(IMAGES_DIR)), name="character-images")
    logger.info("static_files_mounted", directory=str(IMAGES_DIR))
else:
    logger.warning("images_directory_not_found", directory=str(IMAGES_DIR), note="Character images will not be served")

# Initialize Agent Manager (singleton)
agent_manager = AgentManager()

# Track service stats
service_stats = {
    "start_time": time.time(),
    "total_requests": 0,
    "total_messages": 0,
}


# Pydantic Models
class CreateAgentRequest(BaseModel):
    playerName: str = Field(..., min_length=1, max_length=50)
    playerGender: str = Field(..., pattern="^(Male|Female|NonBinary)$")
    playerTimezone: int = Field(..., ge=-12, le=14, description="UTC offset in hours")


class CreateAgentResponse(BaseModel):
    status: str  # "created" | "already_exists"
    firstMessage: Optional[str] = None
    backstorySummary: Optional[str] = None
    agentAddress: Optional[str] = None


class SendMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    playerName: str = Field(..., min_length=1, max_length=50)
    timestamp: int


class SendMessageResponse(BaseModel):
    response: str
    timestamp: int
    affectionChange: int
    agentStatus: str  # "active" | "woke_from_hibernation"


class HealthResponse(BaseModel):
    status: str
    active_agents: int
    hibernated_agents: int
    total_messages_processed: int
    uptime_seconds: int


class CharacterInfoResponse(BaseModel):
    affectionLevel: int
    backstory: str
    recentConversation: List[Dict[str, Any]]
    totalMessages: int
    playerName: str
    playerGender: str
    imageUrl: Optional[str] = None


class DiaryListItem(BaseModel):
    date: str
    messageCount: int


class DiaryEntryResponse(BaseModel):
    date: str
    entry: str
    messageCount: int


class WalletInfoResponse(BaseModel):
    walletAddress: str
    loveBalance: int  # LOVE token balance in wei (18 decimals)


class GiftRequest(BaseModel):
    txHash: str = Field(..., min_length=66, max_length=66, pattern="^0x[a-fA-F0-9]{64}$")
    amount: int = Field(..., ge=100_000_000_000_000_000_000, le=1000_000_000_000_000_000_000)  # 100-1000 LOVE in wei


class GiftResponse(BaseModel):
    status: str  # "success" | "failed"
    affectionChange: int
    newAffectionLevel: int
    message: str
    characterMessage: Optional[str] = None  # Character's response to gift


class GenerateImageResponse(BaseModel):
    status: str  # "success" | "failed" | "already_exists"
    imageUrl: Optional[str] = None
    message: str


# Authentication Dependency
async def verify_service_token(authorization: Optional[str] = Header(None)):
    """Verify request comes from trusted backend"""
    if not authorization:
        logger.warning("request_missing_auth")
        raise HTTPException(401, "Missing Authorization header")

    token = authorization.replace("Bearer ", "")
    if token != settings.AGENT_SERVICE_SECRET:
        logger.warning("request_invalid_token")
        raise HTTPException(401, "Invalid service token")

    return True


# Routes
@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        active_agents=len(agent_manager.active_agents),
        hibernated_agents=await agent_manager.get_hibernated_count(),
        total_messages_processed=service_stats["total_messages"],
        uptime_seconds=int(time.time() - service_stats["start_time"]),
    )


@app.post("/agent/{character_id}/create", response_model=CreateAgentResponse)
async def create_agent(
    character_id: int,
    request: CreateAgentRequest,
    player_address: str = Header(None, alias="X-Player-Address"),
    authenticated: bool = Depends(verify_service_token),
):
    """
    Create a new agent with backstory generation
    This is called on first chat initialization
    """
    service_stats["total_requests"] += 1

    if not player_address:
        raise HTTPException(400, "Missing X-Player-Address header")

    logger.info(
        "agent_create_requested",
        character_id=character_id,
        player_address=player_address,
    )

    try:
        # Check if agent already exists
        if await agent_manager.agent_exists(character_id, player_address):
            logger.info("agent_already_exists", character_id=character_id)

            # Load existing backstory from database
            agent_state = await agent_manager.storage.load_agent_state(
                character_id, player_address
            )
            backstory = agent_state.get("backstory") if agent_state else None

            return CreateAgentResponse(
                status="already_exists",
                backstorySummary=backstory,
                agentAddress=f"agent://character_{character_id}",
            )

        # Create new agent with backstory
        result = await agent_manager.create_agent_with_backstory(
            character_id=character_id,
            player_address=player_address,
            player_name=request.playerName,
            player_gender=request.playerGender,
            player_timezone=request.playerTimezone,
        )

        logger.info(
            "agent_created",
            character_id=character_id,
            backstory_length=len(result["backstory"]),
        )

        return CreateAgentResponse(
            status="created",
            firstMessage=result["first_message"],
            backstorySummary=result["backstory"],
            agentAddress=f"agent://character_{character_id}",
        )

    except Exception as e:
        logger.error(
            "agent_create_failed", character_id=character_id, error=str(e)
        )
        raise HTTPException(500, f"Failed to create agent: {str(e)}")


@app.post("/agent/{character_id}/message", response_model=SendMessageResponse)
async def send_message(
    character_id: int,
    request: SendMessageRequest,
    background_tasks: BackgroundTasks,
    player_address: str = Header(None, alias="X-Player-Address"),
    authenticated: bool = Depends(verify_service_token),
):
    """
    Send a message to a character agent
    Agent will be woken from hibernation if needed
    Compression runs as background task after response is sent
    """
    service_stats["total_requests"] += 1
    service_stats["total_messages"] += 1

    if not player_address:
        raise HTTPException(400, "Missing X-Player-Address header")

    logger.info(
        "message_received",
        character_id=character_id,
        player_address=player_address,
        message_length=len(request.message),
    )

    try:
        # Get or wake agent
        agent = await agent_manager.get_or_create_agent(
            character_id, player_address
        )

        # Process message (fast - no compression blocking)
        response = await agent.process_message(
            player_address=player_address,
            player_name=request.playerName,
            message=request.message,
        )

        logger.info(
            "message_processed",
            character_id=character_id,
            response_length=len(response["text"]),
            affection_change=response["affection_change"],
        )

        # Schedule compression as background task if needed
        if response.get("should_compress", False):
            logger.info(
                "scheduling_background_compression",
                character_id=character_id,
            )
            background_tasks.add_task(agent.compress_and_update_affection)

        # Return response immediately (compression runs after this)
        return SendMessageResponse(
            response=response["text"],
            timestamp=int(time.time()),
            affectionChange=response["affection_change"],
            agentStatus="active" if agent.was_active else "woke_from_hibernation",
        )

    except Exception as e:
        logger.error(
            "message_processing_failed",
            character_id=character_id,
            error=str(e),
        )
        raise HTTPException(500, f"Failed to process message: {str(e)}")


@app.get("/agent/{character_id}/info", response_model=CharacterInfoResponse)
async def get_character_info(
    character_id: int,
    background_tasks: BackgroundTasks,
    player_address: str = Header(None, alias="X-Player-Address"),
    authenticated: bool = Depends(verify_service_token),
):
    """
    Get character information including affection level, backstory, and recent conversation
    This is used to populate the character info panel in the chat UI
    """
    if not player_address:
        raise HTTPException(400, "Missing X-Player-Address header")

    logger.info(
        "character_info_requested",
        character_id=character_id,
        player_address=player_address,
    )

    try:
        # Load agent state from database (works for both active and hibernated agents)
        agent_state = await agent_manager.storage.load_agent_state(
            character_id, player_address
        )

        if not agent_state:
            logger.warning(
                "character_info_not_found",
                character_id=character_id,
                player_address=player_address,
            )
            raise HTTPException(
                404, f"Character {character_id} not initialized. Please bond the character first."
            )

        # Log whether agent is active or hibernated
        is_active = character_id in agent_manager.active_agents
        is_hibernated = bool(agent_state.get("hibernate_data"))

        logger.info(
            "character_info_loading",
            character_id=character_id,
            is_active=is_active,
            is_hibernated=is_hibernated,
            has_backstory=bool(agent_state.get("backstory")),
        )

        # Get recent conversation from active agent or hibernate_data
        recent_conversation = []

        # Check if agent is active in memory
        if is_active:
            agent = agent_manager.active_agents[character_id]
            recent_conversation = agent.state.get("messages_today", [])
            logger.info("character_info_from_active_agent", character_id=character_id)
        else:
            # Get from hibernate_data if available
            hibernate_data = agent_state.get("hibernate_data") or {}
            recent_conversation = hibernate_data.get("messages_today", [])
            logger.info(
                "character_info_from_hibernated_data",
                character_id=character_id,
                messages_count=len(recent_conversation)
            )

        logger.info(
            "character_info_retrieved",
            character_id=character_id,
            affection_level=agent_state["affection_level"],
            conversation_messages=len(recent_conversation),
        )

        # Get player info from database
        player_info = agent_state.get("player_info") or {}

        # Check if character image exists
        image_path = IMAGES_DIR / f"{character_id}.png"
        image_url = f"/character-images/{character_id}.png" if image_path.exists() else None

        # Backfill: If image doesn't exist, trigger generation in background
        if not image_path.exists():
            logger.info(
                "image_missing_triggering_backfill",
                character_id=character_id
            )

            async def backfill_image_task():
                try:
                    from .image_generator import get_image_generator
                    image_generator = get_image_generator()
                    character_data = agent_state.get("character_nft")
                    if character_data:
                        await image_generator.generate_character_image(
                            character_id=character_id,
                            character_data=character_data
                        )
                        logger.info("backfill_image_generated", character_id=character_id)
                except Exception as e:
                    logger.error("backfill_image_failed", character_id=character_id, error=str(e))

            # Add to FastAPI background tasks
            background_tasks.add_task(backfill_image_task)

        return CharacterInfoResponse(
            affectionLevel=agent_state["affection_level"],
            backstory=agent_state["backstory"],  # Full backstory for modal display
            recentConversation=recent_conversation,
            totalMessages=agent_state["total_messages"],
            playerName=player_info.get("name", "Player"),
            playerGender=player_info.get("gender", "Male"),
            imageUrl=image_url,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "character_info_retrieval_failed",
            character_id=character_id,
            error=str(e),
        )
        raise HTTPException(500, f"Failed to retrieve character info: {str(e)}")


@app.get("/agent/{character_id}/diary/list", response_model=List[DiaryListItem])
async def get_diary_list(
    character_id: int,
    player_address: str = Header(None, alias="X-Player-Address"),
    authenticated: bool = Depends(verify_service_token),
):
    """
    Get list of all diary entries for this character-player pair
    Returns list of dates with message counts, sorted by date DESC
    """
    if not player_address:
        raise HTTPException(400, "Missing X-Player-Address header")

    logger.info(
        "diary_list_requested",
        character_id=character_id,
        player_address=player_address,
    )

    try:
        diary_list = await agent_manager.storage.get_diary_list(
            character_id, player_address
        )

        logger.info(
            "diary_list_retrieved",
            character_id=character_id,
            count=len(diary_list)
        )

        # Convert to response format
        return [
            DiaryListItem(
                date=item["date"],
                messageCount=item["message_count"]
            )
            for item in diary_list
        ]

    except Exception as e:
        logger.error(
            "diary_list_retrieval_failed",
            character_id=character_id,
            error=str(e),
        )
        raise HTTPException(500, f"Failed to retrieve diary list: {str(e)}")


@app.get("/agent/{character_id}/diary/entry/{date}", response_model=DiaryEntryResponse)
async def get_diary_entry(
    character_id: int,
    date: str,
    player_address: str = Header(None, alias="X-Player-Address"),
    authenticated: bool = Depends(verify_service_token),
):
    """
    Get specific diary entry by date
    Returns diary entry text and metadata
    """
    if not player_address:
        raise HTTPException(400, "Missing X-Player-Address header")

    logger.info(
        "diary_entry_requested",
        character_id=character_id,
        date=date,
        player_address=player_address,
    )

    try:
        diary_entry = await agent_manager.storage.get_diary_entry(
            character_id, player_address, date
        )

        if not diary_entry:
            logger.warning(
                "diary_entry_not_found",
                character_id=character_id,
                date=date
            )
            raise HTTPException(
                404, f"Diary entry not found for date {date}"
            )

        logger.info(
            "diary_entry_retrieved",
            character_id=character_id,
            date=date,
            entry_length=len(diary_entry["entry"])
        )

        return DiaryEntryResponse(
            date=diary_entry["date"],
            entry=diary_entry["entry"],
            messageCount=diary_entry["message_count"]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "diary_entry_retrieval_failed",
            character_id=character_id,
            date=date,
            error=str(e),
        )
        raise HTTPException(500, f"Failed to retrieve diary entry: {str(e)}")


@app.post("/admin/diary/generate")
async def trigger_diary_generation(
    timezone: Optional[int] = None,
    authenticated: bool = Depends(verify_service_token),
):
    """
    Manually trigger diary generation for testing

    Args:
        timezone: Optional timezone offset (-12 to +14). If not provided, uses current hour's timezone.

    Returns:
        Statistics about diary generation (agents processed, success/failure counts)
    """
    from .diary_scheduler import get_diary_scheduler
    from datetime import datetime, timedelta

    logger.info(
        "manual_diary_generation_triggered",
        timezone=timezone,
        note="Manual trigger for testing"
    )

    try:
        scheduler = get_diary_scheduler()
        if not scheduler:
            raise HTTPException(500, "Diary scheduler not initialized")

        # If no timezone specified, calculate which timezone just hit midnight
        if timezone is None:
            timezone = scheduler._calculate_midnight_timezone()
            logger.info(
                "auto_detected_timezone",
                timezone=timezone,
            )

        # Validate timezone
        if timezone < -12 or timezone > 14:
            raise HTTPException(400, f"Invalid timezone: {timezone}. Must be between -12 and +14")

        # Get yesterday's date for this timezone
        utc_now = datetime.utcnow()
        timezone_now = utc_now + timedelta(hours=timezone)
        yesterday = timezone_now - timedelta(days=1)
        date_str = yesterday.strftime("%Y-%m-%d")

        logger.info(
            "manual_diary_generation_started",
            timezone=timezone,
            date=date_str,
        )

        # Find all agents in this timezone
        agents = await scheduler._get_agents_for_timezone(timezone)

        if not agents:
            return {
                "status": "completed",
                "timezone": timezone,
                "date": date_str,
                "total_agents": 0,
                "success_count": 0,
                "failure_count": 0,
                "message": "No agents found in this timezone with recent activity"
            }

        # Generate diaries for all agents
        success_count = 0
        failure_count = 0

        for character_id, player_address in agents:
            success = await scheduler._generate_diary_for_agent(
                character_id, player_address, date_str
            )
            if success:
                success_count += 1
            else:
                failure_count += 1

        logger.info(
            "manual_diary_generation_completed",
            timezone=timezone,
            date=date_str,
            total_agents=len(agents),
            success_count=success_count,
            failure_count=failure_count,
        )

        return {
            "status": "completed",
            "timezone": timezone,
            "date": date_str,
            "total_agents": len(agents),
            "success_count": success_count,
            "failure_count": failure_count,
            "message": f"Generated {success_count} diaries, {failure_count} failures"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "manual_diary_generation_failed",
            timezone=timezone,
            error=str(e),
        )
        raise HTTPException(500, f"Failed to generate diaries: {str(e)}")


@app.get("/agent/{character_id}/wallet", response_model=WalletInfoResponse)
async def get_character_wallet(
    character_id: int,
    player_address: str = Header(None, alias="X-Player-Address"),
    authenticated: bool = Depends(verify_service_token),
):
    """
    Get character's wallet address and LOVE token balance
    """
    if not player_address:
        raise HTTPException(400, "Missing X-Player-Address header")

    logger.info(
        "wallet_info_requested",
        character_id=character_id,
        player_address=player_address,
    )

    try:
        from .wallet_manager import get_wallet_manager

        # Get wallet address from database
        wallet_address = await agent_manager.storage.get_wallet_address(
            character_id, player_address
        )

        if not wallet_address:
            logger.warning(
                "wallet_not_found",
                character_id=character_id,
                note="Character may need to be bonded first"
            )
            raise HTTPException(
                404, f"Wallet not found for character {character_id}. Please bond the character first."
            )

        # Get LOVE token balance
        wallet_mgr = get_wallet_manager()
        balance = await wallet_mgr.get_love_balance(wallet_address)

        logger.info(
            "wallet_info_retrieved",
            character_id=character_id,
            wallet_address=wallet_address,
            balance=balance
        )

        return WalletInfoResponse(
            walletAddress=wallet_address,
            loveBalance=balance
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "wallet_info_retrieval_failed",
            character_id=character_id,
            error=str(e),
        )
        raise HTTPException(500, f"Failed to retrieve wallet info: {str(e)}")


# Gift response templates based on affection level
GIFT_RESPONSE_TEMPLATES = {
    "low": [  # 0-30 affection
        "Thanks for the gift...",
        "Oh, thank you.",
        "I appreciate it.",
    ],
    "medium": [  # 31-70 affection
        "Thank you so much! ❤️",
        "This is really sweet of you!",
        "I love it, thank you!",
        "You're so thoughtful! ❤️",
    ],
    "high": [  # 71+ affection
        "You're so generous! I love it! ❤️❤️",
        "This means the world to me! Thank you! ❤️",
        "I'm so lucky to have you! ❤️❤️",
        "You always know how to make me happy! ❤️",
    ]
}


def select_gift_response(affection_level: int, affection_boost: int) -> str:
    """
    Select appropriate gift response template based on affection level

    Args:
        affection_level: Current affection level (0-1000)
        affection_boost: Affection increase from gift (unused, kept for API compatibility)

    Returns:
        str: Response message
    """
    import random

    if affection_level <= 30:
        tier = "low"
    elif affection_level <= 70:
        tier = "medium"
    else:
        tier = "high"

    template = random.choice(GIFT_RESPONSE_TEMPLATES[tier])
    return template


def calculate_gift_affection(amount_love: float) -> int:
    """
    Calculate affection boost from gift amount.
    In the future, this will factor in character personality.

    Current formula: amount / 20
    Examples:
    - 100 LOVE → +5 affection
    - 200 LOVE → +10 affection
    - 500 LOVE → +25 affection
    - 1000 LOVE → +50 affection
    """
    return int(amount_love / 20)


@app.post("/agent/{character_id}/gift", response_model=GiftResponse)
async def process_gift(
    character_id: int,
    request: GiftRequest,
    player_address: str = Header(None, alias="X-Player-Address"),
    authenticated: bool = Depends(verify_service_token),
):
    """
    Verify LOVE token gift transaction and update affection level
    """
    if not player_address:
        raise HTTPException(400, "Missing X-Player-Address header")

    logger.info(
        "gift_verification_requested",
        character_id=character_id,
        player_address=player_address,
        tx_hash=request.txHash,
        amount=request.amount
    )

    try:
        from .wallet_manager import get_wallet_manager

        # Get character wallet address
        wallet_address = await agent_manager.storage.get_wallet_address(
            character_id, player_address
        )

        if not wallet_address:
            raise HTTPException(
                404, f"Wallet not found for character {character_id}"
            )

        # Verify transaction on-chain
        wallet_mgr = get_wallet_manager()
        tx_data = await wallet_mgr.verify_gift_transaction(
            tx_hash=request.txHash,
            expected_recipient=wallet_address,
            expected_sender=player_address,
            min_amount=request.amount
        )

        if not tx_data:
            logger.warning(
                "gift_verification_failed",
                character_id=character_id,
                tx_hash=request.txHash,
                note="Transaction verification failed"
            )
            return GiftResponse(
                status="failed",
                affectionChange=0,
                newAffectionLevel=0,
                message="Transaction verification failed. Please check the transaction hash and try again."
            )

        # Calculate affection boost based on gift amount
        amount_love = tx_data["amount"] / 10**18  # Convert wei to LOVE tokens
        affection_boost = calculate_gift_affection(amount_love)

        # Load agent state to get current affection
        agent_state = await agent_manager.storage.load_agent_state(
            character_id, player_address
        )

        if not agent_state:
            raise HTTPException(
                404, f"Character {character_id} not initialized"
            )

        current_affection = agent_state["affection_level"]
        new_affection = min(1000, current_affection + affection_boost)  # Cap at 1000

        # Generate character's thank-you response based on affection level
        character_message = select_gift_response(current_affection, affection_boost)

        # Calculate new total_messages count (add 2 for gift exchange)
        new_total_messages = agent_state["total_messages"] + 2

        # Update affection and total_messages in database
        await agent_manager.storage.update_progress(
            character_id=character_id,
            player_address=player_address,
            affection_level=new_affection,
            total_messages=new_total_messages
        )

        # Try to add gift messages to agent's conversation history if agent is active
        try:
            agent = agent_manager.active_agents.get(character_id)
            if agent:
                import time

                # Add player's gift message
                gift_message_player = {
                    "sender": "player",
                    "text": f"🎁 Sent {amount_love:.0f} LOVE",
                    "timestamp": time.time()
                }
                # Add to BOTH lists (for UI display AND diary generation)
                agent.state["messages_today"].append(gift_message_player)
                agent.state["messages_for_compression"].append(gift_message_player)

                # Maintain rolling window for messages_today (max 15)
                if len(agent.state["messages_today"]) > 15:
                    agent.state["messages_today"].pop(0)

                # Increment counters
                agent.state["total_messages"] += 1
                agent.state["messages_today_count"] += 1

                # Add character's response
                gift_message_character = {
                    "sender": "character",
                    "text": character_message,
                    "timestamp": time.time()
                }
                # Add to BOTH lists (for UI display AND diary generation)
                agent.state["messages_today"].append(gift_message_character)
                agent.state["messages_for_compression"].append(gift_message_character)

                # Maintain rolling window for messages_today (max 15)
                if len(agent.state["messages_today"]) > 15:
                    agent.state["messages_today"].pop(0)

                # Increment counters
                agent.state["messages_today_count"] += 1

                # Persist messages_today to database immediately so they show up on page refresh
                hibernate_data = {
                    "messages_today": agent.state["messages_today"],
                    "today_date": agent.state.get("today_date")
                }

                await agent_manager.storage.save_hibernation_state(
                    character_id=character_id,
                    player_address=player_address,
                    hibernate_data=hibernate_data,
                    affection_level=agent.state["affection_level"],
                    total_messages=agent.state["total_messages"]
                )

                logger.info(
                    "gift_messages_added_to_agent",
                    character_id=character_id,
                    messages_today_count=len(agent.state["messages_today"]),
                    messages_for_compression_count=len(agent.state["messages_for_compression"]),
                    total_messages=agent.state["total_messages"],
                    note="Added to both display and compression lists, persisted to DB for page refresh"
                )
            else:
                # Agent is hibernated - add messages directly to hibernate_data
                import time

                hibernate_data = agent_state.get("hibernate_data") or {}
                messages_today = hibernate_data.get("messages_today", [])

                # Add gift messages
                gift_message_player = {
                    "sender": "player",
                    "text": f"🎁 Sent {amount_love:.0f} LOVE",
                    "timestamp": time.time()
                }
                messages_today.append(gift_message_player)

                gift_message_character = {
                    "sender": "character",
                    "text": character_message,
                    "timestamp": time.time()
                }
                messages_today.append(gift_message_character)

                # Maintain rolling window (max 15)
                while len(messages_today) > 15:
                    messages_today.pop(0)

                # Update hibernate_data
                hibernate_data["messages_today"] = messages_today

                # Save to database
                await agent_manager.storage.save_hibernation_state(
                    character_id=character_id,
                    player_address=player_address,
                    hibernate_data=hibernate_data,
                    affection_level=new_affection,
                    total_messages=new_total_messages
                )

                logger.info(
                    "gift_messages_added_to_hibernated_agent",
                    character_id=character_id,
                    messages_today_count=len(messages_today),
                    note="Agent hibernated - added gift messages directly to hibernate_data in DB"
                )
        except Exception as e:
            logger.warning(
                "failed_to_add_gift_to_agent_history",
                character_id=character_id,
                error=str(e),
                note="Gift processed but not added to active agent history"
            )

        logger.info(
            "gift_processed",
            character_id=character_id,
            tx_hash=request.txHash,
            amount_love=amount_love,
            affection_boost=affection_boost,
            new_affection=new_affection,
            character_response=character_message
        )

        return GiftResponse(
            status="success",
            affectionChange=affection_boost,
            newAffectionLevel=new_affection,
            message=f"Gift of {amount_love:.0f} LOVE received! Affection +{affection_boost}",
            characterMessage=character_message
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "gift_processing_failed",
            character_id=character_id,
            error=str(e),
        )
        raise HTTPException(500, f"Failed to process gift: {str(e)}")


async def _generate_character_image_task(character_id: int):
    """Background task to generate character image"""
    try:
        from .image_generator import get_image_generator

        # Fetch character data from blockchain
        character_data = await agent_manager.blockchain.get_character_data(character_id)

        # Generate image (this takes 5-10 seconds)
        image_generator = get_image_generator()
        image_url = await image_generator.generate_character_image(
            character_id=character_id,
            character_data=character_data
        )

        if not image_url:
            logger.error(
                "image_generation_failed",
                character_id=character_id,
                note="Image generator returned None"
            )
        else:
            logger.info(
                "image_generated_successfully",
                character_id=character_id,
                image_url=image_url
            )
    except Exception as e:
        logger.error(
            "image_generation_error",
            character_id=character_id,
            error=str(e),
            error_type=type(e).__name__
        )


@app.post("/character/{character_id}/generate-image", response_model=GenerateImageResponse)
async def generate_character_image(
    character_id: int,
    background_tasks: BackgroundTasks,
    authenticated: bool = Depends(verify_service_token),
):
    """
    Generate AI portrait for a character (called after minting or as backfill)
    Uses DALL-E 3 to create anime-style profile picture based on character traits
    """
    logger.info(
        "image_generation_requested",
        character_id=character_id
    )

    # Check if image already exists
    image_path = IMAGES_DIR / f"{character_id}.png"
    if image_path.exists():
        logger.info(
            "image_already_exists",
            character_id=character_id,
            image_path=str(image_path)
        )
        return GenerateImageResponse(
            status="already_exists",
            imageUrl=f"/character-images/{character_id}.png",
            message="Character image already exists"
        )

    # Add to FastAPI background tasks (proper way to handle async background work)
    background_tasks.add_task(_generate_character_image_task, character_id)

    logger.info(
        "image_generation_started_background",
        character_id=character_id
    )

    return GenerateImageResponse(
        status="success",
        imageUrl=None,
        message="Image generation started in background"
    )


# Startup/Shutdown Events
@app.on_event("startup")
async def startup_event():
    """Initialize agent manager and diary scheduler on startup"""
    logger.info(
        "service_starting",
        llm_provider=settings.LLM_PROVIDER,
        asi_api_url=settings.ASI_MINI_API_URL,
        openai_key_set=bool(settings.OPENAI_API_KEY),
        asi_key_set=bool(settings.ASI_MINI_API_KEY),
    )

    # Initialize agent manager
    await agent_manager.initialize()
    logger.info(
        "agent_manager_started",
        active_agents=len(agent_manager.active_agents),
    )

    # Initialize and start diary scheduler
    scheduler = DiaryScheduler(agent_manager, agent_manager.storage)
    set_diary_scheduler(scheduler)
    await scheduler.start()

    logger.info("service_started")


@app.on_event("shutdown")
async def shutdown_event():
    """Gracefully shutdown agent manager and diary scheduler"""
    logger.info("service_shutting_down")

    # Stop diary scheduler
    from .diary_scheduler import get_diary_scheduler
    scheduler = get_diary_scheduler()
    if scheduler:
        await scheduler.stop()

    # Shutdown agent manager
    await agent_manager.shutdown()
    logger.info("service_stopped")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "agent_service.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info",
    )
