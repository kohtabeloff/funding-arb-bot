"""
Funding Arbitrage Bot — дельта-нейтральный арбитраж фандинга.
Универсальный: работает с любыми комбинациями бирж.
"""
import asyncio
import json
import logging
import time

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.constants import ParseMode

from config import (
    SCAN_INTERVAL_SECONDS, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, POSITION_SIZE_USD,
    AUTHOR_CHANNEL, AUTHOR_CHANNEL_NAME, DONATION_WALLET_EVM, DONATION_WALLET_SOL,
    EXCHANGES, LIQ_WARN_PCT, LIQ_AUTO_CLOSE_PCT, PRICE_WARN_PCT, PRICE_AUTO_CLOSE_PCT,
    NEG_APR_HARD_CLOSE, NEG_APR_WAIT_HOURS, BOT_LANG,
)
from messages import RU, EN
MSG = EN if BOT_LANG == "en" else RU
from scanners.hyperliquid import HyperliquidScanner
from scanners.backpack import BackpackScanner
from scanners.lighter import LighterScanner
from scanners.grvt import GRVTScanner
from scanners.aster import AsterScanner
from core.analyzer import find_pair_opportunities, calc_net_apr_for_pair
from core.executor import open_pair, close_pair, scale_in_pair, get_executor
from bot.telegram import send_pair_signal, send_message, send_message_get_id
from db.database import (
    init_db, save_funding_snapshot,
    get_open_pairs, get_positions_by_pair, get_closed_pairs, count_closed_pairs,
    get_position_by_id, mark_position_closed,
    save_setting, load_setting, get_avg_rate_since, get_avg_rate_between,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# Токен Telegram утекает в логи через httpx (URL содержит bot<TOKEN>)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ─── Антиспам ───────────────────────────────────────────────────────────────────
_sent_signals: dict[str, tuple[float, float]] = {}
SIGNAL_COOLDOWN_HOURS = 4
APR_GROWTH_THRESHOLD = 0.5

_verify_alerts_sent: dict[str, float] = {}
VERIFY_ALERT_COOLDOWN_SECONDS = 300

_liq_alerts_sent: dict[str, float] = {}
LIQ_ALERT_COOLDOWN_SECONDS = 1800

_negative_funding_since: dict[str, float] = {}

# ─── Настройки (загружаются из БД при старте) ─────────────────────────────────
# Размеры позиций: "global" (один размер для всех) или "per_exchange" (раздельный)
_position_size_mode: str = "global"  # "global" | "per_exchange"
_global_position_size: float = POSITION_SIZE_USD
_exchange_sizes: dict[str, float] = {}  # {"Backpack": 100, "Lighter": 200, ...}

# Настройки защиты (можно менять в боте)
_protection_enabled: bool = True
_price_close_pct: float = PRICE_AUTO_CLOSE_PCT   # % падения цены → закрыть
_neg_apr_hours: float = NEG_APR_WAIT_HOURS        # часов в минусе → закрыть

# История Net APR пар — сколько часов держится положительный результат
# {"ExchA:ExchB:SYMBOL": {"positive_since": float|None, "dip_since": float|None}}
_funding_streak: dict[str, dict] = {}
FUNDING_DIP_TOLERANCE_HOURS = 4.0  # дипы короче этого игнорируются

# Какие биржи включены для сигналов
_enabled_exchanges: set[str] = set(EXCHANGES.values())  # все по умолчанию

# Защита от двойного нажатия
_opening_pairs: set = set()

# Глобальные блокировки от параллельных операций
_scan_lock = asyncio.Lock()          # сканирование (авто + ручное)
_trade_lock = asyncio.Lock()         # open/close/scale_in

# Ожидаем ввод
_waiting_for_size: str | None = None       # None или "global" / exchange_name
_waiting_for_scale_in: tuple | None = None
_waiting_for_price_pct: bool = False       # ожидаем ввод % падения цены вручную
_waiting_for_neg_hours: bool = False       # ожидаем ввод часов вручную

# ─── Кнопки ──────────────────────────────────────────────────────────────────
BTN_POSITIONS = MSG["btn_positions"]
BTN_SCAN = MSG["btn_scan"]
BTN_HISTORY = MSG["btn_history"]
BTN_SETTINGS = MSG["btn_settings"]
BTN_BALANCES = MSG["btn_balances"]
BTN_SUPPORT = MSG["btn_support"]

# ─── Сканеры ─────────────────────────────────────────────────────────────────
ALL_SCANNERS = [
    BackpackScanner(),
    LighterScanner(),
    HyperliquidScanner(),
    GRVTScanner(),
    AsterScanner(),
]


def persistent_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_POSITIONS), KeyboardButton(BTN_SCAN)],
            [KeyboardButton(BTN_BALANCES), KeyboardButton(BTN_HISTORY)],
            [KeyboardButton(BTN_SETTINGS), KeyboardButton(BTN_SUPPORT)],
        ],
        resize_keyboard=True,
    )


def get_position_size(exchange_name: str) -> float:
    """Возвращает размер позиции для биржи с учётом режима."""
    if _position_size_mode == "per_exchange":
        return _exchange_sizes.get(exchange_name, _global_position_size)
    return _global_position_size


# ─── Загрузка/сохранение настроек ────────────────────────────────────────────

async def _load_settings():
    """Загружает настройки из БД при старте."""
    global _position_size_mode, _global_position_size, _exchange_sizes, _enabled_exchanges
    global _protection_enabled, _price_close_pct, _neg_apr_hours

    mode = await load_setting("position_size_mode", "global")
    _position_size_mode = mode

    size = await load_setting("global_position_size", str(POSITION_SIZE_USD))
    _global_position_size = float(size)

    sizes_json = await load_setting("exchange_sizes", "{}")
    try:
        _exchange_sizes = json.loads(sizes_json)
    except json.JSONDecodeError:
        _exchange_sizes = {}

    enabled = await load_setting("enabled_exchanges", "")
    if enabled:
        _enabled_exchanges = set(enabled.split(","))
    else:
        _enabled_exchanges = set(EXCHANGES.values())

    _protection_enabled = (await load_setting("protection_enabled", "1")) == "1"
    _price_close_pct = float(await load_setting("price_close_pct", str(PRICE_AUTO_CLOSE_PCT)))
    _neg_apr_hours = float(await load_setting("neg_apr_hours", str(NEG_APR_WAIT_HOURS)))


