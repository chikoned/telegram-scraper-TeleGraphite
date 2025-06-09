"""Fetcher module for TeleGraphite.

This module handles fetching posts from Telegram channels.
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

from telethon import TelegramClient
from telethon.tl.types import Message, MessageMediaPhoto, MessageMediaDocument

from telegraphite.store import PostStore
from telegraphite.contact_extractor import ContactExtractor

logger = logging.getLogger(__name__)


class ChannelFetcher:
    """Fetches posts from Telegram channels."""

    def __init__(
        self,
        client: TelegramClient,
        store: PostStore,
        channels_file: str = "channels.txt",
        limit: int = 10,
        filters: dict = None,
        schedule: dict = None,
        contact_patterns_file: str = "contact_patterns.txt",
    ):
        """Initialize the channel fetcher."""
        self.client = client
        self.store = store
        self.channels_file = Path(channels_file)
        self.limit = limit
        self.existing_post_ids: Set[int] = set()
        self.contact_extractor = ContactExtractor(contact_patterns_file)

        # Initialize filters
        self.filters = filters or {}
        self.filters.setdefault("keywords", [])
        self.filters.setdefault("media_only", False)
        self.filters.setdefault("text_only", False)

        # Initialize schedule
        self.schedule = schedule or {}
        self.schedule.setdefault("days", [])
        self.schedule.setdefault("times", [])

    def _load_channels(self) -> List[str]:
        if not self.channels_file.exists():
            logger.warning(f"Channels file not found: {self.channels_file}")
            return []

        with open(self.channels_file, "r", encoding="utf-8") as f:
            channels = [line.strip() for line in f if line.strip()]

        logger.info(f"Loaded {len(channels)} channels from {self.channels_file}")
        return channels

    async def _fetch_channel_posts(self, channel: str) -> List[Dict]:
        logger.info(f"Fetching posts from channel: {channel}")
        posts = []

        try:
            self.existing_post_ids = self.store.get_existing_post_ids(channel)

            async for message in self.client.iter_messages(channel, limit=self.limit):
                if not isinstance(message, Message):
                    continue
                if message.id in self.existing_post_ids:
                    logger.debug(f"Skipping already saved post: {message.id}")
                    continue

                post = await self._process_message(channel, message)
                if post:
                    posts.append(post)

        except Exception as e:
            logger.error(f"Error fetching posts from {channel}: {e}")

        return posts

    async def _process_message(self, channel: str, message: Message) -> Optional[Dict]:
        """Process a message and extract relevant information."""
        try:
            date_iso = message.date.strftime("%Y-%m-%dT%H:%M:%SZ")
            text = message.text or message.message or ""

            # Filters
            if self.filters["media_only"] and not message.media:
                logger.debug(f"Skipping post {message.id} (no media)")
                return None

            if self.filters["text_only"] and not text.strip():
                logger.debug(f"Skipping post {message.id} (no text)")
                return None

            if self.filters["keywords"]:
                has_keyword = any(keyword.lower() in text.lower() for keyword in self.filters["keywords"])
                if not has_keyword:
                    logger.debug(f"Skipping post {message.id} (no matching keywords)")
                    return None
            
            # Extract contact information (emails and phone numbers)
            contacts = self.contact_extractor.extract_contacts(text)

            # Save media only if text_only is False
            media_info = []
            if message.media and not self.filters["text_only"]:
                if isinstance(message.media, (MessageMediaPhoto, MessageMediaDocument)):
                    media_info = await self.store.save_media(channel, message)

            post = {
                "channel_name": channel.lstrip("@"),
                "post_id": message.id,
                "timestamp": date_iso,
                "text": text,
                "media": media_info,
                "image_paths": [m.get("path") for m in media_info] if media_info else [],
                "source_channel": channel,
                "post_type": "media" if media_info else "text",
                "fetch_date": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "has_media": bool(media_info),
                "media_count": len(media_info),
                "emails": contacts["emails"],
                "phones": contacts["phones"],
                "links": contacts["links"],
            }

            content_parts = []
            if text:
                content_parts.append(text.strip())
            for media in media_info:
                if media.get("path"):
                    content_parts.append(str(media["path"]).strip())

            if content_parts:
                import hashlib
                content_string = "|".join(content_parts)
                post["content_hash"] = hashlib.md5(content_string.encode("utf-8")).hexdigest()

            return post

        except Exception as e:
            logger.error(f"Error processing message {message.id}: {e}")
            return None

    async def fetch_all_channels(self) -> List[Dict]:
        channels = self._load_channels()
        all_posts = []

        for channel in channels:
            channel_posts = await self._fetch_channel_posts(channel)
            all_posts.extend(channel_posts)
            if channel_posts:
                self.store.save_posts(channel_posts)

        return all_posts

    async def scan_history(
        self,
        channel: str,
        keyword: str,
        max_messages: int = 100,
        delay: float = 1.0,
    ) -> List[Dict]:
        """Scan old messages in a channel for a keyword with rate limiting."""
        posts: List[Dict] = []
        count = 0

        async for message in self.client.iter_messages(
            channel, search=keyword, limit=max_messages
        ):
            post = await self._process_message(channel, message)
            if post:
                posts.append(post)
            count += 1
            if count >= max_messages:
                break
            await asyncio.sleep(delay)

        return posts

    async def fetch_and_save(self) -> bool:
        channels = self._load_channels()
        all_posts = []
        new_post_count = 0
        error_count = 0

        for channel in channels:
            try:
                channel_posts = await self._fetch_channel_posts(channel)
                if channel_posts:
                    new_post_count += len(channel_posts)
                    all_posts.extend(channel_posts)
                    success = self.store.save_posts(channel_posts)
                    if not success:
                        logger.error(f"Failed to save posts for channel {channel}")
                        error_count += 1
                    else:
                        logger.info(f"Successfully saved {len(channel_posts)} new posts from {channel}")
            except Exception as e:
                logger.error(f"Error processing channel {channel}: {e}")
                error_count += 1

        logger.info(f"Fetch and save complete. Added {new_post_count} new posts from {len(channels)} channels")
        if error_count > 0:
            logger.warning(f"Encountered errors with {error_count} channels")

        return error_count == 0

    async def run_periodic(self, interval_seconds: int):
        while True:
            logger.info(f"Starting periodic fetch (interval: {interval_seconds}s)")
            if self._should_run_now():
                try:
                    success = await self.fetch_and_save()
                    if success:
                        logger.info("Periodic fetch completed successfully")
                    else:
                        logger.warning("Periodic fetch completed with some errors")
                except Exception as e:
                    logger.error(f"Error during periodic fetch: {e}")
            else:
                logger.info("Skipping fetch based on schedule configuration")

            logger.info(f"Waiting {interval_seconds} seconds until next run")
            await asyncio.sleep(interval_seconds)

    def _should_run_now(self) -> bool:
        if not self.schedule or (not self.schedule.get("days") and not self.schedule.get("times")):
            return True

        now = datetime.now()

        if self.schedule.get("days"):
            weekday = now.strftime("%A").lower()
            if weekday not in [day.lower() for day in self.schedule["days"]]:
                logger.debug(f"Not running: today ({weekday}) is not in scheduled days {self.schedule['days']}")
                return False

        if self.schedule.get("times"):
            current_time = now.strftime("%H:%M")
            for time_range in self.schedule["times"]:
                if isinstance(time_range, str) and current_time == time_range:
                    return True
                elif isinstance(time_range, dict) and "start" in time_range and "end" in time_range:
                    if time_range["start"] <= current_time <= time_range["end"]:
                        return True

            logger.debug(f"Not running: current time ({current_time}) is not in scheduled times {self.schedule['times']}")
            return False

        return True
