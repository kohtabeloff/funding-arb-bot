"""
GRVT (Gravity) executor — использует grvt-pysdk (async).
Аутентификация: API key + EIP-712 подпись ордеров через ETH private key.
SDK: pip install grvt-pysdk
"""
import logging
from decimal import Decimal

from .base import BaseExchangeExecutor

logger = logging.getLogger(__name__)


class GRVTExecutor(BaseExchangeExecutor):
    """Клиент для торговли на GRVT через grvt-pysdk."""

    name = "GRVT"
    fee_rate = 0.0003  # ~0.03% taker (maker получает ребейт -0.01%)

    def __init__(self, api_key: str, private_key: str, trading_account_id: str = ""):
        self._api_key = api_key
        self._private_key = private_key
        self._trading_account_id = trading_account_id
        self._api = None
        self._markets_loaded = False

    async def _get_api(self):
        """Ленивая инициализация SDK клиента."""
        if self._api is None:
            try:
                from pysdk.grvt_ccxt_pro import GrvtCcxtPro
                from pysdk.grvt_ccxt_env import GrvtEnv

                params = {
                    "api_key": self._api_key,
                    "private_key": self._private_key,
                    "trading_account_id": self._trading_account_id,
                }
                self._api = GrvtCcxtPro(GrvtEnv.PROD, logger, parameters=params)
            except ImportError:
                raise RuntimeError("grvt-pysdk не установлен: pip install grvt-pysdk")
        if not self._markets_loaded:
            await self._api.load_markets()
            self._markets_loaded = True
        return self._api

    def _to_instrument(self, symbol: str) -> str:
        """BTC → BTC_USDT_Perp"""
        return f"{symbol.upper()}_USDT_Perp"

    async def _get_size_precision(self, instrument: str) -> int:
        """Возвращает кол-во знаков после запятой для округления размера ордера.
        Берёт min_size инструмента и считает количество значащих десятичных знаков."""
        api = await self._get_api()
        market = api.markets.get(instrument, {})
        min_size = market.get("min_size")
        if min_size:
            # min_size=0.1 → 1, min_size=0.01 → 2, min_size=1 → 0
            min_size_str = str(min_size)
            if '.' in min_size_str:
                return len(min_size_str.rstrip('0').split('.')[1])
            return 0
        return int(market.get("base_decimals", 9))

    async def get_mark_price(self, symbol: str) -> float:
        api = await self._get_api()
        instrument = self._to_instrument(symbol)
        ticker = await api.fetch_mini_ticker(instrument)
        price = float(ticker.get("mark_price") or ticker.get("last") or 0)
        if price == 0:
            raise ValueError(f"Не удалось получить цену {symbol} на GRVT")
        return price

    async def market_open(self, symbol: str, is_long: bool, size_usd: float) -> dict:
        api = await self._get_api()
        instrument = self._to_instrument(symbol)

        price = await self.get_mark_price(symbol)
        size = size_usd / price

        # Округляем до точности инструмента (base_decimals), иначе подпись не совпадёт
        decimals = await self._get_size_precision(instrument)
        size = round(size, decimals)

        side = "buy" if is_long else "sell"

        logger.info(f"GRVT: {'лонг' if is_long else 'шорт'} {symbol}, ${size_usd}, size={size:.{decimals}f}")

        order = await api.create_order(
            symbol=instrument,
            order_type="market",
            side=side,
            amount=Decimal(str(size)),
        )

        if not order:
            raise RuntimeError(f"GRVT: ордер {symbol} отклонён биржей (пустой ответ от API)")

        # Парсим результат
        filled_size = float(order.get("filled") or order.get("amount") or size)
        filled_price = float(order.get("average") or order.get("price") or price)

        logger.info(f"GRVT: ордер исполнен {symbol}, size={filled_size}, price={filled_price}")
        return {
            "order_id": order.get("id"),
            "size": filled_size,
            "size_usd": size_usd,
            "price": filled_price,
        }

    async def market_open_by_qty(self, symbol: str, is_long: bool, quantity: float) -> dict:
        """Открывает позицию по точному количеству (для синхронизации ног)."""
        api = await self._get_api()
        instrument = self._to_instrument(symbol)
        price = await self.get_mark_price(symbol)
        side = "buy" if is_long else "sell"

        # Округляем до точности инструмента (base_decimals), иначе подпись не совпадёт
        decimals = await self._get_size_precision(instrument)
        quantity = round(quantity, decimals)

        logger.info(f"GRVT: {'лонг' if is_long else 'шорт'} {symbol}, qty={quantity:.{decimals}f}")

        order = await api.create_order(
            symbol=instrument,
            order_type="market",
            side=side,
            amount=Decimal(str(quantity)),
        )

        if not order:
            raise RuntimeError(f"GRVT: ордер {symbol} отклонён биржей (пустой ответ от API)")

        filled_size = float(order.get("filled") or order.get("amount") or quantity)
        filled_price = float(order.get("average") or order.get("price") or price)

        logger.info(f"GRVT: ордер исполнен {symbol}, size={filled_size}, price={filled_price}")
        return {
            "order_id": order.get("id"),
            "size": filled_size,
            "size_usd": filled_size * filled_price,
            "price": filled_price,
        }

    async def market_close(self, symbol: str, size: float = 0, was_long: bool = True) -> dict:
        api = await self._get_api()
        instrument = self._to_instrument(symbol)

        price = await self.get_mark_price(symbol)

        # Закрываем: если был лонг → sell, если шорт → buy
        side = "sell" if was_long else "buy"
        close_size = size if size > 0 else abs((await self._get_position_size(symbol)) or 0)

        if close_size == 0:
            logger.info(f"GRVT: позиция {symbol} уже закрыта")
            return {"symbol": symbol, "price": price, "fee": 0}

        # Округляем до точности инструмента
        decimals = await self._get_size_precision(instrument)
        close_size = round(close_size, decimals)

        logger.info(f"GRVT: закрытие {symbol}, size={close_size}")

        order = await api.create_order(
            symbol=instrument,
            order_type="market",
            side=side,
            amount=Decimal(str(close_size)),
            params={"reduce_only": True},
        )

        if not order:
            raise RuntimeError(f"GRVT: закрытие {symbol} отклонено биржей (пустой ответ от API)")

        exit_price = float(order.get("average") or order.get("price") or price)
        logger.info(f"GRVT: позиция {symbol} закрыта, price={exit_price}")
        return {"symbol": symbol, "price": exit_price, "fee": 0}

    async def _get_position_size(self, symbol: str) -> float | None:
        """Возвращает размер открытой позиции (+ лонг, - шорт)."""
        positions = await self.get_positions()
        if positions is None:
            return None
        for pos in positions:
            if pos["symbol"] == symbol.upper():
                return pos["quantity"]
        return 0

    async def get_positions(self) -> list[dict] | None:
        try:
            api = await self._get_api()
            raw = await api.fetch_positions()

            # SDK может молча вернуть [] при ошибке авторизации — retry один раз
            if not raw:
                import asyncio
                await asyncio.sleep(2)
                # Сбрасываем SDK чтобы переавторизовался
                self._api = None
                self._markets_loaded = False
                api = await self._get_api()
                raw = await api.fetch_positions()
                if not raw:
                    logger.warning("GRVT get_positions: пустой результат после retry — возможно ошибка авторизации")
                    return None

            positions = []
            for pos in raw:
                symbol_raw = pos.get("instrument") or pos.get("symbol") or ""
                # BTC_USDT_Perp → BTC
                symbol = symbol_raw.split("_")[0].upper() if "_" in symbol_raw else symbol_raw
                # GRVT возвращает "size" со знаком: минус = short, плюс = long
                qty = float(pos.get("size") or pos.get("contracts") or pos.get("amount") or 0)
                if qty != 0:
                    positions.append({"symbol": symbol, "quantity": qty})
            return positions
        except Exception as e:
            logger.warning(f"GRVT get_positions ошибка: {e}")
            return None

    async def get_balance(self) -> float | None:
        try:
            api = await self._get_api()
            balance = await api.fetch_balance()
            # Ищем USDT баланс
            if isinstance(balance, dict):
                usdt = balance.get("USDT", {})
                if isinstance(usdt, dict):
                    val = usdt.get("total") or usdt.get("free") or usdt.get("available")
                    if val:
                        return float(val)
                total = balance.get("total", {})
                if isinstance(total, dict):
                    val = total.get("USDT")
                    if val:
                        return float(val)
            return None
        except Exception as e:
            logger.warning(f"GRVT get_balance ошибка: {e}")
            return None

    async def close(self):
        if self._api:
            try:
                await self._api.close()
            except Exception:
                pass
            self._api = None
            self._markets_loaded = False
