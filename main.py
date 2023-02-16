#!/usr/bin/env python3
import os
import subprocess
import asyncio
from pathlib import Path
import aiofiles
import aiofiles.os
import aiohttp
import json
import time
from datetime import datetime
from typing import Tuple, Optional
from enum import Enum

REL_PATH = Path(__file__).parent.absolute()
DELAY = 5
with open(f"{REL_PATH}/apikey.txt") as keyfile: GOOGLE_API_KEY = keyfile.read().strip()
BROWSER = os.environ['BROWSER']


class FeedType(Enum):
    VrtNws = 0
    Youtube = 1
    Twitch = 2

    def __str__(self) -> str:
        assert len(FeedType) == 3, "Unhandled Feedtype"
        match self:
            case FeedType.VrtNws:
                return "VrtNws"
            case FeedType.Youtube:
                return "Youtube"
            case FeedType.Twitch:
                return "Twitch"
            case _:
                assert False, "unreachable!"

    def get_path(self) -> str:
        assert len(FeedType) == 3, "Unhandled Feedtype"
        match self:
            case FeedType.VrtNws:
                return '/home/p3rtang/.thunderbird/zhwa72u2.default-release/Mail/Feeds-2/feeditems.json'
            case FeedType.Youtube:
                return '/home/p3rtang/.thunderbird/zhwa72u2.default-release/Mail/Feeds/feeditems.json'
            case FeedType.Twitch:
                return '/home/p3rtang/.thunderbird/zhwa72u2.default-release/Mail/Feeds-3/feeditems.json'
            case _:
                assert False, "unreachable!"

    async def send_notification(self, url: str):
        print(f"creating notification...")
        assert len(FeedType) == 3, "Unhandled Feedtype"
        match self:
            case FeedType.VrtNws:
                body: str = await get_title_from_url(url)
                msg = Message(f"{self}", body, '/home/p3rtang/Pictures/logos/vrtnws.jpg') \
                    .set_default_cmd(f"{BROWSER} --new-tab {url}")
            case FeedType.Twitch:
                body = await get_twitch_content(url)
                msg = Message(f"{self}", body)
            case FeedType.Youtube:
                try:
                    video_id = url.split(':')[2]
                    video_data: dict = await youtube_api_get_video_data(video_id)
                    video_info: list = video_data.get('items')
                    video_author: str = video_info[0].get('snippet').get('channelTitle')
                    video_title: str = video_info[0].get('snippet').get('title')
                    channel_id: str = video_info[0].get('snippet').get('channelId')
                    thumbnail_url: str = (await youtube_api_get_channel_data(channel_id)) \
                        .get('items')[0] \
                        .get('snippet') \
                        .get('thumbnails') \
                        .get('medium') \
                        .get('url')
                    thumbnail: str = await get_thumbnail(thumbnail_url, channel_id)

                    url = f"https://www.youtube.com/watch?v={video_id}"
                    msg = Message(video_author, video_title) \
                        .set_default_cmd(f"{BROWSER} --new-tab {url}") \
                        .set_image(thumbnail)
                except IndexError as err:
                    print(err)
                    msg = Message("Youtube", "new_video")
            case _:
                assert False, "unreachable!"
        await asyncio.create_task(msg.send())

    async def read_from_file(self) -> dict:
        async with aiofiles.open(self.get_path(), mode='r') as f:
            contents = await f.read()

        json_parsed: str = json.loads(json.dumps(contents))
        content_dict: dict[str, dict] = json.loads(json_parsed)

        return content_dict