async def _save_settings():
    """Сохраняет текущие настройки в БД."""
    await save_setting("position_size_mode", _position_size_mode)
    await save_setting("global_position_size", str(_global_position_size))
    await save_setting("exchange_sizes", json.dumps(_exchange_sizes))
    await save_setting("enabled_exchanges", ",".join(_enabled_exchanges))
    await save_setting("protection_enabled", "1" if _protection_enabled else "0")
    await save_setting("price_close_pct", str(_price_close_pct))
    await save_setting("neg_apr_hours", str(_neg_apr_hours))


# ─── История Net APR пар ─────────────────────────────────────────────────────
# Отслеживаем сколько часов держится положительный Net APR для каждой пары.
# Дипы короче FUNDING_DIP_TOLERANCE_HOURS игнорируются.

def _pair_key(exch_a: str, exch_b: str, symbol: str) -> str:
    a, b = sorted([exch_a, exch_b])
    return f"{a}:{b}:{symbol}"


def _update_pair_net_streaks(opps: list):
    """Обновляет стрики на основе текущего списка выгодных пар.
    Пары, которые исчезли из скана — считаются ушедшими в 0 или минус."""
    now = time.time()
    current_keys = set()

    for opp in opps:
        key = _pair_key(opp["exchange_a"], opp["exchange_b"], opp["symbol"])
        current_keys.add(key)

        if key not in _funding_streak:
            _funding_streak[key] = {"positive_since": now, "dip_since": None}
        else:
            streak = _funding_streak[key]
            if streak["dip_since"] is not None:
                # Пара вернулась в плюс после дипа
                dip_hours = (now - streak["dip_since"]) / 3600
                if dip_hours <= FUNDING_DIP_TOLERANCE_HOURS:
                    streak["dip_since"] = None  # дип короткий — игнорируем, стрик продолжается
                else:
                    streak["positive_since"] = now  # дип затянулся — новый стрик
                    streak["dip_since"] = None

    # Пары, которых нет в текущем скане → net APR упал до 0 или в минус
    for key, streak in _funding_streak.items():
        if key in current_keys:
            continue
        if streak.get("positive_since") is None:
            continue
        if streak["dip_since"] is None:
            streak["dip_since"] = now  # начало дипа
        else:
            dip_hours = (now - streak["dip_since"]) / 3600
            if dip_hours > FUNDING_DIP_TOLERANCE_HOURS:
                streak["positive_since"] = None  # стрик сброшен


def get_pair_streak_hours(exch_a: str, exch_b: str, symbol: str) -> float | None:
    """Сколько часов Net APR пары держится положительным. None если данных нет."""
    key = _pair_key(exch_a, exch_b, symbol)
    streak = _funding_streak.get(key)
    if not streak or streak.get("positive_since") is None:
        return None
    return (time.time() - streak["positive_since"]) / 3600


# ─── Сканирование ────────────────────────────────────────────────────────────

async def fetch_all_rates() -> dict:
    """Запускает все сканеры параллельно."""
    results = await asyncio.gather(
        *[s.get_funding_rates() for s in ALL_SCANNERS],
        return_exceptions=True,
    )
    exchange_rates = {}
    for scanner, result in zip(ALL_SCANNERS, results):
        name = scanner.__class__.__name__.replace("Scanner", "")
        if isinstance(result, Exception):
            logger.error(f"Сканер {name}: {result}")
        elif result:
            exchange_rates[result[0].exchange] = result
    return exchange_rates


def should_send_signal(key: str, current_apr: float) -> bool:
    if key not in _sent_signals:
        return True
    prev_apr, prev_time = _sent_signals[key]
    hours_passed = (time.time() - prev_time) / 3600
    if hours_passed >= SIGNAL_COOLDOWN_HOURS:
        return True
    if current_apr > 0 and prev_apr > 0 and current_apr > prev_apr * (1 + APR_GROWTH_THRESHOLD):
        return True
    return False


# ─── Верификация позиций ─────────────────────────────────────────────────────

async def _verify_positions(exchange_rates: dict):
    """Сверяет позиции в БД с реальными на биржах."""
    pairs = await get_open_pairs()
    if not pairs:
        return

    # Собираем реальные позиции с каждой биржи
    real_positions: dict[str, dict] = {}  # {exchange: {symbol: quantity}}

    for pair in pairs:
        for leg in pair["legs"]:
            exch = leg["exchange"]
            if exch in real_positions:
                continue
            try:
                executor = get_executor(exch)
                positions = await executor.get_positions()
                await executor.close()
                if positions is not None:
                    real_positions[exch] = {p["symbol"]: p["quantity"] for p in positions}
                else:
                    logger.warning(f"Верификация: {exch} вернул None — пропускаем")
            except Exception as e:
                logger.warning(f"Верификация: {exch} недоступен: {e}")

    alerts = []
    for pair in pairs:
        for leg in pair["legs"]:
            exch = leg["exchange"]
            symbol = leg["symbol"]
            if exch not in real_positions:
                continue

            real_qty = real_positions[exch].get(symbol, 0)
            expected_long = (leg["direction"] == "LONG")

            if real_qty == 0:
                alerts.append(MSG["mismatch_disappeared"].format(symbol=symbol, exchange=exch, direction=leg["direction"]))
            elif (real_qty > 0) != expected_long:
                real_dir = "LONG" if real_qty > 0 else "SHORT"
                alerts.append(MSG["mismatch_direction"].format(symbol=symbol, exchange=exch, db_dir=leg["direction"], real_dir=real_dir))

    if not alerts:
        return

    alert_key = "|".join(sorted(alerts))
    last_sent = _verify_alerts_sent.get(alert_key, 0)
    if time.time() - last_sent < VERIFY_ALERT_COOLDOWN_SECONDS:
        return

    _verify_alerts_sent[alert_key] = time.time()
    await send_message(
        MSG["position_mismatch"].format(alerts="\n".join(f"⚠️ {a}" for a in alerts))
    )


# ─── Мониторинг открытых пар ─────────────────────────────────────────────────

