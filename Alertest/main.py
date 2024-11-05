"""Alertest."""

import asyncio
from decimal import Decimal
from time import time

import uvloop
from decouple import Csv, config
from loguru import logger

from models import Access, Telegram, Token
from tools import (
    get_filled_order_list,
    get_margin_account,
    get_seconds_to_next_minutes,
    get_symbol_list,
    send_telegram_msg,
)

DAY_IN_MILLISECONDS = 86400000
WEEK_IN_MILLISECONDS = DAY_IN_MILLISECONDS * 7


def get_now_milliseconds() -> int:
    """Return now milliseconds."""
    return round(time() * 1000)


def get_start_at_for_day() -> int:
    """Return milliseconds for shift a day."""
    return get_now_milliseconds() - DAY_IN_MILLISECONDS


def get_start_at_for_week() -> int:
    """Return milliseconds for shift a week."""
    return get_now_milliseconds() - WEEK_IN_MILLISECONDS


def get_telegram_msg(token: Token) -> str:
    """Prepare telegram msg."""
    return f"""<b>KuCoin</b>

<i>KEEP</i>:{token.base_keep}
<i>USDT</i>:{token.avail_size:.2f}
<i>BORROWING USDT</i>:{token.get_clear_borrow():.2f} ({token.get_percent_borrow():.2f}%)
<i>ALL TOKENS</i>:{token.get_len_accept_tokens()}
<i>USED TOKENS</i>({token.get_len_trade_currency()}):{",".join(token.trade_currency)}
<i>DELETED</i>({token.get_len_del_tokens()}):{",".join(token.del_tokens)}
<i>NEW</i>({token.get_len_new_tokens()}):{",".join(token.new_tokens)}
<i>IGNORE</i>({token.get_len_ignore_currency()}):{",".join(token.ignore_currency)}"""


async def get_available_funds(
    access: Access,
    token: Token,
) -> None:
    """Get available funds in excechge."""
    logger.info("Run get_available_funds")

    margin_account = await get_margin_account(access, {"quoteCurrency": "USDT"})

    for i in [i for i in margin_account["accounts"] if i["currency"] == "USDT"]:
        token.borrow_size = Decimal(i["liability"])
        token.avail_size = Decimal(i["available"])


async def get_tokens(access: Access, token: Token) -> None:
    """Get available tokens."""
    logger.info("Run get_tokens")
    all_token_in_excange = await get_symbol_list(access)

    token.save_accept_tokens(all_token_in_excange)
    token.save_new_tokens(all_token_in_excange)
    token.save_del_tokens()


def unpack(saved_orders: dict, orders: list) -> dict:
    """Unpack orders to used structure."""
    for order in orders:
        clean_symbol = Token.remove_postfix(order["symbol"])

        if clean_symbol not in saved_orders:
            saved_orders[clean_symbol] = []

        saved_orders[clean_symbol].append(
            {
                "time": order["orderCreatedAt"],
                "deal": Decimal(order["dealFunds"]) - Decimal(order["fee"]),
                "side": order["side"],
                "price": Decimal(order["price"]),
            },
        )
    return saved_orders


async def get_orders(access: Access, startat: int) -> dict:
    """."""
    saved_orders = {}
    orders = await get_filled_order_list(
        access,
        {
            "status": "done",
            "type": "limit",
            "tradeType": "MARGIN_TRADE",
            "pageSize": "500",
            "startAt": startat,
        },
    )

    saved_orders.update(unpack(saved_orders, orders["items"]))

    for i in range(2, orders["totalNum"] + 1):
        orders = await get_filled_order_list(
            access,
            {
                "status": "done",
                "type": "limit",
                "tradeType": "MARGIN_TRADE",
                "pageSize": "500",
                "currentPage": i,
                "startAt": startat,
            },
        )
        saved_orders.update(unpack(saved_orders, orders["items"]))

    # sort by time execution
    [saved_orders[symbol].sort(key=lambda x: x["time"]) for symbol in saved_orders]

    return saved_orders


def calc_bot_profit(orders: dict) -> dict:
    """Calc bot profit."""
    result = {}
    for order, value in orders.items():
        profit = Decimal("0")

        for compound in value:
            match compound["side"]:
                case "sell":
                    profit += compound["deal"]
                case "buy":
                    profit -= compound["deal"]

        hodl_profit = (value[0]["price"] / value[-1]["price"] - 1) * 1000

        result.update({order: profit - hodl_profit})
    return result


async def get_actual_token_stats(
    access: Access,
    token: Token,
    telegram: Telegram,
) -> None:
    """Get actual all tokens stats."""
    logger.info("Run get_actual_token_stats")
    await get_available_funds(access, token)
    await get_tokens(access, token)

    msg = get_telegram_msg(token)
    logger.warning(msg)
    await send_telegram_msg(telegram, msg)

    orders = await get_orders(access, get_start_at_for_day())

    for k, v in orders.items():
        logger.info(f"{k}:{v}")

    bot_profit = calc_bot_profit(orders)
    logger.info(bot_profit)


async def main() -> None:
    """Main func in microservice.

    wait second to next time with 10:00 minutes equals
    in infinity loop to run get_actual_token_stats
    """
    logger.info("Run Alertest microservice")

    access = Access(
        key=config("KEY", cast=str),
        secret=config("SECRET", cast=str),
        passphrase=config("PASSPHRASE", cast=str),
        base_uri="https://api.kucoin.com",
    )

    token = Token(
        currency=config("ALLCURRENCY", cast=Csv(str)),
        ignore_currency=config("IGNORECURRENCY", cast=Csv(str)),
        base_keep=Decimal(config("BASE_KEEP", cast=int)),
    )

    telegram = Telegram(
        telegram_bot_key=config("TELEGRAM_BOT_API_KEY", cast=str),
        telegram_bot_chat_id=config("TELEGRAM_BOT_CHAT_ID", cast=Csv(str)),
    )

    await get_actual_token_stats(
        access,
        token,
        telegram,
    )

    while True:
        wait_seconds = get_seconds_to_next_minutes(10)

        logger.info(f"Wait {wait_seconds} to run get_actual_token_stats")
        await asyncio.sleep(wait_seconds)

        await get_actual_token_stats(
            access,
            token,
            telegram,
        )


if __name__ == "__main__":
    with asyncio.Runner(loop_factory=uvloop.new_event_loop) as runner:
        runner.run(main())
