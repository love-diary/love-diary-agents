"""
Diary Scheduler - Timezone-aware cron-based diary generation
Runs every hour to generate diaries for agents at their local midnight
"""

from datetime import datetime, timedelta
from typing import List, Tuple
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = structlog.get_logger()


class DiaryScheduler:
    """
    Scheduler for timezone-aware diary generation
    Runs every hour and generates diaries for agents where it's midnight
    """

    def __init__(self, agent_manager, storage):
        self.agent_manager = agent_manager
        self.storage = storage
        self.scheduler = AsyncIOScheduler()
        self.is_running = False

    async def start(self):
        """Start the scheduler"""
        if self.is_running:
            logger.warning("diary_scheduler_already_running")
            return

        logger.info("diary_scheduler_starting")

        # Run every hour at minute 0 (00:00, 01:00, 02:00, ...)
        self.scheduler.add_job(
            self._hourly_diary_generation,
            CronTrigger(minute=0),
            id="diary_generation",
            name="Timezone-aware diary generation",
            replace_existing=True,
        )

        self.scheduler.start()
        self.is_running = True

        logger.info(
            "diary_scheduler_started",
            next_run_time=self.scheduler.get_job("diary_generation").next_run_time,
        )

    async def stop(self):
        """Stop the scheduler"""
        if not self.is_running:
            return

        logger.info("diary_scheduler_stopping")
        self.scheduler.shutdown(wait=True)
        self.is_running = False
        logger.info("diary_scheduler_stopped")

    def _calculate_midnight_timezone(self) -> int:
        """
        Calculate which timezone just hit midnight based on current UTC hour

        Returns:
            Timezone offset (-12 to +14) that just hit midnight

        Examples:
            UTC 00:00 → Timezone +0 (GMT) hit midnight
            UTC 09:00 → Timezone +9 (JST) hit midnight
            UTC 17:00 → Timezone -7 (PDT) hit midnight (UTC 17 = next day 00:00 PDT)
        """
        utc_now = datetime.utcnow()
        current_utc_hour = utc_now.hour

        # The timezone that hit midnight is the one where:
        # UTC hour = timezone offset
        # Examples:
        #   UTC 09:00 = 09:00 + 0 hours for UTC+9 (Japan) = midnight JST
        #   UTC 17:00 = 17:00 - 24 hours = -7 for UTC-7 (PDT) = midnight PDT
        timezone_offset = current_utc_hour
        if timezone_offset > 14:
            # Handle negative timezones (e.g., UTC 17:00 = UTC-7 midnight)
            timezone_offset = timezone_offset - 24

        return timezone_offset

    async def _get_agents_for_timezone(
        self, timezone_offset: int
    ) -> List[Tuple[int, str]]:
        """
        Get all agents in the given timezone that had activity in the last 24 hours

        Args:
            timezone_offset: Timezone offset (-12 to +14)

        Returns:
            List of (character_id, player_address) tuples
        """
        try:
            async with self.storage.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT character_id, player_address
                    FROM agent_states
                    WHERE player_timezone = $1
                    AND updated_at >= NOW() - INTERVAL '24 hours'
                    ORDER BY character_id
                    """,
                    timezone_offset,
                )

                agents = [(row["character_id"], row["player_address"]) for row in rows]

                logger.info(
                    "agents_found_for_timezone",
                    timezone=timezone_offset,
                    agent_count=len(agents),
                )

                return agents

        except Exception as e:
            logger.error(
                "failed_to_query_agents_for_timezone",
                timezone=timezone_offset,
                error=str(e),
            )
            return []

    async def _generate_diary_for_agent(
        self, character_id: int, player_address: str, date_str: str
    ) -> bool:
        """
        Generate diary for a specific agent at their midnight

        Args:
            character_id: Character NFT token ID
            player_address: Player's wallet address
            date_str: Date string in YYYY-MM-DD format (yesterday's date)

        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(
                "diary_generation_started",
                character_id=character_id,
                player_address=player_address,
                date=date_str,
            )

            # Load agent (or wake from hibernation)
            agent = await self.agent_manager.get_or_create_agent(
                character_id, player_address
            )

            # Check if agent already has pending diary data (set by date change detection)
            # If not, set it now from current state
            if not agent.state.get("pending_diary_date"):
                # No pending data yet - set it from current state
                summary = agent.state.get("conversation_summary", "")
                messages = agent.state.get("messages_for_compression", [])
                message_count = agent.state.get("messages_today_count", 0)

                # Check if there's any data to generate diary from
                if not summary and not messages:
                    logger.info(
                        "diary_skipped_no_data",
                        character_id=character_id,
                        date=date_str,
                        note="No conversation_summary or messages_for_compression"
                    )
                    return True

                # Set pending diary state (compressed summary + recent messages + count)
                agent.state["pending_diary_summary"] = summary
                agent.state["pending_diary_messages"] = messages.copy()
                agent.state["pending_diary_date"] = date_str
                agent.state["pending_diary_message_count"] = message_count

                logger.info(
                    "scheduler_set_pending_diary_data",
                    character_id=character_id,
                    date=date_str,
                    summary_length=len(summary),
                    message_count=message_count,
                    note="Scheduler setting pending diary data (not from date change)"
                )
            else:
                logger.info(
                    "scheduler_found_existing_pending_diary",
                    character_id=character_id,
                    existing_date=agent.state.get("pending_diary_date"),
                    date=date_str,
                    note="Pending diary already set by date change detection"
                )

            # Generate diary entry (will use pending_diary_messages and pending_diary_date)
            await agent._save_daily_diary()

            # Reset state for new day
            agent.state["messages_today"] = []
            agent.state["messages_for_compression"] = []
            agent.state["conversation_summary"] = ""
            agent.state["pending_affection_delta"] = 0
            agent.state["messages_today_count"] = 0  # Reset daily message counter

            # Update today_date to new date
            player_timezone = agent.state.get("player_info", {}).get("timezone", 0)
            new_date = agent._get_player_date(player_timezone)
            agent.state["today_date"] = new_date

            # Save progress to database
            await self.storage.update_progress(
                character_id=character_id,
                player_address=player_address,
                affection_level=agent.state["affection_level"],
                total_messages=agent.state["total_messages"],
            )

            # Hibernate agent to save memory
            await self.agent_manager._hibernate_agent(character_id)

            logger.info(
                "diary_generation_completed",
                character_id=character_id,
                date=date_str,
                new_date=new_date,
            )

            return True

        except Exception as e:
            logger.error(
                "diary_generation_failed",
                character_id=character_id,
                player_address=player_address,
                date=date_str,
                error=str(e),
            )
            return False

    async def _hourly_diary_generation(self):
        """
        Hourly job that generates diaries for all agents in the timezone that just hit midnight
        """
        try:
            # Calculate which timezone just hit midnight
            timezone_offset = self._calculate_midnight_timezone()

            # Get yesterday's date for this timezone
            utc_now = datetime.utcnow()
            timezone_now = utc_now + timedelta(hours=timezone_offset)
            yesterday = timezone_now - timedelta(days=1)
            date_str = yesterday.strftime("%Y-%m-%d")

            logger.info(
                "diary_generation_cycle_started",
                timezone=timezone_offset,
                date=date_str,
                utc_time=utc_now.strftime("%Y-%m-%d %H:%M:%S"),
            )

            # Find all agents in this timezone
            agents = await self._get_agents_for_timezone(timezone_offset)

            if not agents:
                logger.info(
                    "diary_generation_cycle_completed_no_agents",
                    timezone=timezone_offset,
                )
                return

            # Generate diaries for all agents
            success_count = 0
            failure_count = 0

            for character_id, player_address in agents:
                success = await self._generate_diary_for_agent(
                    character_id, player_address, date_str
                )
                if success:
                    success_count += 1
                else:
                    failure_count += 1

            logger.info(
                "diary_generation_cycle_completed",
                timezone=timezone_offset,
                date=date_str,
                total_agents=len(agents),
                success_count=success_count,
                failure_count=failure_count,
            )

        except Exception as e:
            logger.error(
                "diary_generation_cycle_failed",
                error=str(e),
            )


# Singleton instance (initialized in main.py)
diary_scheduler: DiaryScheduler | None = None


def get_diary_scheduler() -> DiaryScheduler | None:
    """Get the global diary scheduler instance"""
    return diary_scheduler


def set_diary_scheduler(scheduler: DiaryScheduler):
    """Set the global diary scheduler instance"""
    global diary_scheduler
    diary_scheduler = scheduler