async def _monitor_open_pairs(exchange_rates: dict):
    """Универсальный мониторинг всех открытых пар: фандинг + ликвидация."""
    pairs = await get_open_pairs()
    if not pairs:
        return

    # Строим карту ставок
    rates_map = {}
    for exch_name, rates in exchange_rates.items():
        for r in rates:
            rates_map[f"{r.exchange}:{r.symbol}"] = r

    for pair in pairs:
        legs = pair["legs"]
        if len(legs) < 2:
            continue

        pair_id = pair["pair_id"]
        symbol = legs[0]["symbol"]

        # Считаем нетто APR
        net_apr = calc_net_apr_for_pair(legs, rates_map)

        # Вспомогательная: APR одной ноги для уведомлений
        def _leg_apr_str(l):
            key = l['exchange'] + ':' + symbol
            dummy = type('', (), {'apr': 0})()
            return f"{l['exchange']} <code>{rates_map.get(key, dummy).apr:+.1f}%</code>"

        # ── Проверка APR ─────────────────────────────────────────────────────
        if not _protection_enabled:
            continue

        if net_apr < NEG_APR_HARD_CLOSE:
            logger.warning(f"Автозакрытие {symbol}: нетто APR={net_apr:.1f}%")
            _negative_funding_since.pop(pair_id, None)
            apr_details = " | ".join(_leg_apr_str(l) for l in legs)
            await _auto_close_pair(
                pair_id, symbol, legs,
                reason=MSG["auto_close_reason_neg_apr"].format(apr=net_apr, threshold=NEG_APR_HARD_CLOSE, details=apr_details),
            )
            continue

        elif net_apr < 0:
            if pair_id not in _negative_funding_since:
                _negative_funding_since[pair_id] = time.time()
                alert_key = f"alert:{pair_id}:negative"
                if should_send_signal(alert_key, net_apr):
                    _sent_signals[alert_key] = (net_apr, time.time())
                    keyboard = InlineKeyboardMarkup([[
                        InlineKeyboardButton("❌ Закрыть пару", callback_data=f"close_pair:{pair_id}:{symbol}"),
                    ]])
                    apr_details = " | ".join(_leg_apr_str(l) for l in legs)
                    await send_message(
                        MSG["negative_funding_alert"].format(
                            symbol=symbol, apr_details=apr_details,
                            net_apr=net_apr, wait_hours=int(_neg_apr_hours),
                        ),
                        reply_markup=keyboard,
                    )
            else:
                hours_waited = (time.time() - _negative_funding_since[pair_id]) / 3600
                if hours_waited >= _neg_apr_hours:
                    logger.warning(f"Автозакрытие {symbol}: фандинг в минусе {hours_waited:.1f}ч")
                    _negative_funding_since.pop(pair_id, None)
                    await _auto_close_pair(
                        pair_id, symbol, legs,
                        reason=MSG["auto_close_reason_neg_wait"].format(apr=net_apr, hours=hours_waited),
                    )
                    continue
        else:
            _negative_funding_since.pop(pair_id, None)

        # ── Проверка ликвидации и отклонения цены ────────────────────────────
        for leg in legs:
            exch_name = leg["exchange"]
            try:
                executor = get_executor(exch_name)

                # Ликвидационная цена (если биржа поддерживает)
                liq_info = await executor.get_liquidation_info(symbol)
                if liq_info:
                    liq_price = liq_info["liquidation_price"]
                    mark_price = liq_info["mark_price"]
                    leverage = liq_info.get("leverage", "?")
                    distance_pct = abs(mark_price - liq_price) / mark_price * 100

                    if distance_pct < LIQ_AUTO_CLOSE_PCT:
                        await _auto_close_pair(
                            pair_id, symbol, legs,
                            reason=MSG["auto_close_reason_liq"].format(
                                exchange=exch_name, distance=distance_pct, threshold=LIQ_AUTO_CLOSE_PCT,
                                mark=mark_price, liq=liq_price, leverage=leverage,
                            ),
                        )
                        break

                    elif distance_pct < LIQ_WARN_PCT:
                        alert_key = f"liq:{pair_id}:{exch_name}:warn"
                        if time.time() - _liq_alerts_sent.get(alert_key, 0) >= LIQ_ALERT_COOLDOWN_SECONDS:
                            _liq_alerts_sent[alert_key] = time.time()
                            keyboard = InlineKeyboardMarkup([[
                                InlineKeyboardButton("❌ Закрыть пару", callback_data=f"close_pair:{pair_id}:{symbol}"),
                            ]])
                            await send_message(
                                MSG["liq_risk_alert"].format(
                                    symbol=symbol, exchange=exch_name, direction=leg["direction"],
                                    distance=distance_pct, mark=mark_price, liq=liq_price,
                                    leverage=leverage, threshold=LIQ_AUTO_CLOSE_PCT,
                                ),
                                reply_markup=keyboard,
                            )

                # Отклонение цены от входа (для бирж без ликвидационной цены)
                elif leg.get("entry_price"):
                    entry = leg["entry_price"]
                    rate = rates_map.get(f"{exch_name}:{symbol}")
                    cur_price = rate.mark_price if rate and rate.mark_price else 0
                    if cur_price and entry:
                        if leg["direction"] == "LONG":
                            loss_pct = (entry - cur_price) / entry * 100
                        else:
                            loss_pct = (cur_price - entry) / entry * 100

                        direction_str = MSG["price_went_down"] if leg["direction"] == "LONG" else MSG["price_went_up"]

                        if loss_pct >= _price_close_pct:
                            await _auto_close_pair(
                                pair_id, symbol, legs,
                                reason=MSG["auto_close_reason_price"].format(
                                    exchange=exch_name, direction=leg["direction"], direction_str=direction_str,
                                    loss=loss_pct, entry=entry, current=cur_price,
                                ),
                            )
                            break

                        elif loss_pct > PRICE_WARN_PCT:
                            alert_key = f"liq:{pair_id}:{exch_name}:price"
                            if time.time() - _liq_alerts_sent.get(alert_key, 0) >= LIQ_ALERT_COOLDOWN_SECONDS:
                                _liq_alerts_sent[alert_key] = time.time()
                                keyboard = InlineKeyboardMarkup([[
                                    InlineKeyboardButton("❌ Закрыть пару", callback_data=f"close_pair:{pair_id}:{symbol}"),
                                ]])
                                await send_message(
                                    MSG["price_risk_alert"].format(
                                        symbol=symbol, exchange=exch_name, direction=leg["direction"],
                                        direction_str=direction_str, loss=loss_pct,
                                        entry=entry, current=cur_price, threshold=_price_close_pct,
                                    ),
                                    reply_markup=keyboard,
                                )

                await executor.close()
            except Exception as e:
                logger.debug(f"Мониторинг {exch_name} {symbol}: {e}")


