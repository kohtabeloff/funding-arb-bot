"""
Универсальный executor пар — работает с любой комбинацией бирж.
Одна функция open_pair() вместо отдельных open_pair() и open_pair_vr_ext().
"""
import asyncio
import logging
import time

from core.exchanges.base import BaseExchangeExecutor
from db.database import save_pair, close_pair as db_close_pair, scale_pair_db_generic

logger = logging.getLogger(__name__)

# Кеш executor'ов — чтобы не пересоздавать SDK и не делать load_markets() при каждом ордере
_executor_cache: dict[str, BaseExchangeExecutor] = {}


def get_executor(exchange_name: str) -> BaseExchangeExecutor:
    """
    Фабрика: возвращает (или создаёт) executor для биржи по имени.
    Кешируется — SDK и маркеты загружаются только один раз за сессию.
    """
    if exchange_name in _executor_cache:
        return _executor_cache[exchange_name]

    import config as cfg

    if exchange_name == "Backpack":
        from core.exchanges.backpack import BackpackExecutor
        if not cfg.BACKPACK_API_KEY or not cfg.BACKPACK_API_SECRET:
            raise RuntimeError("Backpack API ключи не заданы в .env")
        executor = BackpackExecutor(cfg.BACKPACK_API_KEY, cfg.BACKPACK_API_SECRET)

    elif exchange_name == "Lighter":
        from core.exchanges.lighter import LighterExecutor
        if not cfg.LIGHTER_API_PRIVATE_KEY:
            raise RuntimeError("Lighter API ключ не задан в .env")
        executor = LighterExecutor(
            cfg.LIGHTER_API_PRIVATE_KEY,
            cfg.LIGHTER_API_KEY_INDEX,
            cfg.LIGHTER_ACCOUNT_INDEX,
        )

    elif exchange_name == "Hyperliquid":
        from core.exchanges.hyperliquid import HyperliquidExecutor
        if not cfg.HYPERLIQUID_PRIVATE_KEY:
            raise RuntimeError("Hyperliquid приватный ключ не задан в .env")
        executor = HyperliquidExecutor(cfg.HYPERLIQUID_PRIVATE_KEY, cfg.WALLET_ADDRESS)

    elif exchange_name == "GRVT":
        from core.exchanges.grvt import GRVTExecutor
        if not cfg.GRVT_API_KEY:
            raise RuntimeError("GRVT API ключ не задан в .env")
        executor = GRVTExecutor(cfg.GRVT_API_KEY, cfg.GRVT_PRIVATE_KEY, cfg.GRVT_TRADING_ACCOUNT_ID)

    elif exchange_name == "Aster":
        from core.exchanges.aster import AsterExecutor
        if not cfg.ASTER_API_KEY:
            raise RuntimeError("Aster API ключ не задан в .env")
        executor = AsterExecutor(cfg.ASTER_API_KEY, cfg.ASTER_API_SECRET)

    else:
        raise ValueError(f"Неизвестная биржа: {exchange_name}")

    _executor_cache[exchange_name] = executor
    return executor


