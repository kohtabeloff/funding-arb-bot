import asyncio
import httpx
import logging
from .base import BaseScanner, FundingRate

logger = logging.getLogger(__name__)

MARKET_DATA_URL = "https://market-data.grvt.io"


class GRVTScanner(BaseScanner):
    """
    GRVT (Gravity) — ZK-powered derivatives exchange.
    Публичный API, без авторизации для чтения.

    Важно: GRVT возвращает funding_rate уже в процентах
    (0.01 = 0.01% за период, НЕ 1%).
    Интервал (4h/8h) берём из all_instruments, в тикере его нет.
    """

    exchange_name = "GRVT"

    async def _get_instruments_map(self) -> dict[str, int]:
        """Возвращает {instrument_name: funding_interval_hours}."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(f"{MARKET_DATA_URL}/full/v1/all_instruments", json={})
                resp.raise_for_status()
                data = resp.json()

            result = {}
            for item in data.get("result", []):
                name = item.get("instrument", "")
                kind = item.get("kind", "")
                if not (kind == "PERPETUAL" or name.endswith("_Perp")):
                    continue
                interval = int(item.get("funding_interval_hours") or 8)
                result[name] = interval
            return result
        except Exception as e:
            logger.error(f"GRVT: ошибка получения инструментов: {e}")
            return {}

    async def _get_ticker(self, instrument: str) -> dict | None:
        """Получает тикер для одного инструмента."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{MARKET_DATA_URL}/full/v1/ticker",
                    json={"instrument": instrument},
                )
                if resp.status_code != 200:
                    return None
                return resp.json().get("result")
        except Exception:
            return None

    async def get_funding_rates(self) -> list[FundingRate]:
        # Загружаем инструменты и их интервалы
        instruments_map = await self._get_instruments_map()
        if not instruments_map:
            logger.warning("GRVT: нет перп инструментов")
            return []

        instruments = list(instruments_map.keys())
        rates = []
        batch_size = 50

        for i in range(0, len(instruments), batch_size):
            batch = instruments[i:i + batch_size]
            results = await asyncio.gather(
                *[self._get_ticker(inst) for inst in batch],
                return_exceptions=True,
            )

            for instrument, result in zip(batch, results):
                if isinstance(result, Exception) or result is None:
                    continue

                try:
                    symbol = instrument.split("_")[0].upper()

                    # funding_rate на GRVT — уже в % за период
                    # (например 0.01 = 0.01% за 8ч, а не 1%)
                    funding_rate_str = (
                        result.get("funding_rate_8h_curr")
                        or result.get("funding_rate")
                    )
                    funding_rate_pct = float(funding_rate_str) if funding_rate_str is not None else 0.0

                    interval_hours = instruments_map.get(instrument, 8)

                    # Переводим в долю за час для единообразия с другими биржами
                    # funding_rate_pct% за interval_hours → доля/час
                    hourly_rate = funding_rate_pct / 100 / interval_hours
                    apr = hourly_rate * 24 * 365 * 100

                    mark_price = float(result.get("mark_price") or 0)
                    open_interest = float(result.get("open_interest") or 0)
                    oi_usd = open_interest * mark_price if mark_price else 0

                    volume_usd = float(
                        result.get("buy_volume_24h_q", 0) or 0
                    ) + float(result.get("sell_volume_24h_q", 0) or 0)

                    rates.append(FundingRate(
                        exchange="GRVT",
                        symbol=symbol,
                        rate=hourly_rate,
                        interval_hours=1,
                        apr=apr,
                        open_interest_usd=oi_usd,
                        volume_usd=volume_usd,
                        mark_price=mark_price,
                    ))
                except Exception as e:
                    logger.debug(f"GRVT: ошибка парсинга {instrument}: {e}")

        logger.info(f"GRVT: получено {len(rates)} рынков")
        return rates
