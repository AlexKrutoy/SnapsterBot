import asyncio
import time
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
from bot.config import settings


class Tapper:
    def __init__(self, tg_client: Client):
        self.session_name = tg_client.name
        self.tg_client = tg_client
        self.user_id = 0
        self.first_run = False
        self.session_ug_dict = self.load_user_agents() or []

        headers['User-Agent'] = self.check_user_agent()

    async def generate_random_user_agent(self):
        return generate_random_user_agent(device_type='android', browser_type='chrome')

    def save_user_agent(self):
        user_agents_file_name = "user_agents.json"

        if not any(session['session_name'] == self.session_name for session in self.session_ug_dict):
            user_agent_str = generate_random_user_agent()

            self.session_ug_dict.append({
                'session_name': self.session_name,
                'user_agent': user_agent_str})

            with open(user_agents_file_name, 'w') as user_agents:
                json.dump(self.session_ug_dict, user_agents, indent=4)

            logger.success(f"<light-yellow>{self.session_name}</light-yellow> | User agent saved successfully")

            return user_agent_str

    def load_user_agents(self):
        user_agents_file_name = "user_agents.json"

        try:
            with open(user_agents_file_name, 'r') as user_agents:
                session_data = json.load(user_agents)
                if isinstance(session_data, list):
                    return session_data

        except FileNotFoundError:
            logger.warning("User agents file not found, creating...")

        except json.JSONDecodeError:
            logger.warning("User agents file is empty or corrupted.")

        return []

    def check_user_agent(self):
        load = next(
            (session['user_agent'] for session in self.session_ug_dict if session['session_name'] == self.session_name),
            None)

        if load is None:
            return self.save_user_agent()

        return load

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
            if not self.tg_client.is_connected:
                try:
                    await self.tg_client.connect()
                    start_command_found = False

                    async for message in self.tg_client.get_chat_history('snapster_bot'):
                        if (message.text and message.text.startswith('/start')) or (
                                message.caption and message.caption.startswith('/start')):
                            start_command_found = True
                            break

                    if not start_command_found:
                        ref_id = settings.REF_ID or "ref_wjnV2yHU8MD0sL"
                        await self.tg_client.send_message("snapster_bot", f"/start {ref_id}")
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
                string=auth_url.split('tgWebAppData=', maxsplit=1)[1].split('&tgWebAppVersion', maxsplit=1)[0])

            self.user_id = (await self.tg_client.get_me()).id

            if self.tg_client.is_connected:
                await self.tg_client.disconnect()

            return tg_web_data

        except InvalidSession as error:
            raise error

        except Exception as error:
            escaped_error = str(error).replace('<', '&lt;').replace('>', '&gt;')
            logger.error(f"{self.session_name} | Unknown error during Authorization: {escaped_error}")
            await asyncio.sleep(delay=3)

    async def make_request(self, http_client, method, endpoint=None, url=None, **kwargs):
        full_url = url or f"https://prod.snapster.bot/api/{endpoint or ''}"
        response = await http_client.request(method, full_url, **kwargs)
        return response

    async def get_stats(self, http_client: aiohttp.ClientSession):
        try:
            stats = await self.make_request(http_client, 'GET', f'user/getUserByTelegramId?telegramId={self.user_id}')
            stats = await stats.json(content_type=None)
            data = stats.get('data', {})
            league = data.get('currentLeague', {})
            balance = data.get('pointsCount', {})
            leagueId = league.get('leagueId', {})
            mining_speed = league.get('miningSpeed', {})
            leagueName = league.get('title', {})
            daily = data.get('dailyBonusStreakCount', {})
            logger.info(f"{self.session_name} | Balance - <lc>{balance}</lc>, Daily streak - <lc>{daily}</lc> days")
            logger.info(f"{self.session_name} | Mining speed - <lc>{mining_speed} / min</lc>, League - Name: {leagueName}, "
                        f"ID: {leagueId}")

            return daily

        except Exception as error:
            logger.error(f"{self.session_name} | Get stats error: {error}")
            return False

    async def start_daily_streak(self, http_client: aiohttp.ClientSession):
        try:
            resp_json = await self.make_request(http_client, 'POST', 'dailyQuest/startDailyBonusQuest',
                                                json={'telegramId': str(self.user_id)})
            resp_json = await resp_json.json(content_type=None)
            if resp_json.get('result', {}) is False:
                return False
            return True
        except Exception as error:
            logger.error(f"{self.session_name} | Start daily tasks error: {error}")
            return False

    async def join_daily(self, http_client: aiohttp.ClientSession, days):
        try:
            resp_json = await self.make_request(http_client, 'POST', 'dailyQuest/claimDailyQuestBonus',
                                                json={'telegramId': str(self.user_id), 'dayCount': days+1})
            resp_json = await resp_json.json(content_type=None)
            if resp_json.get('result', {}) is True:
                return True
            return False
        except Exception as error:
            logger.error(f"{self.session_name} | Join daily error: {error}")

    async def claim_mining(self, http_client: aiohttp.ClientSession):
        try:
            resp_json = await self.make_request(http_client, 'POST', 'user/claimMiningBonus',
                                                json={'telegramId': str(self.user_id)})
            resp_json = await resp_json.json()
            points = resp_json.get('data', {}).get('pointsClaimed', 0)
            return points
        except Exception as error:
            logger.error(f"{self.session_name} | Claim mining error: {error}")

    async def get_ref_points(self, http_client: aiohttp.ClientSession):
        try:
            resp_json = await self.make_request(http_client, 'GET', f'referral/calculateReferralPoints'
                                                                    f'?telegramId={self.user_id}')
            resp_json = await resp_json.json(content_type=None)
            return resp_json.get('data', {}).get('pointsToClaim', 0)
        except Exception as error:
            logger.error(f"{self.session_name} | RefPoints error: {error}")

    async def claim_ref_points(self, http_client: aiohttp.ClientSession):
        try:
            resp_json = await self.make_request(http_client, 'POST', 'referral/claimReferralPoints',
                                                json={'telegramId': str(self.user_id)})
            resp_json = await resp_json.json(content_type=None)
            if resp_json.get('result', {}) is True:
                return True
            return False
        except Exception as error:
            logger.error(f"{self.session_name} | Claim ref points error:{error}")

    async def get_quests(self, http_client: aiohttp.ClientSession):
        try:
            resp_json = await self.make_request(http_client, 'GET', f'quest/getQuests'
                                                                    f'?telegramId={self.user_id}')
            resp_json = await resp_json.json(content_type=None)
            quests = []
            data = resp_json.get('data', {})
            if data:
                for quest in data:
                    quests.append(({
                        'id': quest['id'],
                        'title': quest['title'],
                        'points': quest['bonusPoints']
                    }))

                return quests

        except Exception as error:
            logger.error(f"{self.session_name} | Get Quests error: {error}")

    async def start_quest(self, http_client: aiohttp.ClientSession, quest_id):
        try:
            resp_json = await self.make_request(http_client, 'POST', 'quest/startQuest',
                                                json={"telegramId": str(self.user_id),"questId": quest_id})
            resp_json = await resp_json.json(content_type=None)
            if resp_json.get('result', {}) is True:
                return True
            return False

        except ValueError:
            pass

        except Exception as error:
            logger.error(f"{self.session_name} | Start quest error: {error}")

    async def claim_quest(self, http_client: aiohttp.ClientSession, quest_id):
        try:
            resp_json = await self.make_request(http_client, 'POST', 'quest/claimQuestBonus',
                                                json={'telegramId': str(self.user_id),"questId": quest_id})
            resp_json = await resp_json.json(content_type=None)
            if resp_json.get('result', {}) is True:
                return True
            return False

        except ValueError:
            pass

        except Exception as error:
            logger.error(f"{self.session_name} | Claim quest error: {error}")

    async def check_proxy(self, http_client: aiohttp.ClientSession, proxy: Proxy) -> None:
        try:
            response = await http_client.get(url='https://httpbin.org/ip', timeout=aiohttp.ClientTimeout(5))
            ip = (await response.json()).get('origin', {})
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

            http_client.headers['Telegram-Data'] = f"{tg_web_data}"
            http_client.headers['User-Agent'] = generate_random_user_agent(device_type='android',
                                                                           browser_type='chrome')

            while True:
                try:
                    if not tg_web_data:
                        continue
                    else:
                        if not self.first_run:
                            logger.success(
                                f"{self.session_name} | Logged in")
                            self.first_run = True

                    daily_streak = await self.get_stats(http_client=http_client)

                    await asyncio.sleep(2)

                    streak_status = await self.start_daily_streak(http_client=http_client)
                    if streak_status:
                        logger.success(f"{self.session_name} | Daily streak started")
                    else:
                        logger.info(f"{self.session_name} | Can`t start daily streak, already started")

                    if daily_streak:
                        status = await self.join_daily(http_client=http_client, days=daily_streak)
                        if status:
                            logger.success(f"{self.session_name} | Daily joined, got points")

                    await asyncio.sleep(2)

                    if settings.AUTO_MINING:
                        points = await self.claim_mining(http_client=http_client)
                        if points and points > 1:
                            logger.success(f'{self.session_name} | Successfully mined <lc>{points}</lc> points')

                    await asyncio.sleep(2)

                    if settings.CLAIM_REF_POINTS:
                        ref_points = await self.get_ref_points(http_client)
                        if ref_points and ref_points > 0:
                            status = await self.claim_ref_points(http_client=http_client)
                            if status:
                                logger.success(f"{self.session_name} | Points from referrals claimed, got - <lc>{ref_points}</lc>")

                    await asyncio.sleep(2)

                    if settings.AUTO_QUEST:
                        try:
                            quests = await self.get_quests(http_client)
                            for quest in quests:
                                id = quest['id']
                                title = quest['title']
                                points = quest['points']
                                await self.start_quest(http_client=http_client, quest_id=id)
                                await asyncio.sleep(.1)
                                status = await self.claim_quest(http_client=http_client, quest_id=id)
                                if status:
                                    logger.success(f'{self.session_name} | Successfully done quest - <ly>"{title}"</ly>, '
                                                   f'got <lc>{points}</lc> points')
                                await asyncio.sleep(.1)
                        except Exception:
                            pass

                    logger.info(f"{self.session_name} | Going sleep 1h")

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