async def open_pair(
    exchange_a_name: str,
    exchange_b_name: str,
    symbol: str,
    dir_a: str,     # "LONG" или "SHORT"
    dir_b: str,     # "LONG" или "SHORT"
    size_usd: float,
    entry_apr: float,
) -> dict:
    """
    Открывает дельта-нейтральную пару на любых двух биржах.
    Возвращает pair_id для дальнейшего управления.
    """
    exec_a = get_executor(exchange_a_name)
    exec_b = get_executor(exchange_b_name)

    is_long_a = (dir_a == "LONG")
    is_long_b = (dir_b == "LONG")

    logger.info(
        f"Открываем пару {symbol}: "
        f"{exchange_a_name} {'лонг' if is_long_a else 'шорт'}, "
        f"{exchange_b_name} {'лонг' if is_long_b else 'шорт'}, ${size_usd}"
    )

    # Проверяем балансы параллельно
    bal_a, bal_b = await asyncio.gather(
        exec_a.get_balance(),
        exec_b.get_balance(),
        return_exceptions=True,
    )
    for name, balance in [(exchange_a_name, bal_a), (exchange_b_name, bal_b)]:
        if isinstance(balance, Exception):
            continue
        if balance is not None:
            logger.info(f"{name} баланс: ${balance:.2f}")
            if balance < size_usd * 0.1:
                await _close_executor(exec_a)
                await _close_executor(exec_b)
                raise RuntimeError(
                    f"{name}: недостаточно баланса. "
                    f"Есть: ${balance:.2f}, нужно как минимум: ${size_usd * 0.1:.2f}"
                )

    # Открываем обе ноги одновременно — минимизируем ценовой лаг между ногами
    result_a, result_b = await asyncio.gather(
        exec_a.market_open(symbol, is_long_a, size_usd),
        exec_b.market_open(symbol, is_long_b, size_usd),
        return_exceptions=True,
    )

    a_ok = not isinstance(result_a, Exception)
    b_ok = not isinstance(result_b, Exception)

    # Если одна нога упала — откатываем вторую
    if a_ok and not b_ok:
        logger.error(f"{exchange_b_name} не открылся: {result_b} — закрываем {exchange_a_name}")
        await _rollback_leg(exec_a, symbol, result_a, is_long_a, exchange_a_name, exchange_b_name, result_b)
        await _close_executor(exec_a)
        await _close_executor(exec_b)
        raise RuntimeError(f"{exchange_b_name} ошибка: {result_b}\n{exchange_a_name} закрыт автоматически.")

    if not a_ok and b_ok:
        logger.error(f"{exchange_a_name} не открылся: {result_a} — закрываем {exchange_b_name}")
        await _rollback_leg(exec_b, symbol, result_b, is_long_b, exchange_b_name, exchange_a_name, result_a)
        await _close_executor(exec_a)
        await _close_executor(exec_b)
        raise RuntimeError(f"{exchange_a_name} ошибка: {result_a}\n{exchange_b_name} закрыт автоматически.")

    if not a_ok and not b_ok:
        await _close_executor(exec_a)
        await _close_executor(exec_b)
        raise RuntimeError(f"Обе ноги не открылись.\n{exchange_a_name}: {result_a}\n{exchange_b_name}: {result_b}")

    # Обе ноги открыты — сохраняем в БД
    # Короткое имя для pair_id: первые 2 буквы каждой биржи
    tag_a = exchange_a_name[:2].upper()
    tag_b = exchange_b_name[:2].upper()
    pair_id = f"{int(time.time())}_{symbol}_{tag_a}_{tag_b}"

    try:
        await save_pair(pair_id, [
            {
                "symbol": symbol, "exchange": exchange_a_name, "direction": dir_a,
                "size": result_a["size"], "entry_price": result_a["price"],
                "position_size_usd": size_usd, "entry_apr": entry_apr,
            },
            {
                "symbol": symbol, "exchange": exchange_b_name, "direction": dir_b,
                "size": result_b["size"], "entry_price": result_b["price"],
                "position_size_usd": size_usd, "entry_apr": entry_apr,
            },
        ])
    except Exception as db_err:
        # Критично: позиции открыты, но БД не записала. Шлём алерт.
        logger.critical(f"БД не сохранила пару {pair_id}: {db_err}")
        try:
            from bot.telegram import send_message
            await send_message(
                f"🚨 *КРИТИЧНО: пара открыта, но НЕ записана в БД!*\n\n"
                f"*{symbol}*: {exchange_a_name} {dir_a} + {exchange_b_name} {dir_b}\n"
                f"Размер: `${size_usd}`\n"
                f"Ошибка БД: `{db_err}`\n\n"
                f"⚠️ Запиши или закрой вручную!"
            )
        except Exception:
            pass

    await _close_executor(exec_a)
    await _close_executor(exec_b)
    logger.info(f"Пара открыта: {pair_id}")
    return {
        "pair_id": pair_id,
        "symbol": symbol,
        "leg_a": result_a,
        "leg_b": result_b,
    }


async def close_pair(pair_id: str, symbol: str, legs: list[dict]) -> dict:
    """
    Закрывает обе ноги пары. legs — список позиций из БД.
    """
    executors = {}
    tasks = []

    for leg in legs:
        exch_name = leg["exchange"]
        executor = get_executor(exch_name)
        executors[exch_name] = executor
        was_long = (leg["direction"] == "LONG")
        tasks.append(executor.market_close(symbol, leg["size"], was_long))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Собираем P&L для успешно закрытых ног
    leg_pnl: dict = {}
    errors = []
    for leg, result in zip(legs, results):
        if isinstance(result, Exception):
            errors.append(f"{leg['exchange']}: {result}")
            continue
        exit_price = result.get("price") or leg["entry_price"]
        was_long = (leg["direction"] == "LONG")
        pnl = (exit_price - leg["entry_price"]) * leg["size"]
        if not was_long:
            pnl = -pnl
        fees = result.get("fee") or (leg["position_size_usd"] * get_executor(leg["exchange"]).fee_rate * 2)
        leg_pnl[leg["id"]] = {
            "exit_price": exit_price,
            "pnl_price_usd": round(pnl, 6),
            "fees_usd": round(fees, 6) if isinstance(fees, (int, float)) else 0.0,
        }

    for executor in executors.values():
        await _close_executor(executor)

    # Записываем в БД всё, что удалось закрыть (с полными данными: exit_price, pnl, fees)
    # Делаем ДО raise, чтобы данные не потерялись при частичном закрытии
    if leg_pnl:
        try:
            await db_close_pair(pair_id, leg_pnl)
        except Exception as db_err:
            logger.error(f"Не удалось записать закрытие в БД: {db_err}")

    if errors:
        # Часть ног не закрылась — алерт
        closed_names = [leg["exchange"] for leg, r in zip(legs, results) if not isinstance(r, Exception)]
        raise RuntimeError(
            f"Частичное закрытие пары {pair_id}!\n"
            f"✅ Закрыты: {', '.join(closed_names) if closed_names else 'нет'}\n"
            f"❌ Ошибки:\n" + "\n".join(errors) +
            "\n\n⚠️ Проверь позиции на биржах вручную!"
        )

    logger.info(f"Пара закрыта: {pair_id}")
    return {"pair_id": pair_id, "symbol": symbol}


