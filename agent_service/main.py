"""
Love Diary - Agent Service
FastAPI server for managing character agents
"""

import os
import time
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional
import structlog

from .agent_manager import AgentManager
from .config import settings

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
    player_address: str = Header(None, alias="X-Player-Address"),
    authenticated: bool = Depends(verify_service_token),
):
    """
    Send a message to a character agent
    Agent will be woken from hibernation if needed
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

        # Process message
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


# Startup/Shutdown Events
@app.on_event("startup")
async def startup_event():
    """Initialize agent manager on startup"""
    logger.info("service_starting")
    await agent_manager.initialize()
    logger.info(
        "service_started",
        active_agents=len(agent_manager.active_agents),
    )


@app.on_event("shutdown")
async def shutdown_event():
    """Gracefully shutdown agent manager"""
    logger.info("service_shutting_down")
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
