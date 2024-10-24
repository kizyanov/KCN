import asyncio
import uvloop
from decouple import config, Csv
from loguru import logger
from kucoin.client import Trade, Market
from decimal import Decimal
from kucoin.client import User, Margin
import aiohttp

from datetime import datetime

key = config("KEY", cast=str)
secret = config("SECRET", cast=str)
passphrase = config("PASSPHRASE", cast=str)
base_keep = Decimal(config("BASE_KEEP", cast=int))

all_currency = config("ALLCURRENCY", cast=Csv(str))  # Tokens for trade in bot
ignore_currency = config("IGNORECURRENCY", cast=Csv(str))  # Tokens for ignore

ledger = {}

base_uri = "https://api.kucoin.com"

trade = Trade(
    key=key,
    secret=secret,
    passphrase=passphrase,
)

margin = Margin(
    key=key,
    secret=secret,
    passphrase=passphrase,
)

user = User(
    key=key,
    secret=secret,
    passphrase=passphrase,
)

market = Market(url="https://api.kucoin.com")

telegram_url = f"https://api.telegram.org/bot{config('TELEGRAM_BOT_API_KEY', cast=str)}/sendMessage"


async def send_telegram_msg(text: str):
    """Отправка сообщения в телеграмм."""
    for chat_id in config("TELEGRAM_BOT_CHAT_ID", cast=Csv(str)):
        async with (
            aiohttp.ClientSession() as session,
            session.post(
                telegram_url,
                json={
                    "chat_id": chat_id,
                    "parse_mode": "HTML",
                    "disable_notification": True,
                    "text": text,
                },
            ),
        ):
            pass


async def get_actual_token_stats():

    accept_tokens = []  # All tokens from exchange
    new_tokens = []  # New tokens, don't find in all_currency

    avail_size = 0.0
    borrow_size = 0.0

    for token in market.get_symbol_list_v2():
        symbol = token["symbol"].replace("-USDT", "")
        if (
            token["isMarginEnabled"]
            and token["quoteCurrency"] == "USDT"
            and symbol not in ignore_currency
        ):
            accept_tokens.append(symbol)
            if symbol not in all_currency:
                new_tokens.append(symbol)

    del_tokens = [used for used in all_currency if used not in accept_tokens]

    for i in margin.get_margin_account_Detail(quoteCurrency="USDT")["accounts"]:
        if i["currency"] == "USDT":
            borrow_size = float(i["liability"])
            avail_size = float(i["available"])

    msg = f"""
<b>KuCoin</b>

<i>KEEP</i>:{base_keep}
<i>USDT</i>:{avail_size:.2f}
<i>BORROWING USDT</i>:{(borrow_size-avail_size):.2f} ({(borrow_size-avail_size)*100/(len(all_currency)*float(base_keep)):.2f}%)
<i>ALL TOKENS</i>:{len(accept_tokens)}
<i>USED TOKENS</i>({len(all_currency)})
<i>DELETED</i>({len(del_tokens)}):{",".join(del_tokens)}
<i>NEW</i>({len(new_tokens)}):{",".join(new_tokens)}
<i>IGNORE</i>({len(ignore_currency)}):{",".join(ignore_currency)}
"""
    logger.warning(msg)
    await send_telegram_msg(msg)


async def main():
    while True:
        await asyncio.sleep(1)
        if datetime.strftime(datetime.now(), "%M:%S") == "10:00":
            await get_actual_token_stats()


if __name__ == "__main__":
    with asyncio.Runner(loop_factory=uvloop.new_event_loop) as runner:
        runner.run(main())
