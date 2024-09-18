import sys
from loguru import logger


logger.remove()
logger.add(sink=sys.stdout, format="<light-white>{time:YYYY-MM-DD HH:mm:ss}</light-white>"
                                   " | <level>{level: <8}</level>"
                                   " | <cyan><b>{line}</b></cyan>"
                                   " - <light-white><b>{message}</b></light-white>")
logger = logger.opt(colors=True)
