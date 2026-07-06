import unittest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
import time
import os
import sys

# Add current directory to path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Mock database.py before importing target modules
mock_db = MagicMock()
mock_collection = AsyncMock()
mock_db.get_collection.return_value = mock_collection
sys.modules['database'] = mock_db

# Import targets
from src.modules.ai.handlers import sanitize_response, wants_image_output
from src.core.config import settings

class TestGeminiHelpers(unittest.TestCase):
    def test_sanitize_response(self):
        # Test cleaning consecutive newlines
        input_text = "Hello\n\n\n\nWorld\n\n"
        expected = "Hello\n\nWorld"
        self.assertEqual(sanitize_response(input_text), expected)

        # Test single newlines are preserved, stripping trailing/leading space
        input_text = "  Hello\nWorld  "
        expected = "Hello\nWorld"
        self.assertEqual(sanitize_response(input_text), expected)

    def test_wants_image_output(self):
        # Case 1: Image generation requests via keywords
        self.assertTrue(wants_image_output("please generate an image of a cat", False))
        self.assertTrue(wants_image_output("create a logo for me", False))
        self.assertTrue(wants_image_output("draw a wallpaper", False))
        self.assertTrue(wants_image_output("edit this photo", True))

        # Case 2: Image input present but no keywords -> routes to image if keyword is present
        self.assertTrue(wants_image_output("make it blue", True))
        self.assertFalse(wants_image_output("what is this?", True))

        # Case 3: Empty prompt
        self.assertTrue(wants_image_output("", True))
        self.assertFalse(wants_image_output("", False))

class TestMirrorUpdateMessage(unittest.IsolatedAsyncioTestCase):
    @patch('src.modules.mirror.handlers.settings')
    async def test_update_message_success(self, mock_settings):
        # Mock settings status interval
        mock_settings.mirror_status_interval = 0
        
        # We need to mock MirrorTask
        from src.modules.mirror.handlers import MirrorTask, CANCEL_CALLBACK_PREFIX
        
        mock_app = MagicMock()
        mock_app.bot = AsyncMock()
        
        task = MirrorTask(
            task_id="abc123xyz456",
            user_id=123,
            chat_id=456,
            status_message_id=789,
            application=mock_app,
            name="test_task",
            phase="downloading",
            progress=50.0,
            downloaded_bytes=500,
            total_bytes=1000,
            speed=50.0,
        )
        
        # Test call
        await task.update_message(force=True)
        
        # Assert edit_message_text was called
        mock_app.bot.edit_message_text.assert_called_once()
        call_args = mock_app.bot.edit_message_text.call_args[1]
        
        self.assertEqual(call_args['chat_id'], 456)
        self.assertEqual(call_args['message_id'], 789)
        self.assertIn("Downloading", call_args['text'])
        self.assertIn("Progress", call_args['text'])
        self.assertIn("abc123xy", call_args['text']) # short_id (first 8 chars of task_id)
        
        # Check reply_markup button text has short_id
        reply_markup = call_args['reply_markup']
        button = reply_markup.inline_keyboard[0][0]
        self.assertIn("abc123xy", button.text)
        self.assertEqual(button.callback_data, f"{CANCEL_CALLBACK_PREFIX}:abc123xyz456")

class TestGroupManagementEnforceLocks(unittest.IsolatedAsyncioTestCase):
    @patch('src.modules.group.handlers.load_group')
    @patch('src.modules.group.handlers.is_user_admin')
    async def test_enforce_locks_triggered(self, mock_is_admin, mock_load_group):
        # Mock load_group to return active locks
        mock_load_group.return_value = {
            "locks": {"audio": True, "photo": False}
        }
        mock_is_admin.return_value = False # User is not admin
        
        from src.modules.group.handlers import enforce_locks
        
        # Mock Update and ContextTypes
        mock_update = MagicMock()
        mock_update.message = MagicMock()
        mock_update.message.from_user.id = 999
        mock_update.effective_chat.id = 111
        mock_update.message.audio = MagicMock() # Trigger audio lock
        mock_update.message.photo = None
        mock_update.message.text = ""
        mock_update.message.caption = ""
        mock_update.message.delete = AsyncMock()
        
        mock_context = MagicMock()
        
        await enforce_locks(mock_update, mock_context)
        
        # Verify message was deleted due to audio lock
        mock_update.message.delete.assert_called_once()

    @patch('src.modules.group.handlers.load_group')
    @patch('src.modules.group.handlers.is_user_admin')
    async def test_enforce_locks_not_triggered(self, mock_is_admin, mock_load_group):
        mock_load_group.return_value = {
            "locks": {"audio": True, "photo": True}
        }
        mock_is_admin.return_value = False
        
        from src.modules.group.handlers import enforce_locks
        
        mock_update = MagicMock()
        mock_update.message = MagicMock()
        mock_update.message.from_user.id = 999
        mock_update.effective_chat.id = 111
        mock_update.message.audio = None
        mock_update.message.photo = None
        mock_update.message.text = "Hello World"
        mock_update.message.caption = ""
        mock_update.message.delete = AsyncMock()
        
        mock_context = MagicMock()
        
        await enforce_locks(mock_update, mock_context)
        
        # Verify message delete was not called
        mock_update.message.delete.assert_not_called()

class TestJsonFallback(unittest.IsolatedAsyncioTestCase):
    @patch('src.core.security.load_json')
    @patch('src.core.security.save_json')
    async def test_comm_checker_fallback(self, mock_save_json, mock_load_json):
        # We trigger database connection failure in _ensure_config
        from src.core.security import CONFIG_COLLECTION, _ensure_config
        
        # Reset caches
        import src.core.security as comm_checker
        comm_checker._command_states_cache = None
        comm_checker._approved_users_cache = None
        
        # Mock find_one to raise Exception (unreachable database)
        CONFIG_COLLECTION.find_one = AsyncMock(side_effect=Exception("DB Down"))
        
        # Mock load_json returns
        mock_load_json.side_effect = lambda path, default: {
            "command_states.json": {"command_states": {"ai": False}},
            "approved_users.json": [9999]
        }.get(path, default)
        
        states, approved = await _ensure_config()
        
        # Assert fallback worked and read from JSON
        self.assertFalse(states["ai"])
        self.assertIn(9999, approved)

    @patch('src.modules.group.handlers.load_json')
    @patch('src.modules.group.handlers.save_json')
    async def test_group_management_fallback(self, mock_save_json, mock_load_json):
        # Reset cache in group_management
        import src.modules.group.handlers as group_management
        group_management._group_cache = {}
        group_management.GROUPS_COLLECTION.find_one = AsyncMock(side_effect=Exception("DB Down"))
        
        # Mock load_json
        mock_load_json.return_value = {"locks": {"audio": True}}
        
        group_data = await group_management.load_group(12345)
        self.assertTrue(group_data["locks"]["audio"])
        mock_load_json.assert_called_with("group_data/12345.json", None)

    @patch('src.modules.notes.handlers.load_json')
    @patch('src.modules.notes.handlers.save_json')
    async def test_notes_fallback(self, mock_save_json, mock_load_json):
        import src.modules.notes.handlers as notes
        notes.NOTES_COLLECTION.find_one = AsyncMock(side_effect=Exception("DB Down"))
        
        # Mock load_json
        mock_load_json.return_value = {"group_notes": {"hello": "world"}, "user_notes": {}}
        
        notes_data = await notes.load_notes(12345)
        self.assertEqual(notes_data["group_notes"]["hello"], "world")
        mock_load_json.assert_called_with("notes/12345.json", {"group_notes": {}, "user_notes": {}})
if __name__ == '__main__':
    unittest.main()
