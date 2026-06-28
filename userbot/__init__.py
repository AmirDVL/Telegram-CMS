"""Telethon MTProto userbot: reads third-party source channels + downloads media.

Why this exists (plan handover): a standard Bot API bot **cannot** read posts from
channels it is not admin of, and **cannot** forward/copy media from them. So a
userbot logged in as a real Telegram account ingests posts and downloads their
media to a volume; the Bot API bot later re-uploads that media.
"""

__version__ = "0.1.0"
