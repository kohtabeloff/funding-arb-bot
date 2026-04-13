"""
Aster DEX executor — API стиль Binance Futures (HMAC SHA256 аутентификация).
SDK: pip install aster-connector-python
"""
import asyncio
import hashlib
import hmac
import logging
import math
import time

import httpx

from .base import BaseExchangeExecutor

logger = logging.getLogger(__name__)

BASE_URL = "https://fapi.asterdex.com"


class AsterExecutor(BaseExchangeExecutor):
    """Клиент для торговли на Aster DEX (Binance-style API)."""

    name = "Aster"
    fee_rate = 0.0004  # ~0.04% taker

    def __init__(self, api_key: str, api_secret: str):
        self._api_key = api_key
        self._api_secret = api_secret
        self._exchange_info: dict = {}  # symbol → {stepSize, tickSize, ...}

    def _sign(self, params: dict) -> str:
        """HMAC SHA256 подпись параметров запроса."""
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return hmac.new(
            self._api_secret.encode(),
            query.encode(),
            hashlib.sha256,
        ).hexdigest()

    def _headers(self) -> dict:
        return {"X-MBX-APIKEY": self._api_key}

    def _aster_symbol(self, symbol: str) -> str:
        """BTC → BTCUSDT"""
        return f"{symbol.upper()}USDT"

    async def _ensure_exchange_info(self):
        """Загружает фильтры символов (stepSize, tickSize)."""
        if self._exchange_info:
            return
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{BASE_URL}/fapi/v1/exchangeInfo")
                data = resp.json()
            for s in data.get("symbols", []):
                sym = s.get("symbol", "")
                filters = {f["filterType"]: f for f in s.get("filters", [])}
                lot_size = filters.get("LOT_SIZE", {})
                self._exchange_info[sym] = {
                    "step_size": float(lot_size.get("stepSize") or 0.001),
                    "min_qty": float(lot_size.get("minQty") or 0.001),
                }
        except Exception as e:
            logger.warning(f"Aster: не удалось загрузить exchangeInfo: {e}")

    def _round_qty(self, aster_symbol: str, qty: float) -> float:
        """Округляет количество до stepSize."""
        info = self._exchange_info.get(aster_symbol, {})
        step = info.get("step_size", 0.001)
        rounded = math.floor(qty / step) * step
        decimals = max(0, -int(math.floor(math.log10(step)))) if step < 1 else 0
        return round(rounded, decimals)

    async def get_mark_price(self, symbol: str) -> float:
        aster_sym = self._aster_symbol(symbol)
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BASE_URL}/fapi/v1/premiumIndex",
                params={"symbol": aster_sym},
            )
            data = resp.json()

        # Может вернуть объект или список
        if isinstance(data, list):
            data = data[0] if data else {}

        price = float(data.get("markPrice") or 0)
        if price == 0:
            raise ValueError(f"Не удалось получить цену {symbol} на Aster")
        return price

    async def market_open(self, symbol: str, is_long: bool, size_usd: float) -> dict:
        await self._ensure_exchange_info()
        aster_sym = self._aster_symbol(symbol)
        price = await self.get_mark_price(symbol)
        quantity = self._round_qty(aster_sym, size_usd / price)

        min_qty = self._exchange_info.get(aster_sym, {}).get("min_qty", 0.001)
        if quantity < min_qty:
            raise ValueError(f"Aster: размер {quantity} меньше минимума {min_qty} для {symbol}")

        side = "BUY" if is_long else "SELL"
        params = {
            "symbol": aster_sym,
            "side": side,
            "type": "MARKET",
            "quantity": str(quantity),
            "timestamp": str(int(time.time() * 1000)),
        }
        params["signature"] = self._sign(params)

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BASE_URL}/fapi/v1/order",
                params=params,
                headers=self._headers(),
            )
            result = resp.json()

        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Aster ошибка открытия: {result}")

        executed_qty = float(result.get("executedQty") or 0)
        avg_price = float(result.get("avgPrice") or 0)

        # Aster может вернуть 0 — ордер ещё не исполнен, дозапрашиваем
        if executed_qty <= 0 or avg_price <= 0:
            order_id = result.get("orderId")
            if order_id:
                await asyncio.sleep(1)
                executed_qty, avg_price = await self._query_order(aster_sym, order_id)
            if executed_qty <= 0:
                executed_qty = quantity
            if avg_price <= 0:
                avg_price = price

        logger.info(f"Aster: открыт {'лонг' if is_long else 'шорт'} {symbol}, "
                    f"qty={executed_qty}, price={avg_price}")
        return {
            "order_id": result.get("orderId"),
            "size": executed_qty,
            "size_usd": size_usd,
            "price": avg_price,
        }

    async def market_open_by_qty(self, symbol: str, is_long: bool, quantity: float) -> dict:
        """Открывает позицию по точному количеству (для синхронизации ног)."""
        await self._ensure_exchange_info()
        aster_sym = self._aster_symbol(symbol)
        price = await self.get_mark_price(symbol)
        quantity = self._round_qty(aster_sym, quantity)

        min_qty = self._exchange_info.get(aster_sym, {}).get("min_qty", 0.001)
        if quantity < min_qty:
            raise ValueError(f"Aster: размер {quantity} меньше минимума {min_qty} для {symbol}")

        side = "BUY" if is_long else "SELL"
        params = {
            "symbol": aster_sym,
            "side": side,
            "type": "MARKET",
            "quantity": str(quantity),
            "timestamp": str(int(time.time() * 1000)),
        }
        params["signature"] = self._sign(params)

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BASE_URL}/fapi/v1/order",
                params=params,
                headers=self._headers(),
            )
            result = resp.json()

        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Aster ошибка открытия: {result}")

        executed_qty = float(result.get("executedQty") or 0)
        avg_price = float(result.get("avgPrice") or 0)

        if executed_qty <= 0 or avg_price <= 0:
            order_id = result.get("orderId")
            if order_id:
                await asyncio.sleep(1)
                executed_qty, avg_price = await self._query_order(aster_sym, order_id)
            if executed_qty <= 0:
                executed_qty = quantity
            if avg_price <= 0:
                avg_price = price

        logger.info(f"Aster: открыт {'лонг' if is_long else 'шорт'} {symbol}, "
                    f"qty={executed_qty}, price={avg_price}")
        return {
            "order_id": result.get("orderId"),
            "size": executed_qty,
            "size_usd": executed_qty * avg_price,
            "price": avg_price,
        }

    async def _query_order(self, aster_sym: str, order_id) -> tuple[float, float]:
        """Запрашивает статус ордера чтобы получить fill."""
        try:
            params = {
                "symbol": aster_sym,
                "orderId": str(order_id),
                "timestamp": str(int(time.time() * 1000)),
            }
            params["signature"] = self._sign(params)
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{BASE_URL}/fapi/v1/order",
                    params=params,
                    headers=self._headers(),
                )
                data = resp.json()
            return float(data.get("executedQty") or 0), float(data.get("avgPrice") or 0)
        except Exception as e:
            logger.warning(f"Aster _query_order ошибка: {e}")
            return 0.0, 0.0

    async def market_close(self, symbol: str, size: float = 0, was_long: bool = True) -> dict:
        await self._ensure_exchange_info()
        aster_sym = self._aster_symbol(symbol)
        price = await self.get_mark_price(symbol)

        # Всегда проверяем реальную позицию на бирже перед закрытием
        positions = await self.get_positions()
        pos = next((p for p in positions if p["symbol"] == symbol.upper()), None) if positions else None
        real_size = abs(pos["quantity"]) if pos else 0
        if real_size == 0:
            logger.info(f"Aster: позиция {symbol} уже закрыта на бирже")
            return {"symbol": symbol, "price": price, "fee": 0}

        # Берём минимум из размера в БД и реального — чтобы reduceOnly не падал
        if size <= 0:
            size = real_size
        else:
            size = min(size, real_size)

        quantity = self._round_qty(aster_sym, size)
        side = "SELL" if was_long else "BUY"

        params = {
            "symbol": aster_sym,
            "side": side,
            "type": "MARKET",
            "quantity": str(quantity),
            "reduceOnly": "true",
            "timestamp": str(int(time.time() * 1000)),
        }
        params["signature"] = self._sign(params)

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BASE_URL}/fapi/v1/order",
                params=params,
                headers=self._headers(),
            )
            result = resp.json()

        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Aster ошибка закрытия: {result}")

        exit_price = float(result.get("avgPrice") or price)
        fees = float(result.get("commission") or 0)
        logger.info(f"Aster: закрыта позиция {symbol}, qty={quantity}, price={exit_price}")
        return {"symbol": symbol, "price": exit_price, "fee": fees}

    async def get_positions(self) -> list[dict] | None:
        try:
            params = {
                "timestamp": str(int(time.time() * 1000)),
            }
            params["signature"] = self._sign(params)

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{BASE_URL}/fapi/v2/positionRisk",
                    params=params,
                    headers=self._headers(),
                )
                if resp.status_code != 200:
                    logger.warning(f"Aster positions error: {resp.text[:200]}")
                    return None
                data = resp.json()

            positions = []
            for pos in data:
                qty = float(pos.get("positionAmt") or 0)
                if qty == 0:
                    continue
                raw_symbol = pos.get("symbol", "")
                symbol = raw_symbol.replace("USDT", "").replace("USDC", "")
                positions.append({"symbol": symbol, "quantity": qty})
            return positions
        except Exception as e:
            logger.warning(f"Aster get_positions ошибка: {e}")
            return None

    async def get_balance(self) -> float | None:
        try:
            params = {
                "timestamp": str(int(time.time() * 1000)),
            }
            params["signature"] = self._sign(params)

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{BASE_URL}/fapi/v2/balance",
                    params=params,
                    headers=self._headers(),
                )
                if resp.status_code != 200:
                    return None
                data = resp.json()

            for item in data:
                asset = item.get("asset", "")
                if asset in ("USDT", "USDC"):
                    return float(item.get("balance") or item.get("availableBalance") or 0)
            return 0.0
        except Exception as e:
            logger.warning(f"Aster get_balance ошибка: {e}")
            return None

    async def get_liquidation_info(self, symbol: str) -> dict | None:
        """Получает ликвидационную цену из positionRisk."""
        try:
            aster_sym = self._aster_symbol(symbol)
            params = {
                "symbol": aster_sym,
                "timestamp": str(int(time.time() * 1000)),
            }
            params["signature"] = self._sign(params)

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{BASE_URL}/fapi/v2/positionRisk",
                    params=params,
                    headers=self._headers(),
                )
                if resp.status_code != 200:
                    return None
                data = resp.json()

            for pos in data:
                if pos.get("symbol") == aster_sym:
                    liq_price = float(pos.get("liquidationPrice") or 0)
                    mark_price = float(pos.get("markPrice") or 0)
                    leverage = pos.get("leverage", "?")
                    if liq_price > 0 and mark_price > 0:
                        return {
                            "liquidation_price": liq_price,
                            "mark_price": mark_price,
                            "leverage": leverage,
                        }
            return None
        except Exception as e:
            logger.debug(f"Aster liquidation info ошибка: {e}")
            return None