async def _auto_close_pair(pair_id: str, symbol: str, legs: list, reason: str):
    """Автоматически закрывает пару и уведомляет."""
    try:
        if not legs:
            legs = await get_positions_by_pair(pair_id)
        async with _trade_lock:
            await close_pair(pair_id=pair_id, symbol=symbol, legs=legs)
        exch_names = " × ".join(l["exchange"] for l in legs)
        await send_message(
            MSG["auto_close_ok"].format(symbol=symbol, exchanges=exch_names, reason=reason)
        )
    except Exception as e:
        logger.error(f"Автозакрытие {pair_id} ({symbol}) провалилось: {e}")
        await send_message(
            MSG["auto_close_fail"].format(symbol=symbol, reason=reason, error=e)
        )


# ─── Поиск новых возможностей ────────────────────────────────────────────────

def _enrich_opp_with_streaks(opp: dict) -> dict:
    """Добавляет в opp количество часов положительного Net APR для пары."""
    opp["pair_streak"] = get_pair_streak_hours(opp["exchange_a"], opp["exchange_b"], opp["symbol"])
    return opp


async def _scan_opportunities(exchange_rates: dict):
    """Ищет пары и отправляет сигналы."""
    opps = find_pair_opportunities(exchange_rates, _enabled_exchanges)

    # Обновляем стрики для всех найденных пар (и помечаем отсутствующие как дип)
    _update_pair_net_streaks(opps)

    if not opps:
        return

    logger.info(f"Найдено {len(opps)} возможностей")

    for opp in opps:
        signal_key = f"{opp['exchange_a']}:{opp['exchange_b']}:{opp['symbol']}:{opp['dir_a']}:{opp['dir_b']}"
        if not should_send_signal(signal_key, opp["net_apr"]):
            continue

        _enrich_opp_with_streaks(opp)
        await send_pair_signal(opp)
        _sent_signals[signal_key] = (opp["net_apr"], time.time())


# ─── Основной цикл сканирования ─────────────────────────────────────────────

async def scan_and_notify():
    """Сканируем все биржи, мониторим позиции, ищем возможности."""
    if _scan_lock.locked():
        logger.info("Сканирование уже идёт, пропускаем")
        return
    async with _scan_lock:
        await _scan_and_notify_inner()


async def _scan_and_notify_inner():
    logger.info("Запуск сканирования...")

    exchange_rates = await fetch_all_rates()
    if not exchange_rates:
        logger.error("Нет данных ни от одной биржи")
        return

    await save_funding_snapshot(exchange_rates)
    await _verify_positions(exchange_rates)
    await _monitor_open_pairs(exchange_rates)
    await _scan_opportunities(exchange_rates)


# ─── Telegram handlers ──────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    seen = await load_setting("welcome_seen", "0")
    if seen == "0":
        await save_setting("welcome_seen", "1")
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Подписался!", callback_data="welcome_subscribed"),
        ]])
        await update.message.reply_text(
            MSG["welcome_new"].format(channel_name=AUTHOR_CHANNEL_NAME, channel=AUTHOR_CHANNEL),
            reply_markup=keyboard,
        )
    else:
        await update.message.reply_text(
            MSG["welcome_back"],
            reply_markup=persistent_keyboard(),
        )


async def show_positions(update: Update):
    """Показывает открытые позиции."""
    position_groups = await get_open_pairs()

    if not position_groups:
        await update.message.reply_text(MSG["no_positions"])
        return

    # Собираем текущие ставки
    exchange_rates = await fetch_all_rates()
    rates_map = {}
    for exch_name, rates in exchange_rates.items():
        for r in rates:
            rates_map[f"{r.exchange}:{r.symbol}"] = r

    for group in position_groups:
        legs = group["legs"]
        pair_id = group["pair_id"]
        symbol = legs[0]["symbol"]
        opened_ago = (time.time() - legs[0]["opened_at"]) / 3600

        if pair_id and len(legs) >= 2:
            # Двуногая пара
            total_usd = sum(l["position_size_usd"] for l in legs)
            net_apr = calc_net_apr_for_pair(legs, rates_map)
            apr_status = "🟢" if net_apr >= 50 else "🟡" if net_apr >= 0 else "🔴"

            lines = []
            total_earned = 0
            has_earnings = False
            for leg in legs:
                dir_label = MSG["short_arrow"] if leg["direction"] == "SHORT" else MSG["long_arrow"]
                rate = rates_map.get(f"{leg['exchange']}:{symbol}")
                # Показываем сырой APR с биржи: знак уже несёт смысл
                # + означает лонги платят шортам, - означает шорты платят лонгам
                apr_str = f"<code>{rate.apr:+.1f}%</code>" if rate else "<i>?</i>"
                lines.append(f"  {leg['exchange']} ({dir_label}): <code>${leg['entry_price']:.4f}</code> APR: {apr_str}")

                avg_rate = await get_avg_rate_since(leg["exchange"], symbol, legs[0]["opened_at"])
                use_rate = avg_rate if avg_rate is not None else (rate.rate if rate else None)
                if use_rate is not None:
                    sign = 1 if leg["direction"] == "SHORT" else -1
                    earned = sign * use_rate * opened_ago * leg["position_size_usd"]
                    total_earned += earned
                    has_earnings = True

            earned_str = f"<code>${total_earned:.4f}</code> ({MSG['earned_estimate']})" if has_earnings else f"<i>{MSG['no_data']}</i>"

            exch_names = " × ".join(l["exchange"] for l in legs)
            text = (
                f"🔀 <b>{symbol}</b> — {exch_names} {apr_status}\n\n"
                + "\n".join(lines) + "\n"
                f"{MSG['size_label']}: <code>${total_usd:.0f}</code> (по <code>${legs[0]['position_size_usd']:.0f}</code> {MSG['per_leg']})\n"
                f"{MSG['opened_label']}: <code>{opened_ago:.1f}{MSG['h_ago']}</code>\n"
                f"  {MSG['net_apr_label']}: <code>{net_apr:+.1f}%</code>\n"
                f"{MSG['earned_label']}: {earned_str}"
            )
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(MSG["btn_add"], callback_data=f"scale_in:{pair_id}:{symbol}"),
                InlineKeyboardButton(MSG["btn_close_pair"], callback_data=f"close_pair:{pair_id}:{symbol}"),
            ]])
        else:
            # Одиночная позиция
            pos = legs[0]
            label = MSG["short"] if pos.get("direction") == "SHORT" else MSG["long"]
            rate = rates_map.get(f"{pos['exchange']}:{pos['symbol']}")
            current_apr = abs(rate.apr) if rate else 0
            avg_rate = await get_avg_rate_since(pos["exchange"], pos["symbol"], pos["opened_at"])
            use_rate = avg_rate if avg_rate is not None else (rate.rate if rate else 0)
            earned = abs(use_rate) * opened_ago * pos["position_size_usd"]
            status = "🟢" if current_apr >= 100 else "🟡" if current_apr >= 30 else "🔴"

            text = (
                f"📌 <b>{pos['symbol']}</b> — {pos['exchange']} {status}\n\n"
                f"{MSG['type_label']}: <code>{label}</code>\n"
                f"{MSG['size_label']}: <code>${pos['position_size_usd']}</code>\n"
                f"{MSG['entry_price_label']}: <code>${pos['entry_price']:.4f}</code>\n"
                f"{MSG['opened_label']}: <code>{opened_ago:.1f}{MSG['h_ago']}</code>\n"
                f"{MSG['apr_label']}: <code>{current_apr:.1f}%</code>\n"
                f"{MSG['earned_label']} (~): <code>${earned:.4f}</code>"
            )
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(MSG["btn_close"], callback_data=f"close:{pos['id']}:{pos['symbol']}")
            ]])

        await update.message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=keyboard
        )


