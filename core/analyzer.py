"""
Универсальный анализатор — ищет лучшие пары на любых комбинациях бирж.
"""
import logging
from scanners.base import FundingRate
from config import MIN_PAIR_APR, MIN_VOLUME_USD

logger = logging.getLogger(__name__)


def find_pair_opportunities(
    exchange_rates: dict[str, list[FundingRate]],
    enabled_exchanges: set[str] | None = None,
    min_pair_apr: float | None = None,
    min_volume_usd: float | None = None,
    blacklist: set[str] | None = None,
) -> list[dict]:
    """
    Ищет лучшие дельта-нейтральные пары среди ВСЕХ комбинаций включённых бирж.

    exchange_rates: {"Backpack": [FundingRate, ...], "Lighter": [...], ...}
    enabled_exchanges: множество включённых бирж (None = все)

    Возвращает отсортированный список возможностей:
    [{"symbol", "exchange_a", "exchange_b", "dir_a", "dir_b",
      "apr_a", "apr_b", "net_apr"}, ...]
    """
    if min_pair_apr is None:
        min_pair_apr = MIN_PAIR_APR
    if min_volume_usd is None:
        min_volume_usd = MIN_VOLUME_USD

    # Фильтруем по включённым биржам
    if enabled_exchanges:
        exchange_rates = {k: v for k, v in exchange_rates.items() if k in enabled_exchanges}

    # Строим индекс: {symbol: {exchange: FundingRate}}
    symbol_map: dict[str, dict[str, FundingRate]] = {}
    for exchange_name, rates in exchange_rates.items():
        for rate in rates:
            symbol_map.setdefault(rate.symbol, {})[exchange_name] = rate

    opportunities = []
    exchanges = list(exchange_rates.keys())

    for symbol, rates_by_exchange in symbol_map.items():
        if len(rates_by_exchange) < 2:
            continue

        # Фильтр мусорных символов
        if len(symbol) < 2 or not any(c.isalpha() for c in symbol):
            continue

        # Блэклист
        if blacklist and symbol in blacklist:
            continue

        # Перебираем все пары бирж для этого символа
        exchange_list = list(rates_by_exchange.keys())
        for i in range(len(exchange_list)):
            for j in range(i + 1, len(exchange_list)):
                exch_a = exchange_list[i]
                exch_b = exchange_list[j]
                rate_a = rates_by_exchange[exch_a]
                rate_b = rates_by_exchange[exch_b]

                # Фильтры
                if rate_a.apr == 0 and rate_b.apr == 0:
                    continue
                if abs(rate_a.apr) > 2000 or abs(rate_b.apr) > 2000:
                    continue
                # Хотя бы одна нога с реальным фандингом
                if abs(rate_a.apr) < 1 and abs(rate_b.apr) < 1:
                    continue
                # Проверяем объём (если доступен)
                if rate_a.volume_usd and rate_a.volume_usd < min_volume_usd:
                    continue
                if rate_b.volume_usd and rate_b.volume_usd < min_volume_usd:
                    continue

                # Определяем направления и нетто APR
                net_apr, dir_a, dir_b = _calc_pair_apr(rate_a.apr, rate_b.apr)

                if net_apr < min_pair_apr:
                    continue

                price_a = rate_a.mark_price
                price_b = rate_b.mark_price
                price_spread_pct = None
                if price_a > 0 and price_b > 0:
                    avg = (price_a + price_b) / 2
                    price_spread_pct = round(abs(price_a - price_b) / avg * 100, 3)

                opportunities.append({
                    "symbol": symbol,
                    "exchange_a": exch_a,
                    "exchange_b": exch_b,
                    "dir_a": dir_a,
                    "dir_b": dir_b,
                    "apr_a": rate_a.apr,
                    "apr_b": rate_b.apr,
                    "net_apr": round(net_apr, 1),
                    "mark_price": price_a or price_b,
                    "price_spread_pct": price_spread_pct,
                })

    opportunities.sort(key=lambda x: x["net_apr"], reverse=True)
    return opportunities


def _calc_pair_apr(apr_a: float, apr_b: float) -> tuple[float, str, str]:
    """
    Считает нетто APR и определяет оптимальные направления для пары.
    Возвращает: (net_apr, dir_a, dir_b)
    """
    if apr_a * apr_b < 0:
        # Разные знаки — лучший случай: складываем абсолютные значения
        net_apr = abs(apr_a) + abs(apr_b)
        dir_a = "SHORT" if apr_a > 0 else "LONG"
        dir_b = "SHORT" if apr_b > 0 else "LONG"
    else:
        # Одинаковые знаки — вычитаем, берём разницу
        net_apr = abs(abs(apr_a) - abs(apr_b))
        if abs(apr_a) >= abs(apr_b):
            dir_a = "SHORT" if apr_a > 0 else "LONG"
            dir_b = "LONG" if apr_b > 0 else "SHORT"
        else:
            dir_a = "LONG" if apr_a > 0 else "SHORT"
            dir_b = "SHORT" if apr_b > 0 else "LONG"

    return net_apr, dir_a, dir_b


def calc_net_apr_for_pair(legs: list[dict], rates_map: dict[str, FundingRate]) -> float:
    """
    Считает текущий нетто APR для открытой пары.
    legs: [{"exchange": str, "direction": str, "symbol": str}, ...]
    rates_map: {"Backpack:BTC": FundingRate, ...}
    """
    total = 0.0
    for leg in legs:
        key = f"{leg['exchange']}:{leg['symbol']}"
        rate = rates_map.get(key)
        if rate:
            income = rate.apr if leg["direction"] == "SHORT" else -rate.apr
            total += income
    return total