async def scale_in_pair(pair_id: str, symbol: str, legs: list, add_size_usd: float) -> dict:
    """Увеличивает существующую пару на add_size_usd на каждой бирже."""
    if len(legs) < 2:
        raise RuntimeError("Не найдены обе ноги пары")

    executors = {}
    tasks = []

    for leg in legs:
        exch_name = leg["exchange"]
        executor = get_executor(exch_name)
        executors[exch_name] = executor
        is_long = (leg["direction"] == "LONG")
        tasks.append(executor.market_open(symbol, is_long, add_size_usd))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    oks = [not isinstance(r, Exception) for r in results]

    # Если одна нога упала — откатываем остальные
    if any(oks) and not all(oks):
        for i, (leg, result, ok) in enumerate(zip(legs, results, oks)):
            if ok:
                exch_name = leg["exchange"]
                executor = executors[exch_name]
                is_long = (leg["direction"] == "LONG")
                try:
                    await executor.market_close(symbol, result["size"], is_long)
                except Exception as e:
                    logger.error(f"Не удалось откатить {exch_name} при scale_in: {e}")
        errors = [str(r) for i, r in enumerate(results) if isinstance(r, Exception)]
        for executor in executors.values():
            await _close_executor(executor)
        raise RuntimeError(f"Scale in отменён:\n" + "\n".join(errors))

    if not any(oks):
        for executor in executors.values():
            await _close_executor(executor)
        errors = [f"{leg['exchange']}: {r}" for leg, r in zip(legs, results)]
        raise RuntimeError(f"Scale in: все ноги не открылись.\n" + "\n".join(errors))

    # Обновляем БД
    results_by_exchange = {}
    for leg, result in zip(legs, results):
        if not isinstance(result, Exception):
            results_by_exchange[leg["exchange"]] = {"size": result["size"], "price": result["price"]}

    await scale_pair_db_generic(legs=legs, results_by_exchange=results_by_exchange, add_size_usd=add_size_usd)

    for executor in executors.values():
        await _close_executor(executor)

    logger.info(f"Scale in выполнен: {pair_id} +${add_size_usd}")
    return {"pair_id": pair_id, "symbol": symbol, "added_usd": add_size_usd}


async def _rollback_leg(
    executor: BaseExchangeExecutor,
    symbol: str,
    open_result: dict,
    was_long: bool,
    opened_exchange: str,
    failed_exchange: str,
    failed_error,
):
    """Откатывает открытую ногу при сбое второй. Шлёт критичный алерт при неудаче."""
    try:
        await executor.market_close(symbol, open_result["size"], was_long)
        logger.info(f"{opened_exchange} автоматически закрыт после ошибки {failed_exchange}")
    except Exception as e:
        logger.error(f"Не удалось закрыть {opened_exchange} после ошибки {failed_exchange}: {e}")
        try:
            from bot.telegram import send_message
            await send_message(
                f"🚨 *КРИТИЧНО! НЕЗАХЕДЖИРОВАННАЯ ПОЗИЦИЯ!*\n\n"
                f"*{symbol}* — {opened_exchange} открылся, {failed_exchange} упал.\n"
                f"Автозакрытие {opened_exchange} тоже провалилось!\n\n"
                f"❌ {failed_exchange}: `{failed_error}`\n"
                f"❌ Автозакрытие: `{e}`\n\n"
                f"⚠️ *Немедленно закрой {symbol} на {opened_exchange} вручную!*"
            )
        except Exception:
            pass


async def _close_executor(executor: BaseExchangeExecutor):
    """Безопасно закрывает executor. Кешированные executor'ы не закрываем — они переиспользуются."""
    if executor in _executor_cache.values():
        return
    try:
        await executor.close()
    except Exception:
        pass
