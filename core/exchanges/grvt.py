"""
GRVT (Gravity) executor — использует grvt-pysdk (async).
Аутентификация: API key + EIP-712 подпись ордеров через ETH private key.
SDK: pip install grvt-pysdk
"""
import asyncio
import logging
from decimal import Decimal

from .base import BaseExchangeExecutor, CloseResult, ExchangeStatus, PositionResult

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
        api = await self._get_api()
        market = api.markets.get(instrument, {})
        min_size = market.get("min_size")
        if min_size:
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
        decimals = await self._get_size_precision(instrument)
        size = round(size, decimals)
        side = "buy" if is_long else "sell"

        logger.info(f"GRVT: {'лонг' if is_long else 'шорт'} {symbol}, ${size_usd}, size={size:.{decimals}f}")

        order = await api.create_order(
            symbol=instrument, order_type="market", side=side, amount=Decimal(str(size)),
        )

        if not order:
            await asyncio.sleep(2)
            pos_result = await self.get_positions()
            if pos_result.status == ExchangeStatus.OK:
                found = next((p for p in pos_result.positions if p["symbol"] == symbol.upper()), None)
                if found and abs(found["quantity"]) > 0:
                    logger.warning(f"GRVT: ордер {symbol} исполнен, но ответ был пустым")
                    size = abs(found["quantity"])
                    order = {"filled": size, "amount": size, "average": price, "price": price}
                else:
                    logger.warning(f"GRVT: пустой ответ при открытии {symbol}, сброс сессии и retry...")
                    self._api = None
                    self._markets_loaded = False
                    api = await self._get_api()
                    order = await api.create_order(
                        symbol=instrument, order_type="market", side=side, amount=Decimal(str(size)),
                    )
                    if not order:
                        raise RuntimeError(f"GRVT: ордер {symbol} отклонён биржей (пустой ответ от API)")
            else:
                raise RuntimeError(f"GRVT: не удалось проверить статус ордера {symbol}: {pos_result.error}")

        filled_size = float(order.get("filled") or order.get("amount") or size) if order else size
        filled_price = float(order.get("average") or order.get("price") or price) if order else price

        logger.info(f"GRVT: ордер исполнен {symbol}, size={filled_size}, price={filled_price}")
        return {"order_id": order.get("id") if order else None, "size": filled_size, "size_usd": size_usd, "price": filled_price}

    async def market_open_by_qty(self, symbol: str, is_long: bool, quantity: float) -> dict:
        """Открывает позицию по точному количеству (для синхронизации ног)."""
        api = await self._get_api()
        instrument = self._to_instrument(symbol)
        price = await self.get_mark_price(symbol)
        side = "buy" if is_long else "sell"
        decimals = await self._get_size_precision(instrument)
        quantity = round(quantity, decimals)

        logger.info(f"GRVT: {'лонг' if is_long else 'шорт'} {symbol}, qty={quantity:.{decimals}f}")

        order = await api.create_order(
            symbol=instrument, order_type="market", side=side, amount=Decimal(str(quantity)),
        )

        if not order:
            await asyncio.sleep(2)
            pos_result = await self.get_positions()
            if pos_result.status == ExchangeStatus.OK:
                found = next((p for p in pos_result.positions if p["symbol"] == symbol.upper()), None)
                if found and abs(found["quantity"]) > 0:
                    logger.warning(f"GRVT: ордер qty {symbol} исполнен, но ответ был пустым")
                    order = {"filled": quantity, "amount": quantity, "average": price, "price": price}
                else:
                    logger.warning(f"GRVT: пустой ответ qty {symbol}, сброс сессии и retry...")
                    self._api = None
                    self._markets_loaded = False
                    api = await self._get_api()
                    order = await api.create_order(
                        symbol=instrument, order_type="market", side=side, amount=Decimal(str(quantity)),
                    )
                    if not order:
                        raise RuntimeError(f"GRVT: ордер {symbol} отклонён биржей (пустой ответ от API)")
            else:
                raise RuntimeError(f"GRVT: не удалось проверить статус ордера {symbol}: {pos_result.error}")

        filled_size = float(order.get("filled") or order.get("amount") or quantity) if order else quantity
        filled_price = float(order.get("average") or order.get("price") or price) if order else price

        logger.info(f"GRVT: ордер исполнен {symbol}, size={filled_size}, price={filled_price}")
        return {"order_id": order.get("id") if order else None, "size": filled_size, "size_usd": filled_size * filled_price, "price": filled_price}

    async def market_close(self, symbol: str, size: float = 0, was_long: bool = True) -> CloseResult:
        try:
            api = await self._get_api()
            instrument = self._to_instrument(symbol)
            price = await self.get_mark_price(symbol)

            pos_result = await self.get_positions()
            if pos_result.status == ExchangeStatus.API_ERROR:
                return CloseResult(status=ExchangeStatus.API_ERROR, error=pos_result.error)
            if pos_result.status == ExchangeStatus.UNKNOWN:
                return CloseResult(status=ExchangeStatus.UNKNOWN, error=pos_result.error)

            found = next((p for p in pos_result.positions if p["symbol"] == symbol.upper()), None)
            real_size = abs(found["quantity"]) if found else 0

            if real_size == 0:
                logger.info(f"GRVT: позиция {symbol} уже закрыта (подтверждено API)")
                return CloseResult(status=ExchangeStatus.ALREADY_CLOSED, price=price)

            side = "sell" if was_long else "buy"
            close_size = size if size > 0 else real_size
            decimals = await self._get_size_precision(instrument)
            close_size = round(close_size, decimals)

            logger.info(f"GRVT: закрытие {symbol}, size={close_size}")

            order = await api.create_order(
                symbol=instrument, order_type="market", side=side, amount=Decimal(str(close_size)),
            )

            if not order:
                logger.warning(f"GRVT: пустой ответ при закрытии {symbol}, retry через 2с...")
                await asyncio.sleep(2)
                order = await api.create_order(
                    symbol=instrument, order_type="market", side=side, amount=Decimal(str(close_size)),
                )

            if not order:
                return CloseResult(status=ExchangeStatus.UNKNOWN, error=f"GRVT: пустой ответ при закрытии {symbol}")

            exit_price = float(order.get("average") or order.get("price") or price)
            logger.info(f"GRVT: позиция {symbol} закрыта, price={exit_price}")
            return CloseResult(status=ExchangeStatus.OK, price=exit_price, fee=0)

        except Exception as e:
            logger.error(f"GRVT market_close {symbol} ошибка: {e}")
            return CloseResult(status=ExchangeStatus.API_ERROR, error=str(e))

    async def get_positions(self) -> PositionResult:
        try:
            api = await self._get_api()
            raw = await api.fetch_positions()

            if not raw:
                await asyncio.sleep(2)
                self._api = None
                self._markets_loaded = False
                api = await self._get_api()
                raw = await api.fetch_positions()
                if not raw:
                    logger.warning("GRVT get_positions: пустой результат после retry — возможно ошибка авторизации")
                    return PositionResult(status=ExchangeStatus.API_ERROR, error="пустой ответ после retry")

            positions = []
            for pos in raw:
                symbol_raw = pos.get("instrument") or pos.get("symbol") or ""
                sym = symbol_raw.split("_")[0].upper() if "_" in symbol_raw else symbol_raw
                qty = float(pos.get("size") or pos.get("contracts") or pos.get("amount") or 0)
                if qty != 0:
                    positions.append({"symbol": sym, "quantity": qty})
            return PositionResult(status=ExchangeStatus.OK, positions=positions)

        except Exception as e:
            logger.warning(f"GRVT get_positions ошибка: {e}")
            return PositionResult(status=ExchangeStatus.API_ERROR, error=str(e))

    async def _get_position_size(self, symbol: str) -> float | None:
        """Вспомогательный метод для market_open."""
        result = await self.get_positions()
        if result.status != ExchangeStatus.OK:
            return None
        for pos in result.positions:
            if pos["symbol"] == symbol.upper():
                return pos["quantity"]
        return 0

    async def get_balance(self) -> float | None:
        try:
            api = await self._get_api()
            balance = await api.fetch_balance()
            if not balance:
                await asyncio.sleep(2)
                self._api = None
                self._markets_loaded = False
                api = await self._get_api()
                balance = await api.fetch_balance()
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
