import asyncio
from urllib.parse import unquote, quote

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
                    start_command_found = False

                    async for message in self.tg_client.get_chat_history('snapster_bot'):
                        if message.text.startswith('/start'):
                            start_command_found = True
                            break

                    if not start_command_found:
                        if settings.REF_ID == '':
                            await self.tg_client.send_message("snapster_bot", "/start 737844465")
                        else:
                            await self.tg_client.send_message("snapster_bot", f"/start {settings.REF_ID}")
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
            escaped_error = str(error).replace('<', '&lt;').replace('>', '&gt;')
            logger.error(f"{self.session_name} | Unknown error during Authorization: {escaped_error}")
            await asyncio.sleep(delay=3)

    async def get_stats(self, http_client: aiohttp.ClientSession):
        response_text = ""
        try:
            async with http_client.get(url='https://45.87.154.135/api/user') as response:
                response_text = await response.text()
                if response_text:
                    try:
                        data = json.loads(response_text)
                        points = data.get('points')
                        last_claim = data.get('dateLastClaimed')
                        return (points, last_claim)
                    except json.JSONDecodeError as error:
                        escaped_error = str(error).replace('<', '&lt;').replace('>', '&gt;')
                        logger.error(f"{self.session_name} | JSON decode error: {escaped_error}")
                        logger.error(f"{self.session_name} | Response: {response}")
                        logger.error(f"{self.session_name} | headers: {http_client.headers}")
                        logger.error(f"{self.session_name} | Headers response: {response.headers}")
                        logger.error(f"{self.session_name} | Response text: {response_text.encode('unicode_escape')}")
                        return None, None
                else:
                    logger.error(f"{self.session_name} | Empty response received")
                    return None, None
        except Exception as error:
            escaped_error = str(error).replace('<', '&lt;').replace('>', '&gt;')
            logger.error(f"{self.session_name} | Error happened: {escaped_error}")
            logger.error(f"{self.session_name} | Response: {response_text.encode('unicode_escape')}")
            logger.error(f"{self.session_name} | Headers: {response.headers}")
            logger.error(f"{self.session_name} | headers: {http_client.headers}")
            logger.error(f"{self.session_name} | Response: {response}")
            return None, None

    async def daily_claim(self, http_client: aiohttp.ClientSession) -> bool:
        try:
            async with http_client.post(url="https://45.87.154.135/api/claim-daily"):
                return True
        except Exception as error:
            escaped_error = str(error).replace('<', '&lt;').replace('>', '&gt;')
            logger.error(f"{self.session_name} | Daily claim error: {escaped_error}")
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
                    tg_web_data_parts = tg_web_data.split('&')
                    query_id = tg_web_data_parts[0].split('=')[1]
                    user_data = tg_web_data_parts[1].split('=')[1]
                    auth_date = tg_web_data_parts[2].split('=')[1]
                    hash_value = tg_web_data_parts[3].split('=')[1]
                    
                    user_data_encoded = quote(user_data)
                    init_data = f"query_id={query_id}&user={user_data_encoded}&auth_date={auth_date}&hash={hash_value}"
                    http_client.headers['x-telegram-auth'] = f"{init_data}"
                    http_client.headers['User-Agent'] = generate_random_user_agent(device_type='android',
                                                                           browser_type='chrome')

                    if not tg_web_data:
                        continue
                    
                    points, last_claim = await self.get_stats(http_client=http_client)
                    if points is None and last_claim is None:
                        logger.info(f"{self.session_name} | Bot is lagging, retrying...")
                        await asyncio.sleep(3)
                        continue

                    logger.info(f"{self.session_name} | Your points right now: {points}")

                    await asyncio.sleep(2)

                    current_time = datetime.now()
                    convert = datetime.strptime(last_claim, "%Y-%m-%dT%H:%M:%S.%fZ")
                    convert += timedelta(hours=27)
                    if current_time >= convert:
                        status = await self.daily_claim(http_client=http_client)
                        if status is True:
                            logger.success(f"{self.session_name} | Daily claim successful")
                    else:
                        logger.info(f"{self.session_name} | Can`t daily claim, going sleep 1 hour")
                        await asyncio.sleep(delay=3600)
                    await asyncio.sleep(5)

                except InvalidSession as error:
                    raise error

                except Exception as error:
                    escaped_error = str(error).replace('<', '&lt;').replace('>', '&gt;')
                    logger.error(f"{self.session_name} | Unknown error: {escaped_error}")
                    await asyncio.sleep(delay=3)


async def run_tapper(tg_client: Client, proxy: str | None):
    try:
        await Tapper(tg_client=tg_client).run(proxy=proxy)
    except InvalidSession:
        logger.error(f"{tg_client.name} | Invalid Session")