class Feed:
    def __init__(self) -> None:
        self.content: dict[FeedType, dict[str, dict]] = {
            FeedType.VrtNws: dict(),
            FeedType.Youtube: dict(),
            FeedType.Twitch: dict(),
        }
        self.last_check: float = time.time()

    def msg_diff(self, update: Tuple[FeedType, dict]) -> set[str]:
        diff = set(update[1].keys()) - set(self.content[update[0]].keys())
        print(f"new contents: {diff}") if diff else print(f"no new content")
        return diff

    async def build(self) -> None:
        feed_type: FeedType
        print("building feed content history:")
        for feed_type in FeedType:
            print(f"\tbuilding {feed_type}")
            content_dict = await feed_type.read_from_file()
            self.content[feed_type] = content_dict
        print()

    async def check(self) -> None:
        pending = [
            asyncio.create_task(get_messages(FeedType.VrtNws, self)),
            asyncio.create_task(get_messages(FeedType.Youtube, self)),
            asyncio.create_task(get_messages(FeedType.Twitch, self)),
        ]
        while True:
            feed_update, pending_tasks = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            pending = list(pending_tasks)

            feed = feed_update.pop().result()
            if feed is None:
                continue

            diff = self.msg_diff(feed)
            notifications = [asyncio.create_task(feed[0].send_notification(diff_part)) for diff_part in diff]
            pending += notifications

            self.content[feed[0]] = feed[1]
            self.last_check = time.time()
            pending.append(asyncio.create_task(get_messages(feed[0], self)))


async def get_title_from_url(url: str) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            html = await response.text()
            title = html.split("<title>")[1].split("</title>")[0].strip()
            return title


async def get_twitch_content(url: str) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            html = await response.text()
            title = html \
                .split("<span class=\"attribute-name\">content</span>")[1] \
                .split("</a>")[0] \
                .removeprefix("=\"<a class=\"attribute-value\">")
            return title


async def youtube_api_get_video_data(video_id: str) -> dict:
    async with aiohttp.ClientSession() as session:
        api_url = f"https://youtube.googleapis.com/youtube/v3/videos?part=snippet%2CcontentDetails%2Cstatistics&id=" \
                  f"{video_id}&key={GOOGLE_API_KEY}"
        async with session.get(api_url) as response:
            resp_json: dict = await response.json()
            return resp_json


async def youtube_api_get_channel_data(channel_id: str) -> dict:
    async with aiohttp.ClientSession() as session:
        api_url = f"https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&id=" \
                  f"{channel_id}&key={GOOGLE_API_KEY}"
        async with session.get(api_url) as response:
            resp_json: dict = await response.json()
            return resp_json


async def get_thumbnail(url: str, name: str) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if Path(f"{REL_PATH}/thumbnails/{name}.jpg").is_file():
                return f"{REL_PATH}/thumbnails/{name}.jpg"

            file = await aiofiles.open(f"./thumbnails/{name}.jpg", mode="wb")
            await file.write(await response.read())
            await file.close()
            return f"{REL_PATH}/thumbnails/{name}.jpg"


async def get_messages(feed_type: FeedType, feed_cont: Feed) -> Tuple[FeedType, dict[str, dict]]:
    while True:
        await asyncio.sleep(DELAY)
        try:
            stat = await aiofiles.os.stat(feed_type.get_path())
            if stat.st_mtime > feed_cont.last_check:
                break
        except FileNotFoundError:
            pass
    content_dict = await feed_type.read_from_file()
    now = datetime.now().strftime("%H:%M:%S")
    print(f"{now} [{feed_type} file update]:\t", end="")
    return feed_type, content_dict


class Message:
    title = "feed"
    body = ""
    image: Optional[str] = None
    default_command: Optional[str] = None
    secondary_commands: list[str] = []

    def __init__(self, title="", body="", image=None) -> None:
        self.title = title
        self.body = body
        self.image = image

    def set_image(self, path: str):
        self.image = path
        return self

    def set_default_cmd(self, cmd: str):
        self.default_command = cmd
        return self

    async def send(self):
        if self.default_command is not None:
            noti_cmd_str = f'notify-send "{self.title}" "{self.body}" -w -i "{self.image}" --action=default="default"'
            proc = await asyncio.create_subprocess_shell(
                noti_cmd_str,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE)

            stdout, stderr = await proc.communicate()
            command = self.default_command.split(' ')
            # clicked = subprocess.run(noti_cmd, capture_output=True).stdout.decode("utf-8")
            if stdout.decode("utf-8").find("default") != -1:
                subprocess.run(command)
        else:
            subprocess.run(["notify-send", f"{self.title}", f"{self.body}", "-i", f"{self.image}"])


async def main() -> None:
    feed = Feed()
    await feed.build()
    await asyncio.create_task(feed.check())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("KeyboardInterrupt: exiting safely...")
        exit(0)
