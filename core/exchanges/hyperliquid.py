import asyncio
import logging

import httpx
import eth_account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants

from .base import BaseExchangeExecutor, CloseResult, ExchangeStatus, PositionResult

logger = logging.getLogger(__name__)

HL_BASE_URL = constants.MAINNET_API_URL


class HyperliquidExecutor(BaseExchangeExecutor):
    """Клиент для торговли на Hyperliquid."""

    name = "Hyperliquid"
    fee_rate = 0.0005  # 0.05% taker

    def __init__(self, private_key: str, wallet_address: str):
        self._private_key = private_key
        self._wallet_address = wallet_address
        self._exchange = None
        self._info = None
        self._meta = None

    def _get_exchange(self) -> Exchange:
        if self._exchange is None:
            account = eth_account.Account.from_key(self._private_key)
            self._exchange = Exchange(account, HL_BASE_URL, account_address=self._wallet_address)
        return self._exchange

    def _get_info(self) -> Info:
        if self._info is None:
            self._info = Info(HL_BASE_URL, skip_ws=True)
        return self._info

    async def _ensure_meta(self):
        if self._meta is None:
            info = self._get_info()
            self._meta = await asyncio.to_thread(info.meta)

    def _get_sz_decimals(self, symbol: str) -> int:
        if self._meta is None:
            raise RuntimeError("Meta не загружена, вызови _ensure_meta()")
        asset = next((a for a in self._meta["universe"] if a["name"] == symbol), None)
        if not asset:
            raise ValueError(f"Монета {symbol} не найдена на Hyperliquid")
        return asset["szDecimals"]

    async def get_mark_price(self, symbol: str) -> float:
        info = self._get_info()
        all_mids = await asyncio.to_thread(info.all_mids)
        price = float(all_mids.get(symbol, 0))
        if price == 0:
            raise ValueError(f"Не удалось получить цену {symbol} на Hyperliquid")
        return price

    async def market_open(self, symbol: str, is_long: bool, size_usd: float) -> dict:
        await self._ensure_meta()
        exchange = self._get_exchange()

        sz_decimals = self._get_sz_decimals(symbol)
        price = await self.get_mark_price(symbol)
        size = round(size_usd / price, sz_decimals)

        result = await asyncio.to_thread(exchange.market_open, symbol, is_long, size, None, 0.01)
        if result.get("status") != "ok":
            raise RuntimeError(f"Hyperliquid ошибка открытия: {result}")

        logger.info(f"Hyperliquid: открыт {'лонг' if is_long else 'шорт'} {symbol}, "
                    f"size={size}, price={price}")
        return {"size": size, "size_usd": size_usd, "price": price}

    async def market_open_by_qty(self, symbol: str, is_long: bool, quantity: float) -> dict:
        """Открывает позицию по точному количеству (для синхронизации ног)."""
        await self._ensure_meta()
        exchange = self._get_exchange()

        sz_decimals = self._get_sz_decimals(symbol)
        price = await self.get_mark_price(symbol)
        size = round(quantity, sz_decimals)

        result = await asyncio.to_thread(exchange.market_open, symbol, is_long, size, None, 0.01)
        if result.get("status") != "ok":
            raise RuntimeError(f"Hyperliquid ошибка открытия: {result}")

        logger.info(f"Hyperliquid: открыт {'лонг' if is_long else 'шорт'} {symbol}, "
                    f"size={size}, price={price}")
        return {"size": size, "size_usd": size * price, "price": price}

    async def market_close(self, symbol: str, size: float = 0, was_long: bool = True) -> CloseResult:
        try:
            await self._ensure_meta()
            exchange = self._get_exchange()
            price = await self.get_mark_price(symbol)

            pos_result = await self.get_positions()
            if pos_result.status == ExchangeStatus.API_ERROR:
                return CloseResult(status=ExchangeStatus.API_ERROR, error=pos_result.error)
            if pos_result.status == ExchangeStatus.UNKNOWN:
                return CloseResult(status=ExchangeStatus.UNKNOWN, error=pos_result.error)

            pos = next((p for p in pos_result.positions if p["symbol"] == symbol), None)
            if pos is None or abs(pos["quantity"]) == 0:
                logger.info(f"Hyperliquid: позиция {symbol} уже закрыта (подтверждено API)")
                return CloseResult(status=ExchangeStatus.ALREADY_CLOSED, price=price)

            if size > 0:
                sz_decimals = self._get_sz_decimals(symbol)
                close_size = round(size, sz_decimals)
                is_buy = not was_long
                order_type = {"limit": {"tif": "Ioc"}}
                result = await asyncio.to_thread(
                    exchange.order, symbol, is_buy, close_size,
                    price * 0.95 if is_buy else price * 1.05,
                    order_type, reduce_only=True
                )
                if result.get("status") != "ok":
                    return CloseResult(
                        status=ExchangeStatus.API_ERROR,
                        error=f"Hyperliquid ошибка закрытия {symbol}: {result}"
                    )
                logger.info(f"Hyperliquid: закрыта часть {symbol}, size={close_size}")
            else:
                result = await asyncio.to_thread(exchange.market_close, symbol)
                if result.get("status") != "ok":
                    return CloseResult(
                        status=ExchangeStatus.API_ERROR,
                        error=f"Hyperliquid ошибка закрытия {symbol}: {result}"
                    )
                logger.info(f"Hyperliquid: позиция {symbol} закрыта полностью")

            return CloseResult(status=ExchangeStatus.OK, price=price)

        except Exception as e:
            logger.error(f"Hyperliquid market_close {symbol} ошибка: {e}")
            return CloseResult(status=ExchangeStatus.API_ERROR, error=str(e))

    async def get_positions(self) -> PositionResult:
        try:
            info = self._get_info()
            user_state = await asyncio.to_thread(info.user_state, self._wallet_address)
            positions = []
            for pos in user_state.get("assetPositions", []):
                item = pos.get("position", {})
                symbol = item.get("coin", "")
                szi = float(item.get("szi", 0))
                if szi != 0:
                    positions.append({"symbol": symbol, "quantity": szi})
            return PositionResult(status=ExchangeStatus.OK, positions=positions)
        except Exception as e:
            logger.warning(f"Hyperliquid get_positions ошибка: {e}")
            return PositionResult(status=ExchangeStatus.API_ERROR, error=str(e))

    async def get_balance(self) -> float | None:
        try:
            total = 0.0
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post("https://api.hyperliquid.xyz/info", json={
                    "type": "clearinghouseState", "user": self._wallet_address
                })
                margin = r.json().get("marginSummary", {})
                total += float(margin.get("accountValue", 0))
                r2 = await c.post("https://api.hyperliquid.xyz/info", json={
                    "type": "spotClearinghouseState", "user": self._wallet_address
                })
                for b in r2.json().get("balances", []):
                    if b.get("coin") == "USDC":
                        total += float(b.get("total", 0))
            return total
        except Exception as e:
            logger.warning(f"Hyperliquid get_balance ошибка: {e}")
            return None
