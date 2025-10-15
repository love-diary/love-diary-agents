"""
Agent Manager - Dynamic Agent Loading & Hibernation
Manages the lifecycle of character agents with lazy loading
"""

import asyncio
import time
from typing import Dict, Optional
import structlog

from .character_agent import CharacterAgent
from .postgres_storage import PostgresStorage
from .blockchain_client import BlockchainClient
from .config import settings

logger = structlog.get_logger()


class AgentManager:
    """
    Manages a pool of active character agents with dynamic loading and hibernation
    """

    def __init__(self):
        self.active_agents: Dict[int, CharacterAgent] = {}
        self.last_activity: Dict[int, float] = {}
        self.storage = PostgresStorage()
        self.blockchain = BlockchainClient()
        self.hibernation_task: Optional[asyncio.Task] = None
        self.is_initialized = False

    async def initialize(self):
        """Initialize agent manager and start background tasks"""
        if self.is_initialized:
            return

        logger.info("agent_manager_initializing")

        # Initialize clients
        await self.storage.initialize()
        await self.blockchain.initialize()

        # Start hibernation background task
        self.hibernation_task = asyncio.create_task(self._hibernation_loop())

        self.is_initialized = True
        logger.info("agent_manager_initialized")

    async def shutdown(self):
        """Gracefully shutdown agent manager"""
        logger.info("agent_manager_shutting_down")

        # Cancel hibernation task
        if self.hibernation_task:
            self.hibernation_task.cancel()
            try:
                await self.hibernation_task
            except asyncio.CancelledError:
                pass

        # Hibernate all active agents
        agent_ids = list(self.active_agents.keys())
        for agent_id in agent_ids:
            await self._hibernate_agent(agent_id)

        logger.info(
            "agent_manager_shutdown_complete",
            hibernated_count=len(agent_ids),
        )

    async def agent_exists(
        self, character_id: int, player_address: str
    ) -> bool:
        """Check if agent has been initialized for this character-player pair"""
        # Check active agents
        if character_id in self.active_agents:
            return True

        # Check database for hibernated state
        return await self.storage.agent_state_exists(character_id, player_address)

    async def get_or_create_agent(
        self, character_id: int, player_address: str
    ) -> CharacterAgent:
        """
        Get agent if active, wake from hibernation, or raise error if not initialized

        Args:
            character_id: Character NFT token ID
            player_address: Player's wallet address

        Returns:
            CharacterAgent instance

        Raises:
            ValueError: If agent not initialized (need to call create_agent_with_backstory)
        """
        # Already active?
        if character_id in self.active_agents:
            self.last_activity[character_id] = time.time()
            agent = self.active_agents[character_id]
            agent.was_active = True
            logger.info("agent_cache_hit", character_id=character_id)
            return agent

        # Wake from hibernation
        logger.info("agent_waking", character_id=character_id)

        # Load state from database
        agent_state = await self.storage.load_agent_state(
            character_id, player_address
        )

        if not agent_state:
            raise ValueError(
                f"Agent {character_id} not initialized. Call /create first."
            )

        # Transform database state to agent state format
        hibernate_data = agent_state.get("hibernate_data") or {}
        transformed_state = {
            "character_id": agent_state["character_id"],
            "player_address": agent_state["player_address"],
            "player_name": agent_state["player_info"].get("name"),
            "player_gender": agent_state["player_info"].get("gender"),
            "messages_today": hibernate_data.get("messages_today", []),
            "today_date": hibernate_data.get("today_date"),
            "backstory": agent_state["backstory"],
            "character_data": agent_state["character_nft"],
            "affection_level": agent_state["affection_level"],
            "total_messages": agent_state["total_messages"],
        }

        # Create agent instance
        agent = CharacterAgent(character_id)
        await agent.restore_state(transformed_state)

        # Clear hibernate_data in database (agent is now active)
        await self.storage.clear_hibernation_data(character_id, player_address)

        # Add to active pool
        self.active_agents[character_id] = agent
        self.last_activity[character_id] = time.time()
        agent.was_active = False  # Flag: was hibernated

        logger.info(
            "agent_woken",
            character_id=character_id,
            hibernated_for_seconds=int(
                time.time() - agent_state.get("hibernated_at", time.time())
            ),
        )

        return agent

    async def create_agent_with_backstory(
        self,
        character_id: int,
        player_address: str,
        player_name: str,
        player_gender: str,
    ) -> Dict:
        """
        Create a new agent from scratch with backstory generation

        Args:
            character_id: Character NFT token ID
            player_address: Player's wallet address
            player_name: Player's name
            player_gender: Player's gender

        Returns:
            Dict with {first_message, backstory, agent_address}
        """
        logger.info("agent_creating", character_id=character_id)

        # Fetch character data from blockchain
        character_data = await self.blockchain.get_character_data(character_id)

        # Create agent
        agent = CharacterAgent(character_id)
        await agent.initialize(
            character_data=character_data,
            player_address=player_address,
            player_name=player_name,
            player_gender=player_gender,
        )

        # Generate backstory (takes 2-5 seconds)
        backstory = await agent.generate_backstory()

        # Prepare player_info dict
        player_info = {
            "name": player_name,
            "gender": player_gender,
            "timezone": 0,  # TODO: Get from frontend
        }

        # Save initial state to database
        await self.storage.save_agent_state(
            character_id=character_id,
            player_address=player_address,
            player_info=player_info,
            character_nft=character_data,
            backstory=backstory,
            affection_level=agent.state["affection_level"],
            total_messages=agent.state["total_messages"],
        )

        # Add to active pool
        self.active_agents[character_id] = agent
        self.last_activity[character_id] = time.time()

        logger.info(
            "agent_created",
            character_id=character_id,
            backstory_length=len(backstory),
        )

        # Generate first greeting message
        first_message = agent.get_greeting()

        return {
            "first_message": first_message,
            "backstory": backstory,
            "agent_address": f"agent://character_{character_id}",
        }

    async def _hibernation_loop(self):
        """Background task to hibernate inactive agents"""
        while True:
            try:
                await asyncio.sleep(settings.AGENT_HIBERNATION_CHECK_INTERVAL)
                await self._hibernate_inactive_agents()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("hibernation_loop_error", error=str(e))

    async def _hibernate_inactive_agents(self):
        """Hibernate agents that have been idle for too long"""
        cutoff_time = time.time() - settings.AGENT_IDLE_TIMEOUT

        to_hibernate = []

        for agent_id, last_time in self.last_activity.items():
            if last_time < cutoff_time:
                to_hibernate.append(agent_id)

        if not to_hibernate:
            return

        logger.info(
            "hibernating_agents",
            count=len(to_hibernate),
            agent_ids=to_hibernate,
        )

        for agent_id in to_hibernate:
            await self._hibernate_agent(agent_id)

        logger.info(
            "hibernation_complete",
            hibernated_count=len(to_hibernate),
            active_agents=len(self.active_agents),
        )

    async def _hibernate_agent(self, character_id: int):
        """Hibernate a single agent"""
        if character_id not in self.active_agents:
            return

        agent = self.active_agents[character_id]

        try:
            # Export state
            state = agent.get_state()

            # Prepare hibernate_data
            hibernate_data = {
                "messages_today": state.get("messages_today", []),
                "today_date": state.get("today_date"),
            }

            # Save hibernation state to database
            await self.storage.save_hibernation_state(
                character_id=character_id,
                player_address=agent.player_address,
                hibernate_data=hibernate_data,
                affection_level=state.get("affection_level", 0),
                total_messages=state.get("total_messages", 0),
            )

            # Remove from memory
            del self.active_agents[character_id]
            del self.last_activity[character_id]
            del agent  # Allow GC

            logger.info("agent_hibernated", character_id=character_id)

        except Exception as e:
            logger.error(
                "agent_hibernation_failed",
                character_id=character_id,
                error=str(e),
            )

    async def get_hibernated_count(self) -> int:
        """Get count of hibernated agents from database"""
        try:
            return await self.storage.get_hibernated_agent_count()
        except Exception:
            return 0

    async def force_hibernate_all(self):
        """Force hibernate all active agents (for maintenance)"""
        agent_ids = list(self.active_agents.keys())

        for agent_id in agent_ids:
            await self._hibernate_agent(agent_id)

        logger.info("force_hibernated_all", count=len(agent_ids))
