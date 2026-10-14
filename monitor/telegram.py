"""
Sends messages to Telegram through your bot.

Helper commands (run from the project folder):

    python -m monitor.telegram --get-chat-id   # find your chat ID
    python -m monitor.telegram --test          # send a test message
"""

import argparse
import sys

import requests

from monitor import settings

API_URL = "https://api.telegram.org/bot{token}/{method}"
MAX_MESSAGE_LENGTH = 4000      # Telegram's limit is 4096 characters


class TelegramError(Exception):
    pass


def _call(method, **params):
    """Call one Telegram Bot API method and return its result."""
    if not settings.TELEGRAM_BOT_TOKEN:
        raise TelegramError("TELEGRAM_BOT_TOKEN is missing - add it to your .env file")
    url = API_URL.format(token=settings.TELEGRAM_BOT_TOKEN, method=method)
    try:
        response = requests.post(url, data=params, timeout=20)
        data = response.json()
    except (requests.RequestException, ValueError) as error:
        # Error messages can contain the URL, which contains the token -
        # hide it so it never ends up in logs.
        message = str(error).replace(settings.TELEGRAM_BOT_TOKEN, "<TOKEN>")
        raise TelegramError(f"could not reach Telegram: {message}") from None
    if not data.get("ok"):
        raise TelegramError(f"Telegram refused the request: {data.get('description')}")
    return data["result"]


def split_message(text, limit=MAX_MESSAGE_LENGTH):
    """Cut a long text into pieces under Telegram's limit, at blank lines."""
    pieces, current = [], ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                pieces.append(current)
            current = block[:limit]
    if current:
        pieces.append(current)
    return pieces


def send_message(text):
    """Send a (possibly long) HTML-formatted message to your chat."""
    if not settings.TELEGRAM_CHAT_ID:
        raise TelegramError("TELEGRAM_CHAT_ID is missing - add it to your .env file")
    for piece in split_message(text):
        _call("sendMessage",
              chat_id=settings.TELEGRAM_CHAT_ID,
              text=piece,
              parse_mode="HTML",               # allows <b>bold</b> and <a href> links
              disable_web_page_preview="true")  # no big link previews


def print_chat_ids():
    """Show the chats that recently messaged the bot, with their IDs."""
    updates = _call("getUpdates")
    chats = {}
    for update in updates:
        message = update.get("message") or update.get("channel_post") or {}
        chat = message.get("chat")
        if chat:
            chats[chat["id"]] = chat.get("title") or chat.get("first_name") or chat.get("username")
    if not chats:
        print("No messages found. Open your bot in Telegram, press Start or send it "
              "any message (e.g. 'hi'), then run this command again.")
        return
    print("Chats that messaged your bot:")
    for chat_id, name in chats.items():
        print(f"  {name}:  TELEGRAM_CHAT_ID={chat_id}")
    print("\nCopy the line for your chat into your .env file.")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Telegram helper")
    parser.add_argument("--get-chat-id", action="store_true", help="show your chat ID")
    parser.add_argument("--test", action="store_true", help="send a test message")
    args = parser.parse_args()
    try:
        if args.get_chat_id:
            print_chat_ids()
        elif args.test:
            send_message("✅ <b>Test message</b> from your Africa security monitor.")
            print("Test message sent - check Telegram.")
        else:
            parser.print_help()
    except TelegramError as error:
        print(f"Error: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