async def _refresh_settings(query):
    """Обновляет сообщение настроек на месте (без мигания)."""
    text, markup = _build_settings()
    try:
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    except Exception:
        # Если edit не сработал (например, текст не изменился) — ничего страшного
        pass


def _build_settings() -> tuple:
    """Строит текст и клавиатуру для меню настроек. Используется и при показе, и при обновлении."""
    rows = []

    # Переключатель бирж
    rows.append([InlineKeyboardButton(MSG["settings_exchanges_header"], callback_data="noop")])
    exchange_btns = []
    for exch_id, exch_name in EXCHANGES.items():
        is_on = exch_name in _enabled_exchanges
        exchange_btns.append(InlineKeyboardButton(
            f"{'✅' if is_on else '❌'} {exch_name}",
            callback_data=f"toggle_exchange:{exch_name}"
        ))
        if len(exchange_btns) == 3:
            rows.append(exchange_btns)
            exchange_btns = []
    if exchange_btns:
        rows.append(exchange_btns)

    # Режим размера позиций
    rows.append([InlineKeyboardButton(MSG["settings_size_header"], callback_data="noop")])
    is_global = _position_size_mode == "global"
    rows.append([
        InlineKeyboardButton(
            f"{'🔘' if is_global else '⚪'} {MSG['settings_global_btn']} (${_global_position_size:.0f})",
            callback_data="size_mode:global"
        ),
        InlineKeyboardButton(
            f"{'🔘' if not is_global else '⚪'} {MSG['settings_per_exchange_btn']}",
            callback_data="size_mode:per_exchange"
        ),
    ])

    if is_global:
        rows.append([
            InlineKeyboardButton("$15", callback_data="setsize:global:15"),
            InlineKeyboardButton("$50", callback_data="setsize:global:50"),
            InlineKeyboardButton("$100", callback_data="setsize:global:100"),
            InlineKeyboardButton("$250", callback_data="setsize:global:250"),
            InlineKeyboardButton("$500", callback_data="setsize:global:500"),
        ])
        rows.append([InlineKeyboardButton(MSG["settings_enter_manual"], callback_data="setsize:global:manual")])
    else:
        for exch_id, exch_name in EXCHANGES.items():
            if exch_name not in _enabled_exchanges:
                continue
            size = _exchange_sizes.get(exch_name, _global_position_size)
            rows.append([InlineKeyboardButton(f"── {exch_name} (${size:.0f}) ──", callback_data="noop")])
            rows.append([
                InlineKeyboardButton("$15", callback_data=f"setsize:{exch_name}:15"),
                InlineKeyboardButton("$50", callback_data=f"setsize:{exch_name}:50"),
                InlineKeyboardButton("$100", callback_data=f"setsize:{exch_name}:100"),
                InlineKeyboardButton("$250", callback_data=f"setsize:{exch_name}:250"),
                InlineKeyboardButton("$500", callback_data=f"setsize:{exch_name}:500"),
            ])
            rows.append([InlineKeyboardButton(MSG["settings_enter_exchange"].format(exch=exch_name), callback_data=f"setsize:{exch_name}:manual")])

    if is_global:
        desc = MSG["settings_mode_global"].format(size=_global_position_size)
    else:
        parts = [f"{n}: <code>${_exchange_sizes.get(n, _global_position_size):.0f}</code>" for n in sorted(_enabled_exchanges)]
        desc = MSG["settings_mode_per_exchange"] + "\n" + "\n".join(parts)

    # Секция защиты
    rows.append([InlineKeyboardButton("─── Защита позиций ───", callback_data="noop")])
    prot_label = "✅ Защита включена" if _protection_enabled else "❌ Защита выключена"
    rows.append([InlineKeyboardButton(prot_label, callback_data="toggle_protection")])

    if _protection_enabled:
        rows.append([InlineKeyboardButton(
            f"📉 Закрыть при падении цены: {_price_close_pct:.0f}%", callback_data="noop"
        )])
        _pct_presets = [15, 25, 35, 50, 100]
        rows.append([
            InlineKeyboardButton(f"{'▶ ' if _price_close_pct == v else ''}{v}%", callback_data=f"set_price_pct:{v}")
            for v in _pct_presets
        ])
        rows.append([InlineKeyboardButton("✏️ Указать вручную", callback_data="set_price_pct:manual")])

        rows.append([InlineKeyboardButton(
            f"📊 Закрыть при минус-фандинге: {_neg_apr_hours:.0f}ч", callback_data="noop"
        )])
        _hours_presets = [1, 2, 4, 6, 12, 24]
        rows.append([
            InlineKeyboardButton(f"{'▶ ' if _neg_apr_hours == v else ''}{v}ч", callback_data=f"set_neg_hours:{v}")
            for v in _hours_presets
        ])
        rows.append([InlineKeyboardButton("✏️ Указать вручную", callback_data="set_neg_hours:manual")])

    prot_desc = ""
    if _protection_enabled:
        prot_desc = f"\n\n🛡 Защита: закрытие при падении &gt;{_price_close_pct:.0f}% или минус-фандинге &gt;{_neg_apr_hours:.0f}ч"
    else:
        prot_desc = "\n\n⚠️ Защита выключена — автозакрытие не работает"

    enabled_list = ", ".join(sorted(_enabled_exchanges)) or MSG["settings_none_enabled"]
    text = (
        f"{MSG['settings_title']}\n\n"
        f"{MSG['settings_enabled']}: {enabled_list}\n"
        f"{desc}"
        f"{prot_desc}"
    )
    return text, InlineKeyboardMarkup(rows)


