import html
import logging
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, BOT_LANG
from messages import RU, EN
MSG = EN if BOT_LANG == "en" else RU

logger = logging.getLogger(__name__)


def esc(text) -> str:
    """Экранирует спецсимволы HTML для безопасной вставки в Telegram HTML-сообщения."""
    return html.escape(str(text))


def get_bot() -> Bot:
    return Bot(token=TELEGRAM_TOKEN)


# Комиссии бирж (taker)
EXCHANGE_FEES = {
    "Backpack": "0.04%",
    "Lighter": "0%",
    "Hyperliquid": "0.05%",
    "GRVT": "0.03%",
    "Aster": "0.04%",
}


async def send_pair_signal(opp: dict, size_usd: float = 0) -> None:
    """Отправляет сигнал о найденной паре с кнопками."""
    bot = get_bot()

    exch_a = opp["exchange_a"]
    exch_b = opp["exchange_b"]
    symbol = opp["symbol"]
    dir_a = opp["dir_a"]
    dir_b = opp["dir_b"]

    dir_a_str = MSG["long_arrow"] if dir_a == "LONG" else MSG["short_arrow"]
    dir_b_str = MSG["long_arrow"] if dir_b == "LONG" else MSG["short_arrow"]

    # Сырой APR с биржи (как показывает биржа)
    eff_a = opp['apr_a']
    eff_b = opp['apr_b']

    fee_a = EXCHANGE_FEES.get(exch_a, "?")
    fee_b = EXCHANGE_FEES.get(exch_b, "?")
    net_apr = opp['net_apr']

    # Стрик пары — как давно Net APR положительный (минимум из двух ног)
    streak_a = opp.get("streak_a")
    streak_b = opp.get("streak_b")
    if streak_a is not None and streak_b is not None:
        pair_streak = min(streak_a, streak_b)
    else:
        pair_streak = streak_a or streak_b  # если одна нога ещё без истории

    def _pair_streak_str(hours: float | None) -> str:
        if hours is None:
            return ""
        if hours < 1:
            return " ⏱ <1ч"
        if hours < 24:
            return f" ⏱ {hours:.0f}ч"
        return f" ⏱ {hours / 24:.1f}д"

    text = (
        f"🔀 <b>{esc(symbol)}</b> — {esc(exch_a)} × {esc(exch_b)}\n\n"
        f"{esc(exch_a)} ({dir_a_str}): <code>{eff_a:+.1f}%</code>\n"
        f"{esc(exch_b)} ({dir_b_str}): <code>{eff_b:+.1f}%</code>\n"
        f"{MSG['signal_net_apr']}: ~{net_apr:.1f}% APR{_pair_streak_str(pair_streak)}\n\n"
        f"💸 {esc(exch_a)}: {fee_a} {MSG['signal_fee']} | {esc(exch_b)}: {fee_b}"
    )

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            MSG["btn_open_pair"],
            callback_data=f"open_pair:{exch_a}:{exch_b}:{symbol}:{dir_a}:{dir_b}:{net_apr:.1f}"
        ),
        InlineKeyboardButton(MSG["btn_skip"], callback_data="skip"),
    ]])

    await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
    logger.info(f"Сигнал: {symbol} {exch_a}×{exch_b}, APR={net_apr:.1f}%")


async def send_message(text: str, reply_markup=None) -> None:
    bot = get_bot()
    await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
    )


async def send_message_get_id(text: str, reply_markup=None) -> int | None:
    bot = get_bot()
    msg = await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
    )
    return msg.message_id


async def pin_message(message_id: int) -> None:
    try:
        bot = get_bot()
        await bot.pin_chat_message(
            chat_id=TELEGRAM_CHAT_ID,
            message_id=message_id,
            disable_notification=True,
        )
    except Exception as e:
        logger.warning(f"Не удалось запинить сообщение: {e}")


async def unpin_message(message_id: int) -> None:
    try:
        bot = get_bot()
        await bot.unpin_chat_message(
            chat_id=TELEGRAM_CHAT_ID,
            message_id=message_id,
        )
    except Exception as e:
        logger.warning(f"Не удалось открепить сообщение: {e}")
