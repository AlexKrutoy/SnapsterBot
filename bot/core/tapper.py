import asyncio
from urllib.parse import unquote

import aiohttp
import json
from aiocfscrape import CloudflareScraper
from aiohttp_proxy import ProxyConnector
from better_proxy import Proxy
from pyrogram import Client
from pyrogram.errors import Unauthorized, UserDeactivated, AuthKeyUnregistered, FloodWait
from pyrogram.raw.functions.messages import RequestWebView
from datetime import datetime, timedelta
from .agents import generate_random_user_agent

from bot.utils import logger
from bot.exceptions import InvalidSession
from .headers import headers


class Tapper:
    def __init__(self, tg_client: Client):
        self.session_name = tg_client.name
        self.tg_client = tg_client
        self.user_id = 0

    async def get_tg_web_data(self, proxy: str | None) -> str:
        if proxy:
            proxy = Proxy.from_str(proxy)
            proxy_dict = dict(
                scheme=proxy.protocol,
                hostname=proxy.host,
                port=proxy.port,
                username=proxy.login,
                password=proxy.password
            )
        else:
            proxy_dict = None

        self.tg_client.proxy = proxy_dict

        try:
            with_tg = True

            if not self.tg_client.is_connected:
                with_tg = False
                try:
                    await self.tg_client.connect()
                except (Unauthorized, UserDeactivated, AuthKeyUnregistered):
                    raise InvalidSession(self.session_name)

            while True:
                try:
                    peer = await self.tg_client.resolve_peer('snapster_bot')
                    break
                except FloodWait as fl:
                    fls = fl.value

                    logger.warning(f"{self.session_name} | FloodWait {fl}")
                    logger.info(f"{self.session_name} | Sleep {fls}s")

                    await asyncio.sleep(fls + 3)

            web_view = await self.tg_client.invoke(RequestWebView(
                peer=peer,
                bot=peer,
                platform='android',
                from_bot_menu=False,
                url='https://snapster-lake.vercel.app/'
            ))

            auth_url = web_view.url
            tg_web_data = unquote(
                string=unquote(
                    string=auth_url.split('tgWebAppData=', maxsplit=1)[1].split('&tgWebAppVersion', maxsplit=1)[0]))

            self.user_id = (await self.tg_client.get_me()).id

            if with_tg is False:
                await self.tg_client.disconnect()

            return tg_web_data

        except InvalidSession as error:
            raise error

        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error during Authorization: {error}")
            await asyncio.sleep(delay=3)

    async def get_stats(self, http_client: aiohttp.ClientSession, headers_send):
        try:
            response = await http_client.get(url='https://45.87.154.135/api/user', headers=headers_send)
            response_text = await response.text()
            response.raise_for_status()
            data = json.loads(response_text)
            points = data['points']
            last_claim = data['dateLastClaimed']
            return (points,
                    last_claim)
        except Exception as error:
            status = response.status if 'response' in locals() else 'No response'
            if status == 503:
                return None, None
            else:
                logger.error(f"{self.session_name} | Error getting stats: {error}")
                return "Not", "Not"

    async def daily_claim(self, http_client: aiohttp.ClientSession, headers_send) -> bool:
        try:
            response = await http_client.post(url="https://45.87.154.135/api/claim-daily", headers=headers_send)
            response.raise_for_status()
            
            return True
        except Exception:
            return False

    async def check_proxy(self, http_client: aiohttp.ClientSession, proxy: Proxy) -> None:
        try:
            response = await http_client.get(url='https://httpbin.org/ip', timeout=aiohttp.ClientTimeout(5))
            ip = (await response.json()).get('origin')
            logger.info(f"{self.session_name} | Proxy IP: {ip}")
        except Exception as error:
            logger.error(f"{self.session_name} | Proxy: {proxy} | Error: {error}")

    async def run(self, proxy: str | None) -> None:
        proxy_conn = ProxyConnector().from_url(proxy) if proxy else None

        async with CloudflareScraper(headers=headers, connector=proxy_conn) as http_client:
            if proxy:
                await self.check_proxy(http_client=http_client, proxy=proxy)

            tg_web_data = await self.get_tg_web_data(proxy=proxy)
            headers['x-telegram-auth'] = tg_web_data
            headers['User-Agent'] = generate_random_user_agent(device_type='android', browser_type='chrome')

            while True:
                try:
                    points, last_claim = await self.get_stats(http_client=http_client, headers_send=headers)
                    if points is None and last_claim is None:
                        logger.info(f"{self.session_name} | Bot is lagging, retrying...")
                        await asyncio.sleep(3)
                        continue
                    elif points == "Not" and last_claim == "Not":
                        logger.error(f"{self.session_name} | Something wrong")
                        continue

                    logger.info(f"{self.session_name} | Your points right now: {points}")
                    current_time = datetime.now()
                    convert = datetime.strptime(last_claim, "%Y-%m-%dT%H:%M:%S.%fZ")
                    convert += timedelta(hours=24)
                    if current_time >= convert:
                        status = await self.daily_claim(http_client=http_client, headers_send=headers)
                        if status is True:
                            logger.success(f"{self.session_name} | Daily claim successful")
                    else:
                        logger.info(f"{self.session_name} | Can`t daily claim, going sleep 1 hour")
                        await asyncio.sleep(delay=3600)

                except InvalidSession as error:
                    raise error

                except Exception as error:
                    logger.error(f"{self.session_name} | Unknown error: {error}")
                    await asyncio.sleep(delay=3)


async def run_tapper(tg_client: Client, proxy: str | None):
    try:
        await Tapper(tg_client=tg_client).run(proxy=proxy)
    except InvalidSession:
        logger.error(f"{tg_client.name} | Invalid Session")
