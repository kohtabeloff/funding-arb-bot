import logging
import time

import httpx

from .base import BaseExchangeExecutor, CloseResult, ExchangeStatus, PositionResult

logger = logging.getLogger(__name__)

LIGHTER_BASE_URL = "https://mainnet.zklighter.elliot.ai"


class LighterExecutor(BaseExchangeExecutor):
    """Клиент для торговли на Lighter (ZK order book DEX)."""

    name = "Lighter"
    fee_rate = 0.0  # 0% комиссия

    def __init__(self, api_private_key: str, api_key_index: int, account_index: int):
        self._api_private_key = api_private_key
        self._api_key_index = api_key_index
        self._account_index = account_index
        self._signer = None
        self._markets: dict = {}

    def _get_signer(self):
        if self._signer is None:
            try:
                import lighter
                self._signer = lighter.SignerClient(
                    url=LIGHTER_BASE_URL,
                    api_private_keys={self._api_key_index: self._api_private_key},
                    account_index=self._account_index,
                )
            except ImportError:
                raise RuntimeError("lighter-sdk не установлен: pip install lighter-sdk")
        return self._signer

    async def _ensure_markets(self):
        if self._markets:
            return
        signer = self._get_signer()
        result = await signer.order_api.order_books()
        for ob in (result.order_books or []):
            self._markets[ob.symbol.upper()] = ob
        logger.info(f"Lighter: загружено {len(self._markets)} рынков")

    async def get_mark_price(self, symbol: str) -> float:
        signer = self._get_signer()
        stats = await signer.order_api.exchange_stats()
        for ob in (stats.order_book_stats or []):
            if ob.symbol.upper() == symbol.upper():
                return float(ob.last_trade_price)
        raise ValueError(f"Цена {symbol} не найдена на Lighter")

    async def market_open(self, symbol: str, is_long: bool, size_usd: float) -> dict:
        signer = self._get_signer()
        await self._ensure_markets()

        market = self._markets.get(symbol.upper())
        if not market:
            raise ValueError(f"Рынок {symbol} не найден на Lighter")

        market_index = int(market.market_id)
        price = await self.get_mark_price(symbol)
        client_order_id = int(time.time() * 1000) % 1_000_000

        logger.info(
            f"Lighter: {'лонг' if is_long else 'шорт'} {symbol}, "
            f"market_id={market_index}, ${size_usd}, цена={price}"
        )

        tx, tx_hash, err = await signer.create_market_order_quote_amount(
            market_index=market_index,
            client_order_index=client_order_id,
            quote_amount=size_usd,
            max_slippage=0.10,
            is_ask=not is_long,
        )

        if err:
            raise RuntimeError(f"Lighter ошибка открытия {symbol}: {err}")

        logger.info(f"Lighter: ордер исполнен {symbol}, tx={tx_hash}")

        actual_size = size_usd / price  # fallback
        try:
            pos_result = await self.get_positions()
            if pos_result.status == ExchangeStatus.OK:
                pos = next((p for p in pos_result.positions if p["symbol"] == symbol.upper()), None)
                if pos:
                    actual_size = abs(pos["quantity"])
                    logger.info(f"Lighter: подтверждённый размер {symbol} = {actual_size}")
        except Exception as e:
            logger.warning(f"Lighter: не удалось получить реальный размер: {e}")

        return {
            "tx_hash": str(tx_hash),
            "size": actual_size,
            "size_usd": size_usd,
            "price": price,
        }

    async def market_open_by_qty(self, symbol: str, is_long: bool, quantity: float) -> dict:
        """Открывает позицию по точному количеству (для синхронизации ног)."""
        price = await self.get_mark_price(symbol)
        size_usd = quantity * price
        return await self.market_open(symbol, is_long, size_usd)

    async def market_close(self, symbol: str, size: float = 0, was_long: bool = True) -> CloseResult:
        try:
            signer = self._get_signer()
            await self._ensure_markets()

            market = self._markets.get(symbol.upper())
            if not market:
                return CloseResult(status=ExchangeStatus.API_ERROR, error=f"Рынок {symbol} не найден на Lighter")

            market_index = int(market.market_id)
            price = await self.get_mark_price(symbol)

            if size <= 0:
                pos_result = await self.get_positions()
                if pos_result.status == ExchangeStatus.API_ERROR:
                    return CloseResult(status=ExchangeStatus.API_ERROR, error=pos_result.error)
                if pos_result.status == ExchangeStatus.UNKNOWN:
                    return CloseResult(status=ExchangeStatus.UNKNOWN, error=pos_result.error)
                pos = next((p for p in pos_result.positions if p["symbol"] == symbol.upper()), None)
                if pos:
                    size = abs(pos["quantity"])
                if size <= 0:
                    logger.info(f"Lighter: позиция {symbol} уже закрыта (подтверждено API)")
                    return CloseResult(status=ExchangeStatus.ALREADY_CLOSED, price=price)

            # +5% чтобы гарантированно закрыть всю позицию.
            # reduce_only=True не даст закрыть больше, чем есть на бирже.
            size_usd = size * price * 1.05
            client_order_id = int(time.time() * 1000) % 1_000_000

            logger.info(f"Lighter: закрытие {symbol}, market_id={market_index}, ~${size_usd:.2f} (с запасом 5%)")

            tx, tx_hash, err = await signer.create_market_order_quote_amount(
                market_index=market_index,
                client_order_index=client_order_id,
                quote_amount=size_usd,
                max_slippage=0.15,
                is_ask=was_long,
                reduce_only=True,
            )

            if err:
                err_str = str(err).lower()
                safe_errors = ("no position", "position not found", "nothing to close",
                               "reduce only", "no open position")
                if any(s in err_str for s in safe_errors):
                    logger.warning(f"Lighter закрытие {symbol}: позиция уже закрыта ({err})")
                    return CloseResult(status=ExchangeStatus.ALREADY_CLOSED, price=price)
                return CloseResult(status=ExchangeStatus.API_ERROR, error=f"Lighter ошибка закрытия {symbol}: {err}")

            logger.info(f"Lighter: позиция {symbol} закрыта, tx={tx_hash}")
            return CloseResult(status=ExchangeStatus.OK, price=price)

        except Exception as e:
            logger.error(f"Lighter market_close {symbol} ошибка: {e}")
            return CloseResult(status=ExchangeStatus.API_ERROR, error=str(e))

    async def get_positions(self) -> PositionResult:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{LIGHTER_BASE_URL}/v1/accounts",
                    params={"blockchain_index": self._account_index},
                )
            if resp.status_code != 200:
                logger.warning(f"Lighter positions: HTTP {resp.status_code}: {resp.text[:200]}")
                return PositionResult(status=ExchangeStatus.API_ERROR,
                                      error=f"HTTP {resp.status_code}: {resp.text[:200]}")
            data = resp.json()

            account = data.get("account") or data
            raw_positions = (
                account.get("perp_positions")
                or account.get("positions")
                or account.get("open_positions")
                or []
            )

            positions = []
            for pos in raw_positions:
                qty_raw = pos.get("quantity") or pos.get("size") or 0
                qty = float(qty_raw)
                if qty == 0:
                    continue
                symbol = (
                    pos.get("market_symbol") or pos.get("symbol") or ""
                ).replace("-PERP", "").replace("/USDC", "").upper()
                positions.append({"symbol": symbol, "quantity": qty})

            return PositionResult(status=ExchangeStatus.OK, positions=positions)

        except Exception as e:
            logger.warning(f"Lighter get_positions ошибка: {e}")
            return PositionResult(status=ExchangeStatus.API_ERROR, error=str(e))

    async def get_balance(self) -> float | None:
        """Lighter не предоставляет API для чтения баланса."""
        return None

    async def close(self):
        if self._signer:
            await self._signer.close()
            self._signer = None
