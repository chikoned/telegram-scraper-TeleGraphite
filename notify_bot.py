import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv
from telethon import TelegramClient

from telegraphite.fetcher import ChannelFetcher
from telegraphite.store import PostStore


CHANNELS_FILE = "channels.txt"
KEYWORDS_FILE = "channel_keywords.json"
ENV_FILE = ".env"


def load_credentials(env_file: str) -> tuple[int, str]:
    """Загружает API_ID и API_HASH из файла .env."""
    load_dotenv(env_file)
    api_id = os.getenv("API_ID")
    api_hash = os.getenv("API_HASH")
    if not api_id or not api_hash:
        raise RuntimeError("API_ID и API_HASH должны быть заданы в .env")
    return int(api_id), api_hash


def add_channel(channel: str, channels_file: str = CHANNELS_FILE) -> None:
    """Добавляет канал в файл со списком, если его там ещё нет."""
    channel = channel.strip()
    path = Path(channels_file)
    path.touch()
    with open(path, "r+", encoding="utf-8") as f:
        channels = {line.strip() for line in f if line.strip()}
        if channel in channels:
            print(f"Канал {channel} уже добавлен")
            return
        f.write(channel + "\n")
        print(f"Канал {channel} добавлен")


def add_keyword(channel: str, keyword: str, keywords_file: str = KEYWORDS_FILE) -> None:
    """Добавляет ключевое слово для конкретного канала."""
    path = Path(keywords_file)
    data: Dict[str, List[str]] = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    keywords = set(data.get(channel, []))
    if keyword in keywords:
        print(f"Ключевое слово {keyword} уже есть для {channel}")
        return
    keywords.add(keyword)
    data[channel] = sorted(keywords)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Ключевое слово {keyword} добавлено для {channel}")


async def fetch_and_notify(
    token: str,
    user: str,
    env_file: str = ENV_FILE,
    channels_file: str = CHANNELS_FILE,
    keywords_file: str = KEYWORDS_FILE,
    data_dir: str = "data",
) -> None:
    """Получает новые посты и отправляет их пользователю."""
    api_id, api_hash = load_credentials(env_file)
    client = TelegramClient("bot_session", api_id, api_hash)
    await client.start(bot_token=token)

    store = PostStore(data_dir=data_dir)
    fetcher = ChannelFetcher(
        client=client,
        store=store,
        channels_file=channels_file,
        filters={"keywords": []},
    )

    kw_map: Dict[str, List[str]] = {}
    if os.path.exists(keywords_file):
        with open(keywords_file, "r", encoding="utf-8") as f:
            kw_map = json.load(f)

    posts = await fetcher.fetch_all_channels()
    for post in posts:
        channel = (
            post.get("channel_name")
            or post.get("channel")
            or post.get("source_channel")
        )
        text = post.get("text", "")
        keywords = kw_map.get(channel.lstrip("@"), [])
        if keywords and not any(k.lower() in text.lower() for k in keywords):
            continue
        message = f"Новый пост в {channel}:\n{text}"
        await client.send_message(user, message)

    await client.disconnect()


async def scan_history(
    token: str,
    channel: str,
    keyword: str,
    limit: int = 100,
    delay: float = 1.0,
    env_file: str = ENV_FILE,
    data_dir: str = "data",
) -> None:
    """Сканирует старые сообщения канала по ключевому слову."""
    api_id, api_hash = load_credentials(env_file)
    client = TelegramClient("bot_session", api_id, api_hash)
    await client.start(bot_token=token)

    store = PostStore(data_dir=data_dir)
    fetcher = ChannelFetcher(client=client, store=store)
    posts = await fetcher.scan_history(channel, keyword, max_messages=limit, delay=delay)
    if posts:
        store.save_posts(posts)
    await client.disconnect()
    print(f"Найдено сообщений: {len(posts)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Телеграм-бот уведомлений")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Запустить уведомления")
    run_parser.add_argument("--token", required=True, help="Токен бота")
    run_parser.add_argument("--user", required=True, help="Получатель сообщений")
    run_parser.add_argument("--channels-file", default=CHANNELS_FILE)
    run_parser.add_argument("--keywords-file", default=KEYWORDS_FILE)
    run_parser.add_argument("--env-file", default=ENV_FILE)
    run_parser.add_argument("--data-dir", default="data")

    scan_parser = subparsers.add_parser(
        "scan", help="Просканировать историю канала"
    )
    scan_parser.add_argument("--token", required=True, help="Токен бота")
    scan_parser.add_argument("channel", help="Канал для сканирования")
    scan_parser.add_argument("keyword", help="Ключевое слово")
    scan_parser.add_argument("--limit", type=int, default=100, help="Максимум сообщений")
    scan_parser.add_argument("--delay", type=float, default=1.0, help="Пауза между запросами")
    scan_parser.add_argument("--env-file", default=ENV_FILE)
    scan_parser.add_argument("--data-dir", default="data")

    addc_parser = subparsers.add_parser("add-channel", help="Добавить канал")
    addc_parser.add_argument("channel")

    addk_parser = subparsers.add_parser("add-keyword", help="Добавить ключевое слово")
    addk_parser.add_argument("channel")
    addk_parser.add_argument("keyword")

    args = parser.parse_args()

    if args.command == "add-channel":
        add_channel(args.channel, channels_file=CHANNELS_FILE)
    elif args.command == "add-keyword":
        add_keyword(args.channel, args.keyword, keywords_file=KEYWORDS_FILE)
    elif args.command == "run":
        asyncio.run(
            fetch_and_notify(
                args.token,
                args.user,
                args.env_file,
                args.channels_file,
                args.keywords_file,
                args.data_dir,
            )
        )
    elif args.command == "scan":
        asyncio.run(
            scan_history(
                args.token,
                args.channel,
                args.keyword,
                args.limit,
                args.delay,
                args.env_file,
                args.data_dir,
            )
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