async def show_balances(update: Update):
    """Показывает балансы на всех включённых биржах."""
    msg = await update.message.reply_text(MSG["loading_balances"])
    lines = [f"{MSG['balances_title']}\n"]
    total = 0.0
    no_api = []
    for exch_name in sorted(_enabled_exchanges):
        try:
            executor = get_executor(exch_name)
            balance = await executor.get_balance()
            if balance is not None:
                lines.append(f"  {exch_name}: <code>${balance:.2f}</code>")
                total += balance
            else:
                no_api.append(exch_name)
        except Exception as e:
            logger.error(f"Ошибка баланса {exch_name}: {e}")
            lines.append(f"  {exch_name}: {MSG['balance_error']}")
    lines.append(f"\n{MSG['balances_total']}: <code>${total:.2f}</code>")
    if no_api:
        lines.append(f"<i>{', '.join(no_api)} — {MSG['no_api_balance']}</i>")
    await msg.edit_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def show_settings(update: Update):
    """Показывает меню настроек."""
    text, markup = _build_settings()
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


HISTORY_PAGE_SIZE = 5


async def _build_history_page(page: int) -> tuple:
    total_count = await count_closed_pairs()
    if total_count == 0:
        return MSG["no_history"], None

    total_pages = (total_count + HISTORY_PAGE_SIZE - 1) // HISTORY_PAGE_SIZE
    page = max(0, min(page, total_pages - 1))
    items = await get_closed_pairs(limit=HISTORY_PAGE_SIZE, offset=page * HISTORY_PAGE_SIZE)

    lines = [f"{MSG['history_title']} ({MSG['history_page'].format(page=page + 1, total=total_pages)})\n"]
    for item in items:
        legs = item["legs"]
        if not legs:
            continue
        symbol = legs[0]["symbol"]
        exch_names = " × ".join(l["exchange"] for l in legs)
        closed_at = item.get("closed_at", 0)
        ago_h = (time.time() - closed_at) / 3600 if closed_at else 0

        total_pnl = sum(l.get("pnl_price_usd") or 0 for l in legs)
        total_fees = sum(l.get("fees_usd") or 0 for l in legs)
        total_usd = sum(l.get("position_size_usd", 0) for l in legs)

        # Считаем фандинг по каждой ноге за время жизни позиции
        total_funding = 0.0
        has_funding = False
        opened_at = legs[0].get("opened_at") or 0
        for leg in legs:
            avg_rate = await get_avg_rate_between(leg["exchange"], symbol, opened_at, closed_at or time.time())
            if avg_rate is not None:
                opened_ago_h = (closed_at - opened_at) / 3600 if closed_at and opened_at else 0
                sign = 1 if leg["direction"] == "SHORT" else -1
                total_funding += sign * avg_rate * opened_ago_h * leg["position_size_usd"]
                has_funding = True

        total_result = total_pnl + total_funding - total_fees
        result_emoji = "🟢" if total_result >= 0 else "🔴"

        funding_str = f" | {MSG['history_funding']}: <code>{total_funding:+.4f}</code>" if has_funding else ""
        result_str = f" | {MSG['history_total']}: <code>{total_result:+.4f}</code>" if has_funding else ""

        lines.append(
            f"{result_emoji} <b>{symbol}</b> — {exch_names}\n"
            f"  💵 ${total_usd:.0f} | P&L: <code>{total_pnl:+.4f}</code>{funding_str}{result_str}\n"
            f"  {MSG['history_fees']}: <code>-{total_fees:.4f}</code> | ⏱ {ago_h:.0f}{MSG['h_ago']}"
        )

    nav_btns = []
    if page > 0:
        nav_btns.append(InlineKeyboardButton("⬅️", callback_data=f"history_page:{page - 1}"))
    if page < total_pages - 1:
        nav_btns.append(InlineKeyboardButton("➡️", callback_data=f"history_page:{page + 1}"))

    keyboard = InlineKeyboardMarkup([nav_btns]) if nav_btns else None
    return "\n".join(lines), keyboard


async def show_history(update: Update):
    text, keyboard = await _build_history_page(0)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def _fetch_rates_for_symbol(symbol: str, exch_a: str, exch_b: str):
    """Получает свежие APR для конкретного символа на двух биржах."""
    try:
        rates = await fetch_all_rates()
        rate_a = rate_b = None
        for exchange_name, rate_list in rates.items():
            if exchange_name == exch_a:
                rate_a = next((r for r in rate_list if r.symbol == symbol), None)
            if exchange_name == exch_b:
                rate_b = next((r for r in rate_list if r.symbol == symbol), None)
        if rate_a and rate_b:
            return rate_a.apr, rate_b.apr
    except Exception as e:
        logger.warning(f"Не удалось перепроверить фандинг: {e}")
    return None


async def scan_manual(update: Update):
    """Ручное сканирование — отправляет карточки с кнопками."""
    msg = await update.message.reply_text(MSG["scanning"])
    exchange_rates = await fetch_all_rates()
    if not exchange_rates:
        await msg.edit_text(MSG["no_exchange_data"])
        return

    opps = find_pair_opportunities(exchange_rates, _enabled_exchanges)

    if not opps:
        await msg.edit_text(MSG["no_pairs"])
        return

    await msg.delete()

    _update_pair_net_streaks(opps)
    for opp in opps:
        _enrich_opp_with_streaks(opp)
        await send_pair_signal(opp)

    # Итоговое сообщение
    min_apr = opps[-1]["net_apr"]
    max_apr = opps[0]["net_apr"]
    await send_message(MSG["scan_result"].format(count=len(opps), min=min_apr, max=max_apr))


