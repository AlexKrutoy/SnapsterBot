import asyncio
from urllib.parse import unquote, quote
import aiohttp
import json
import html
from aiocfscrape import CloudflareScraper
from aiohttp_proxy import ProxyConnector
from better_proxy import Proxy
from pyrogram import Client
from pyrogram.errors import Unauthorized, UserDeactivated, AuthKeyUnregistered, FloodWait
from pyrogram.raw.functions.messages import RequestWebView
from datetime import datetime
import random
from .agents import generate_random_user_agent
from bot.utils import logger
from bot.exceptions import InvalidSession
from .headers import headers
from bot.config import settings

class Tapper:
    def __init__(self, tg_client: Client):
        self.session_name = tg_client.name
        self.tg_client = tg_client
        self.user_id = 0

    async def get_tg_web_data(self, proxy: str | None) -> str:
        proxy_dict = Proxy.from_str(proxy).as_dict() if proxy else None
        self.tg_client.proxy = proxy_dict
    
        try:
            if not self.tg_client.is_connected:
                await self.tg_client.connect()
                async for message in self.tg_client.get_chat_history('snapster_bot'):
                    if message.text and message.text.startswith('/start'):
                        break
                else:
                    ref_id = settings.REF_ID or 'ref_acs_c-Zl_DyApG'
                    await self.tg_client.send_message("snapster_bot", f"/start {ref_id}")
    
            while True:
                try:
                    peer = await self.tg_client.resolve_peer('snapster_bot')
                    break
                except FloodWait as fl:
                    logger.warning(f"{self.session_name} | FloodWait {fl}")
                    logger.info(f"{self.session_name} | Sleep {fl.value}s")
                    await asyncio.sleep(fl.value + 3)
    
            web_view = await self.tg_client.invoke(RequestWebView(peer=peer, bot=peer, platform='android',from_bot_menu=False, url='https://snapster.psylabs.tech/'))

            auth_url = web_view.url
            tg_web_data = unquote(string=unquote(string=auth_url.split('tgWebAppData=', maxsplit=1)[1].split('&tgWebAppVersion', maxsplit=1)[0]))

            self.user_id = (await self.tg_client.get_me()).id

            if not self.tg_client.is_connected:
                await self.tg_client.disconnect()

            return tg_web_data
    
        except (Unauthorized, UserDeactivated, AuthKeyUnregistered):
            raise InvalidSession(self.session_name)
        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error during Authorization: {html.escape(str(error))}")
            await asyncio.sleep(3)

    async def daily_claim(self, http_client: aiohttp.ClientSession) -> bool:
        url = "https://snapster.psylabs.tech/api/user/claimMiningBonus"
        payload = { "telegramId": f"{self.user_id}" }

        try:
            async with http_client.post(url=url, json=payload) as response:
                if response.status == 200:
                    response_data = await response.json()
                    if response_data.get("result"):
                        points_claimed = response_data["data"]["pointsClaimed"]
                        points_count = response_data["data"]["user"]["pointsCount"]
                        logger.success(f"{self.session_name} | Points claimed: {points_claimed}, Total points: {points_count}")
                        return True
                    else:
                        logger.error(f"{self.session_name} | Daily claim failed: {json.dumps(response_data)}")
                else:
                    logger.error(f"{self.session_name} | Unexpected response: {response.status}, {html.escape(await response.text())}")
        except Exception as error:
            logger.error(f"{self.session_name} | Daily claim error: {html.escape(str(error))}")
        return False

    async def check_proxy(self, http_client: aiohttp.ClientSession, proxy: Proxy) -> None:
        try:
            response = await http_client.get(url='https://httpbin.org/ip', timeout=aiohttp.ClientTimeout(5))
            ip = (await response.json()).get('origin')
            logger.info(f"{self.session_name} | Proxy IP: {ip}")
        except Exception as error:
            escaped_error = str(error).replace('<', '&lt;').replace('>', '&gt;')
            logger.error(f"{self.session_name} | Proxy: {proxy} | Error: {escaped_error}")

    async def run(self, proxy: str | None) -> None:
        proxy_conn = ProxyConnector().from_url(proxy) if proxy else None

        async with CloudflareScraper(headers=headers, connector=proxy_conn) as http_client:
            if proxy:
                await self.check_proxy(http_client=http_client, proxy=proxy)
            tg_web_data = await self.get_tg_web_data(proxy=proxy)
            while True:
                try:
                    if not tg_web_data:
                        continue

                    tg_web_data_parts = tg_web_data.split('&')
                    query_id = tg_web_data_parts[0].split('=')[1]
                    user_data = quote(tg_web_data_parts[1].split('=')[1])
                    auth_date = tg_web_data_parts[2].split('=')[1]
                    hash_value = tg_web_data_parts[3].split('=')[1]

                    init_data = f"query_id={query_id}&user={user_data}&auth_date={auth_date}&hash={hash_value}"
                    http_client.headers['Telegram-Data'] = init_data
                    http_client.headers['User-Agent'] = generate_random_user_agent(device_type='android', browser_type='chrome')

                    status = await self.daily_claim(http_client=http_client)
                    if status:
                        delay = random.randint(3600, 21600)
                        hours = delay // 3600
                        minutes = (delay % 3600) // 60
                        seconds = delay % 60
                        logger.debug(f"{self.session_name} | Sleep {hours}h {minutes}m {seconds}s")
                        await asyncio.sleep(delay)
                    else:
                        await asyncio.sleep(6)

                except InvalidSession as error:
                    raise error

                except Exception as error:
                    logger.error(f"{self.session_name} | Unknown error: {html.escape(str(error))}")
                    await asyncio.sleep(3)

async def run_tapper(tg_client: Client, proxy: str | None):
    try:
        await Tapper(tg_client=tg_client).run(proxy=proxy)
    except InvalidSession:
        logger.error(f"{tg_client.name} | Invalid Session!")