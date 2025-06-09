"""Tests for the store module.

This module contains tests for the PostStore class, focusing on deduplication logic.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from telegraphite.store import PostStore


class TestPostStore(unittest.TestCase):
    """Test cases for the PostStore class."""

    def setUp(self):
        """Set up test environment before each test."""
        # Create a temporary directory for test data
        self.temp_dir = tempfile.mkdtemp()
        self.store = PostStore(data_dir=self.temp_dir)
        self.test_channel = "test_channel"
        
        # Create test channel directory
        self.channel_dir = Path(self.temp_dir) / self.test_channel
        self.channel_dir.mkdir(exist_ok=True)
        
        # Sample posts for testing
        self.sample_posts = [
            {"channel": self.test_channel, "post_id": 1, "text": "Post 1"},
            {"channel": self.test_channel, "post_id": 2, "text": "Post 2"},
            {"channel": self.test_channel, "post_id": 3, "text": "Post 3"},
        ]

    def tearDown(self):
        """Clean up after each test."""
        # Remove the temporary directory and its contents
        shutil.rmtree(self.temp_dir)

    def test_get_channel_dir(self):
        """Test getting the channel directory."""
        # Test with @ prefix
        channel_dir = self.store.get_channel_dir(f"@{self.test_channel}")
        self.assertEqual(channel_dir, Path(self.temp_dir) / self.test_channel)
        
        # Test without @ prefix
        channel_dir = self.store.get_channel_dir(self.test_channel)
        self.assertEqual(channel_dir, Path(self.temp_dir) / self.test_channel)

    def test_get_existing_post_ids_empty(self):
        """Test getting existing post IDs when no posts exist."""
        post_ids = self.store.get_existing_post_ids(self.test_channel)
        self.assertEqual(post_ids, set())

    def test_get_existing_post_ids(self):
        """Test getting existing post IDs from saved posts."""
        # Save sample posts
        posts_file = self.channel_dir / "posts.json"
        with open(posts_file, "w", encoding="utf-8") as f:
            json.dump(self.sample_posts, f)
        
        # Get existing post IDs
        post_ids = self.store.get_existing_post_ids(self.test_channel)
        self.assertEqual(post_ids, {1, 2, 3})

    def test_save_posts_new(self):
        """Test saving new posts."""
        # Save posts
        result = self.store.save_posts(self.sample_posts)
        self.assertTrue(result)
        
        # Check if posts were saved correctly
        posts_file = self.channel_dir / "posts.json"
        self.assertTrue(posts_file.exists())
        
        with open(posts_file, "r", encoding="utf-8") as f:
            saved_posts = json.load(f)
        
        self.assertEqual(len(saved_posts), 3)
        self.assertEqual(saved_posts, self.sample_posts)

    def test_save_posts_with_duplicates(self):
        """Test saving posts with duplicates."""
        # Save initial posts
        self.store.save_posts(self.sample_posts)
        
        # Create new posts with some duplicates
        new_posts = [
            {"channel": self.test_channel, "post_id": 3, "text": "Post 3"}, # Duplicate
            {"channel": self.test_channel, "post_id": 4, "text": "Post 4"}, # New
            {"channel": self.test_channel, "post_id": 5, "text": "Post 5"}, # New
        ]
        
        # Save new posts
        result = self.store.save_posts(new_posts)
        self.assertTrue(result)
        
        # Check if posts were merged correctly
        posts_file = self.channel_dir / "posts.json"
        with open(posts_file, "r", encoding="utf-8") as f:
            saved_posts = json.load(f)
        
        # Should have 5 unique posts (1, 2, 3, 4, 5)
        self.assertEqual(len(saved_posts), 5)
        post_ids = {post["post_id"] for post in saved_posts}
        self.assertEqual(post_ids, {1, 2, 3, 4, 5})

    @patch("telegraphite.store.logger")
    def test_error_handling(self, mock_logger):
        """Test error handling when saving posts."""
        # Create an invalid posts file (not valid JSON)
        posts_file = self.channel_dir / "posts.json"
        with open(posts_file, "w", encoding="utf-8") as f:
            f.write("invalid json")
        
        # Try to get existing post IDs
        post_ids = self.store.get_existing_post_ids(self.test_channel)
        self.assertEqual(post_ids, set())
        
        # Verify that the error was logged
        mock_logger.error.assert_called_once()


if __name__ == "__main__":
    unittest.main()