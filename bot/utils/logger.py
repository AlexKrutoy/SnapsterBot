import sys
from loguru import logger

logger.remove()
logger.add(sink=sys.stdout, format="<white><b>{time:YYYY-MM-DD HH:mm:ss}</b></white> | <level>{level: <8}</level> | <cyan><b>{line}</b></cyan> - <white><b>{message}</b></white>")
logger = logger.opt(colors=True)