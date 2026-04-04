import base64
import logging
import math
import time

import httpx

from .base import BaseExchangeExecutor

logger = logging.getLogger(__name__)


class BackpackExecutor(BaseExchangeExecutor):
    """Клиент для торговли на Backpack Exchange (Ed25519 аутентификация)."""

    name = "Backpack"
    fee_rate = 0.0004  # 0.04% taker
    BASE_URL = "https://api.backpack.exchange"

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self._markets: dict = {}
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            raw = base64.b64decode(api_secret)
            if len(raw) == 64:
                raw = raw[:32]
            self._private_key = Ed25519PrivateKey.from_private_bytes(raw)
        except ImportError:
            raise RuntimeError("Установи: pip install cryptography")

    def _sign(self, instruction: str, params: dict) -> dict:
        timestamp = int(time.time() * 1000)
        window = 30000

        def _val(v):
            if isinstance(v, bool):
                return "true" if v else "false"
            return v

        sorted_body = "&".join(f"{k}={_val(v)}" for k, v in sorted(params.items()))
        if sorted_body:
            message = f"instruction={instruction}&{sorted_body}&timestamp={timestamp}&window={window}"
        else:
            message = f"instruction={instruction}&timestamp={timestamp}&window={window}"
        signature = self._private_key.sign(message.encode("utf-8"))
        return {
            "X-API-Key": self.api_key,
            "X-Signature": base64.b64encode(signature).decode(),
            "X-Timestamp": str(timestamp),
            "X-Window": str(window),
            "Content-Type": "application/json; charset=utf-8",
        }

    def _bp_symbol(self, symbol: str) -> str:
        return f"{symbol.upper()}_USDC_PERP"

    async def _ensure_markets(self):
        if self._markets:
            return
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self.BASE_URL}/api/v1/markets")
            data = resp.json()
        for m in data:
            if m.get("marketType") != "PERP":
                continue
            sym = m.get("baseSymbol", "").upper()
            step = float(m["filters"]["quantity"]["stepSize"])
            self._markets[sym] = {"step_size": step}

    def _round_qty(self, symbol: str, qty: float) -> float:
        step = self._markets.get(symbol.upper(), {}).get("step_size", 0.000001)
        rounded = math.floor(qty / step) * step
        decimals = max(0, -int(math.floor(math.log10(step)))) if step < 1 else 0
        return round(rounded, decimals)

    async def get_mark_price(self, symbol: str) -> float:
        bp_symbol = self._bp_symbol(symbol)
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.BASE_URL}/api/v1/markPrices",
                params={"marketType": "PERP"},
            )
            data = resp.json()
        for item in data:
            if item.get("symbol") == bp_symbol:
                return float(item.get("markPrice") or item.get("price") or 0)
        raise ValueError(f"Цена {symbol} не найдена на Backpack")

    async def market_open(self, symbol: str, is_long: bool, size_usd: float) -> dict:
        await self._ensure_markets()
        bp_symbol = self._bp_symbol(symbol)
        price = await self.get_mark_price(symbol)
        quantity = self._round_qty(symbol, size_usd / price)

        side = "Bid" if is_long else "Ask"
        params = {
            "orderType": "Market",
            "quantity": str(quantity),
            "side": side,
            "symbol": bp_symbol,
        }
        headers = self._sign("orderExecute", params)

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.BASE_URL}/api/v1/order",
                json=params,
                headers=headers,
            )
            result = resp.json()

        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Backpack ошибка открытия: {result}")

        executed_qty = float(result.get("executedQuantity") or quantity)
        executed_price = float(result.get("avgPrice") or price)
        logger.info(f"Backpack: открыт {'лонг' if is_long else 'шорт'} {symbol}, "
                    f"qty={executed_qty}, price={executed_price}")
        return {
            "order_id": result.get("id"),
            "size": executed_qty,
            "size_usd": size_usd,
            "price": executed_price,
        }

    async def market_open_by_qty(self, symbol: str, is_long: bool, quantity: float) -> dict:
        """Открывает позицию по точному количеству (для синхронизации ног)."""
        await self._ensure_markets()
        bp_symbol = self._bp_symbol(symbol)
        price = await self.get_mark_price(symbol)
        quantity = self._round_qty(symbol, quantity)

        side = "Bid" if is_long else "Ask"
        params = {
            "orderType": "Market",
            "quantity": str(quantity),
            "side": side,
            "symbol": bp_symbol,
        }
        headers = self._sign("orderExecute", params)

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.BASE_URL}/api/v1/order",
                json=params,
                headers=headers,
            )
            result = resp.json()

        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Backpack ошибка открытия: {result}")

        executed_qty = float(result.get("executedQuantity") or quantity)
        executed_price = float(result.get("avgPrice") or price)
        logger.info(f"Backpack: открыт {'лонг' if is_long else 'шорт'} {symbol}, "
                    f"qty={executed_qty}, price={executed_price}")
        return {
            "order_id": result.get("id"),
            "size": executed_qty,
            "size_usd": executed_qty * executed_price,
            "price": executed_price,
        }

    async def market_close(self, symbol: str, size: float = 0, was_long: bool = True) -> dict:
        bp_symbol = self._bp_symbol(symbol)
        mark_price = await self.get_mark_price(symbol)

        if size > 0:
            # Размер известен — закрываем по нему
            side = "Ask" if was_long else "Bid"
            qty = size
        else:
            raw_positions = await self._get_raw_positions()
            if raw_positions is None:
                raise RuntimeError(f"Backpack: не удалось получить позиции для закрытия {symbol}")
            pos = next((p for p in raw_positions if p.get("symbol") == bp_symbol), None)
            if not pos:
                logger.info(f"Backpack: позиция {symbol} не найдена — считаем закрытой")
                return {"symbol": symbol, "closed_qty": 0, "price": 0}
            qty = float(pos.get("netQuantity") or pos.get("quantity") or 0)
            if qty == 0:
                return {"symbol": symbol, "closed_qty": 0, "price": 0}
            side = "Ask" if qty > 0 else "Bid"

        params = {
            "orderType": "Market",
            "quantity": f"{abs(qty):g}",
            "reduceOnly": True,
            "side": side,
            "symbol": bp_symbol,
        }
        headers = self._sign("orderExecute", params)

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.BASE_URL}/api/v1/order",
                json=params,
                headers=headers,
            )
            result = resp.json()

        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Backpack ошибка закрытия: {result}")

        exit_price = float(result.get("avgPrice") or result.get("price") or mark_price)
        fees_paid = float(result.get("fee") or 0)
        logger.info(f"Backpack: закрыта позиция {symbol}, qty={abs(qty)}, price={exit_price}")
        return {"symbol": symbol, "closed_qty": abs(qty), "price": exit_price, "fee": fees_paid}

    async def _get_raw_positions(self) -> list:
        """Возвращает сырые позиции с API (без нормализации)."""
        params = {}
        headers = self._sign("positionQuery", params)
        get_headers = {k: v for k, v in headers.items() if k != "Content-Type"}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.BASE_URL}/api/v1/position",
                headers=get_headers,
            )
            if resp.status_code != 200:
                logger.error(f"Backpack positions error: {resp.text}")
                return []
            return resp.json()

    async def get_positions(self) -> list[dict] | None:
        raw = await self._get_raw_positions()
        result = []
        for pos in raw:
            sym = pos.get("symbol", "").replace("_USDC_PERP", "").upper()
            qty = float(pos.get("netQuantity") or pos.get("quantity") or 0)
            if qty != 0:
                result.append({"symbol": sym, "quantity": qty})
        return result

    async def get_balance(self) -> float | None:
        params = {}
        headers = self._sign("balanceQuery", params)
        get_headers = {k: v for k, v in headers.items() if k != "Content-Type"}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.BASE_URL}/api/v1/capital",
                headers=get_headers,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Backpack balance error: {resp.text}")
            data = resp.json()
        if isinstance(data, dict) and "USDC" in data:
            return float(data["USDC"].get("available", 0) or 0)
        return 0.0

    async def get_liquidation_info(self, symbol: str) -> dict | None:
        raw = await self._get_raw_positions()
        bp_symbol = self._bp_symbol(symbol)
        pos = next((p for p in raw if p.get("symbol") == bp_symbol), None)
        if not pos:
            return None
        try:
            liq_price = float(pos.get("liquidationPrice") or 0)
            mark_price = float(pos.get("markPrice") or 0)
            leverage = pos.get("leverage", "?")
            if liq_price > 0 and mark_price > 0:
                return {
                    "liquidation_price": liq_price,
                    "mark_price": mark_price,
                    "leverage": leverage,
                }
        except (ValueError, TypeError):
            pass
        return None