# ─── Обработка кнопок ────────────────────────────────────────────────────────

async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _waiting_for_size, _waiting_for_scale_in

    # Игнорируем сообщения не от владельца
    if str(update.effective_chat.id) != str(TELEGRAM_CHAT_ID):
        return

    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "skip" or data == "noop":
        return

    # ── Приветствие — подписался ──────────────────────────────────────────────
    if data == "welcome_subscribed":
        await query.edit_message_text(MSG["welcome_subscribed"])
        await query.message.reply_text(
            MSG["control_buttons"],
            reply_markup=persistent_keyboard(),
        )
        return

    # ── Открытие пары ────────────────────────────────────────────────────────
    if data.startswith("open_pair:"):
        parts = data.split(":")
        if len(parts) < 6:
            return
        _, exch_a, exch_b, symbol, dir_a, dir_b = parts[:6]
        signal_apr = float(parts[6]) if len(parts) > 6 else 0.0

        lock_key = f"{exch_a}:{exch_b}:{symbol}"
        if lock_key in _opening_pairs:
            await query.edit_message_text(MSG["already_opening"])
            return
        _opening_pairs.add(lock_key)

        # Размер = минимум из двух бирж (если раздельный режим)
        size = min(get_position_size(exch_a), get_position_size(exch_b))

        await query.edit_message_text(MSG["opening_pair"].format(symbol=symbol))

        try:
            # Перепроверяем фандинг перед открытием
            from core.analyzer import _calc_pair_apr
            fresh_rates = await _fetch_rates_for_symbol(symbol, exch_a, exch_b)
            if fresh_rates:
                rate_a_fresh, rate_b_fresh = fresh_rates
                new_net, new_dir_a, new_dir_b = _calc_pair_apr(rate_a_fresh, rate_b_fresh)
                if new_net < 10:  # APR упал ниже 10%
                    await query.edit_message_text(
                        MSG["funding_changed"].format(apr=new_net),
                    )
                    _opening_pairs.discard(lock_key)
                    return
                if new_dir_a != dir_a or new_dir_b != dir_b:
                    dir_a, dir_b = new_dir_a, new_dir_b
                    logger.info(f"Направления обновлены: {exch_a}={dir_a}, {exch_b}={dir_b}")

            entry_apr = new_net if fresh_rates else signal_apr
            async with _trade_lock:
                result = await open_pair(exch_a, exch_b, symbol, dir_a, dir_b, size, entry_apr=entry_apr)
            leg_a = result["leg_a"]
            leg_b = result["leg_b"]
            await query.edit_message_text(
                MSG["pair_opened"].format(
                    symbol=symbol,
                    exch_a=exch_a, size_a=leg_a['size'], price_a=leg_a['price'], dir_a=dir_a,
                    exch_b=exch_b, size_b=leg_b['size'], price_b=leg_b['price'], dir_b=dir_b,
                    size=size,
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            await query.edit_message_text(MSG["open_error"].format(error=e), parse_mode=ParseMode.HTML)
        finally:
            _opening_pairs.discard(lock_key)

    # ── Закрытие пары ────────────────────────────────────────────────────────
    elif data.startswith("close_pair:"):
        parts = data.split(":")
        pair_id = parts[1]
        symbol = parts[2] if len(parts) > 2 else "?"

        await query.edit_message_text(MSG["closing_pair"].format(symbol=symbol))
        try:
            async with _trade_lock:
                legs = await get_positions_by_pair(pair_id)
                await close_pair(pair_id, symbol, legs)
            await query.edit_message_text(MSG["pair_closed"].format(symbol=symbol), parse_mode=ParseMode.HTML)
        except Exception as e:
            await query.edit_message_text(MSG["close_error"].format(error=e), parse_mode=ParseMode.HTML)

    # ── Закрытие одиночной позиции ────────────────────────────────────────
    elif data.startswith("close:"):
        parts = data.split(":")
        pos_id = parts[1]
        symbol = parts[2] if len(parts) > 2 else "?"

        await query.edit_message_text(MSG["closing_position"].format(symbol=symbol))
        try:
            async with _trade_lock:
                pos = await get_position_by_id(pos_id)
                if not pos:
                    await query.edit_message_text(MSG["position_not_found"].format(id=pos_id))
                    return
                executor = get_executor(pos["exchange"])
                await executor.market_close(pos["symbol"], pos["size"], pos["direction"] == "LONG")
                await mark_position_closed(pos_id)
            await query.edit_message_text(
                MSG["position_closed"].format(symbol=symbol, exchange=pos['exchange']),
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            await query.edit_message_text(MSG["close_error"].format(error=e), parse_mode=ParseMode.HTML)

    # ── Scale in ─────────────────────────────────────────────────────────────
    elif data.startswith("scale_in:"):
        parts = data.split(":")
        pair_id = parts[1]
        symbol = parts[2] if len(parts) > 2 else "?"
        _waiting_for_scale_in = (pair_id, symbol)
        await query.edit_message_text(MSG["scale_in_prompt"].format(symbol=symbol))

    # ── Переключение бирж ────────────────────────────────────────────────────
    elif data.startswith("toggle_exchange:"):
        exch_name = data.split(":")[1]
        if exch_name in _enabled_exchanges:
            _enabled_exchanges.discard(exch_name)
        else:
            _enabled_exchanges.add(exch_name)
        await _save_settings()
        await _refresh_settings(query)

    # ── Режим размера позиций ────────────────────────────────────────────────
    elif data.startswith("size_mode:"):
        global _position_size_mode
        _position_size_mode = data.split(":")[1]
        await _save_settings()
        await _refresh_settings(query)

    # ── Установка размера ────────────────────────────────────────────────────
    elif data.startswith("setsize:"):
        parts = data.split(":")
        target = parts[1]  # "global" или exchange_name
        value = parts[2]

        if value == "manual":
            _waiting_for_size = target
            await query.message.delete()
            target_label = MSG["all_exchanges"] if target == "global" else target
            await query.message.chat.send_message(
                MSG["enter_size_prompt"].format(target=target_label)
            )
        else:
            size = float(value)
            if target == "global":
                _global_position_size = size
            else:
                _exchange_sizes[target] = size
            await _save_settings()
            await _refresh_settings(query)

    # ── Настройки защиты ────────────────────────────────────────────────────
    elif data == "toggle_protection":
        global _protection_enabled
        _protection_enabled = not _protection_enabled
        await _save_settings()
        await _refresh_settings(query)

    elif data.startswith("set_price_pct:"):
        global _price_close_pct, _waiting_for_price_pct
        val = data.split(":")[1]
        if val == "manual":
            _waiting_for_price_pct = True
            await query.message.delete()
            await query.message.chat.send_message("Введи % падения цены для автозакрытия (например: 40)")
        else:
            _price_close_pct = float(val)
            await _save_settings()
            await _refresh_settings(query)

    elif data.startswith("set_neg_hours:"):
        global _neg_apr_hours, _waiting_for_neg_hours
        val = data.split(":")[1]
        if val == "manual":
            _waiting_for_neg_hours = True
            await query.message.delete()
            await query.message.chat.send_message("Введи количество часов в минус-фандинге для автозакрытия (например: 8)")
        else:
            _neg_apr_hours = float(val)
            await _save_settings()
            await _refresh_settings(query)

    # ── Пагинация истории ────────────────────────────────────────────────────
    elif data.startswith("history_page:"):
        page = int(data.split(":")[1])
        text, keyboard = await _build_history_page(page)
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений."""
    global _waiting_for_size, _waiting_for_scale_in, _waiting_for_price_pct, _waiting_for_neg_hours

    text = update.message.text.strip()

    # Кнопки клавиатуры
    if text == BTN_POSITIONS:
        await show_positions(update)
    elif text == BTN_SCAN:
        await scan_manual(update)
    elif text == BTN_BALANCES:
        await show_balances(update)
    elif text == BTN_HISTORY:
        await show_history(update)
    elif text == BTN_SETTINGS:
        await show_settings(update)
    elif text == BTN_SUPPORT:
        author_links = MSG.get("author_links") or f'{MSG["support_channel"]}: <a href="{AUTHOR_CHANNEL}">{AUTHOR_CHANNEL_NAME}</a>'
        await update.message.reply_text(
            f"{MSG['support_title']}\n\n"
            f"{author_links}\n\n"
            f"EVM: <code>{DONATION_WALLET_EVM}</code>\n"
            f"SOL: <code>{DONATION_WALLET_SOL}</code>",
            parse_mode=ParseMode.HTML,
        )
    # Ввод размера позиции
    elif _waiting_for_size is not None:
        target = _waiting_for_size
        _waiting_for_size = None
        try:
            size = float(text.replace("$", "").replace(",", "."))
            if size < 5:
                await update.message.reply_text(MSG["min_size_error"])
                return
            if target == "global":
                global _global_position_size
                _global_position_size = size
            else:
                _exchange_sizes[target] = size
            await _save_settings()
            target_label = MSG["size_set_ok_global"] if target == "global" else target
            await update.message.reply_text(
                MSG["size_set_ok"].format(target=target_label, size=size),
                parse_mode=ParseMode.HTML,
            )
        except ValueError:
            await update.message.reply_text(MSG["enter_number_error"], parse_mode=ParseMode.HTML)
    # Ввод % падения цены вручную
    elif _waiting_for_price_pct:
        _waiting_for_price_pct = False
        try:
            val = float(text.replace("%", "").replace(",", "."))
            if val <= 0 or val > 100:
                await update.message.reply_text("Введи число от 1 до 100")
                return
            global _price_close_pct
            _price_close_pct = val
            await _save_settings()
            await update.message.reply_text(f"✅ Закрытие при падении цены: <code>{val:.0f}%</code>", parse_mode=ParseMode.HTML)
        except ValueError:
            await update.message.reply_text(MSG["enter_number_error"], parse_mode=ParseMode.HTML)

    # Ввод часов минус-фандинга вручную
    elif _waiting_for_neg_hours:
        _waiting_for_neg_hours = False
        try:
            val = float(text.replace("ч", "").replace(",", "."))
            if val <= 0 or val > 168:
                await update.message.reply_text("Введи число от 1 до 168 (часов)")
                return
            global _neg_apr_hours
            _neg_apr_hours = val
            await _save_settings()
            await update.message.reply_text(f"✅ Закрытие при минус-фандинге: <code>{val:.0f}ч</code>", parse_mode=ParseMode.HTML)
        except ValueError:
            await update.message.reply_text(MSG["enter_number_error"], parse_mode=ParseMode.HTML)

    # Ввод суммы для scale_in
    elif _waiting_for_scale_in is not None:
        pair_id, symbol = _waiting_for_scale_in
        _waiting_for_scale_in = None
        try:
            add_usd = float(text.replace("$", "").replace(",", "."))
            if add_usd < 5:
                await update.message.reply_text(MSG["min_size_error"])
                return
            await update.message.reply_text(MSG["scale_in_adding"].format(amount=add_usd, symbol=symbol))
            async with _trade_lock:
                legs = await get_positions_by_pair(pair_id)
                result = await scale_in_pair(pair_id, symbol, legs, add_usd)
            await update.message.reply_text(
                MSG["scale_in_done"].format(amount=add_usd, symbol=symbol),
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            await update.message.reply_text(MSG["scale_in_error"].format(error=e), parse_mode=ParseMode.HTML)


# ─── Запуск ──────────────────────────────────────────────────────────────────

async def post_init(app):
    """Выполняется после запуска бота."""
    await init_db()
    await _load_settings()

    # Сброс антиспама при запуске — чтобы сразу пришли сигналы
    _sent_signals.clear()
    # Первое сканирование в фоне — бот запустится мгновенно, сигналы придут через ~10с
    asyncio.create_task(scan_and_notify())

    scheduler = AsyncIOScheduler()
    scheduler.add_job(scan_and_notify, "interval", seconds=SCAN_INTERVAL_SECONDS)
    scheduler.start()
    logger.info(f"Планировщик запущен: каждые {SCAN_INTERVAL_SECONDS} сек")


def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN не задан в .env")
    if not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_CHAT_ID не задан в .env")

    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    # Разрешаем только владельцу (TELEGRAM_CHAT_ID)
    owner_filter = filters.Chat(chat_id=int(TELEGRAM_CHAT_ID))
    app.add_handler(CommandHandler("start", cmd_start, filters=owner_filter))
    app.add_handler(CallbackQueryHandler(handle_button))  # доп. проверка внутри
    app.add_handler(MessageHandler(owner_filter & filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Бот запускается...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
