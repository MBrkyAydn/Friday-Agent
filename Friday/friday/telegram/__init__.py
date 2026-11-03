"""
FRIDAY Telegram Integration Package
Provides two-way Telegram notifications, interactive 4-tier approval prompts,
and remote CLI command execution with strict Chat ID authorization.
"""

from friday.telegram.bridge import TelegramBridge
from friday.telegram.prompter import TelegramPrompter, HybridPrompter

__all__ = ["TelegramBridge", "TelegramPrompter", "HybridPrompter"]
