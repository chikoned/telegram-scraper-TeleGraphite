"""Tests for the fetcher module.

This module contains tests for the ChannelFetcher class.
"""

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from telegraphite.fetcher import ChannelFetcher
from telegraphite.store import PostStore


class TestChannelFetcher(unittest.TestCase):
    """Test cases for the ChannelFetcher class."""

    def setUp(self):
        """Set up test environment before each test."""
        # Create a temporary directory for test data
        self.temp_dir = tempfile.mkdtemp()
        self.store = PostStore(data_dir=self.temp_dir)
        
        # Create a mock client
        self.mock_client = MagicMock()
        
        # Create a temporary channels file
        self.channels_file = Path(self.temp_dir) / "channels.txt"
        with open(self.channels_file, "w", encoding="utf-8") as f:
            f.write("@test_channel1\ntest_channel2")
        
        # Create the fetcher
        self.fetcher = ChannelFetcher(
            client=self.mock_client,
            store=self.store,
            channels_file=str(self.channels_file),
            limit=10,
        )

    def tearDown(self):
        """Clean up after each test."""
        # Remove the temporary directory and its contents
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_load_channels(self):
        """Test loading channels from the channels file."""
        channels = self.fetcher._load_channels()
        self.assertEqual(len(channels), 2)
        self.assertEqual(channels, ["@test_channel1", "test_channel2"])

    def test_load_channels_file_not_found(self):
        """Test loading channels when the file doesn't exist."""
        # Remove the channels file
        os.remove(self.channels_file)
        
        # Try to load channels
        channels = self.fetcher._load_channels()
        self.assertEqual(channels, [])

    @patch("telegraphite.store.PostStore.get_existing_post_ids")
    @patch("telegraphite.fetcher.ChannelFetcher._process_message")
    async def test_fetch_channel_posts(self, mock_process_message, mock_get_existing_post_ids):
        """Test fetching posts from a channel."""
        # Mock the existing post IDs
        mock_get_existing_post_ids.return_value = {1, 2}
        
        # Create mock messages
        mock_message1 = MagicMock(id=1)  # Already exists
        mock_message2 = MagicMock(id=3)  # New message
        mock_message3 = MagicMock(id=4)  # New message
        
        # Set up the client to return the mock messages
        self.mock_client.iter_messages = AsyncMock(return_value=[mock_message1, mock_message2, mock_message3])
        
        # Mock the process_message method to return post data
        mock_process_message.side_effect = [
            None,  # Skip message 1 (already exists)
            {"channel": "test_channel", "post_id": 3, "text": "Post 3"},
            {"channel": "test_channel", "post_id": 4, "text": "Post 4"},
        ]
        
        # Fetch posts
        posts = await self.fetcher._fetch_channel_posts("test_channel")
        
        # Verify results
        self.assertEqual(len(posts), 2)  # Should have 2 new posts
        self.assertEqual(posts[0]["post_id"], 3)
        self.assertEqual(posts[1]["post_id"], 4)
        
        # Verify that existing posts were skipped
        mock_process_message.assert_called_with("test_channel", mock_message3)
        self.assertEqual(mock_process_message.call_count, 2)  # Called for message2 and message3

    @patch("telegraphite.fetcher.ChannelFetcher._fetch_channel_posts")
    async def test_fetch_all_channels(self, mock_fetch_channel_posts):
        """Test fetching posts from all channels."""
        # Mock the fetch_channel_posts method
        mock_fetch_channel_posts.side_effect = [
            [{"channel": "test_channel1", "post_id": 1, "text": "Post 1"}],
            [{"channel": "test_channel2", "post_id": 2, "text": "Post 2"}],
        ]
        
        # Fetch all channels
        posts = await self.fetcher.fetch_all_channels()
        
        # Verify results
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0]["channel"], "test_channel1")
        self.assertEqual(posts[1]["channel"], "test_channel2")
        
        # Verify that fetch_channel_posts was called for each channel
        self.assertEqual(mock_fetch_channel_posts.call_count, 2)
        mock_fetch_channel_posts.assert_any_call("@test_channel1")
        mock_fetch_channel_posts.assert_any_call("test_channel2")

    @patch("telegraphite.store.PostStore.save_posts")
    @patch("telegraphite.fetcher.ChannelFetcher._fetch_channel_posts")
    async def test_fetch_and_save(self, mock_fetch_channel_posts, mock_save_posts):
        """Test fetching and saving posts."""
        # Mock the fetch_channel_posts method
        mock_fetch_channel_posts.side_effect = [
            [{"channel": "test_channel1", "post_id": 1, "text": "Post 1"}],
            [{"channel": "test_channel2", "post_id": 2, "text": "Post 2"}],
        ]
        
        # Mock the save_posts method
        mock_save_posts.return_value = True
        
        # Fetch and save posts
        result = await self.fetcher.fetch_and_save()
        
        # Verify results
        self.assertTrue(result)
        mock_save_posts.assert_called_once()
        self.assertEqual(len(mock_save_posts.call_args[0][0]), 2)  # Called with 2 posts


if __name__ == "__main__":
    unittest.main()