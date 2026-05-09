from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class ExchangeStatus(Enum):
    """Единый статус для всех операций с биржей."""
    OK = "ok"               # операция выполнена успешно
    ALREADY_CLOSED = "already_closed"  # позиция уже закрыта (подтверждено биржей)
    API_ERROR = "api_error"    # биржа недоступна / ошибка авторизации
    UNKNOWN = "unknown"        # ответ получен, но интерпретировать нельзя


@dataclass
class PositionResult:
    """Результат запроса позиций."""
    status: ExchangeStatus
    positions: list[dict] | None = None  # None при API_ERROR/UNKNOWN
    error: str = ""


@dataclass
class CloseResult:
    """Результат закрытия позиции."""
    status: ExchangeStatus
    price: float = 0.0
    fee: float = 0.0
    error: str = ""


class BaseExchangeExecutor(ABC):
    """
    Единый интерфейс для всех бирж.
    Каждая биржа реализует эти методы — универсальный executor
    может работать с любой комбинацией бирж через этот интерфейс.

    Контракт:
    - API_ERROR и UNKNOWN никогда не считаются успехом
    - ALREADY_CLOSED означает позиция точно отсутствует (подтверждено API)
    - OK означает операция выполнена
    """

    name: str = ""          # "Backpack", "Lighter", "Hyperliquid", ...
    fee_rate: float = 0.0   # Примерная комиссия за сделку (0.0004 = 0.04%)

    @abstractmethod
    async def market_open(self, symbol: str, is_long: bool, size_usd: float) -> dict:
        """
        Открывает рыночный ордер.
        Возвращает: {"size": float, "price": float, "size_usd": float}
        Бросает исключение при любой ошибке.
        """

    @abstractmethod
    async def market_close(self, symbol: str, size: float, was_long: bool) -> CloseResult:
        """
        Закрывает позицию.
        Всегда возвращает CloseResult — никогда не бросает исключение.
        status=OK: позиция закрыта
        status=ALREADY_CLOSED: позиции не было (подтверждено API)
        status=API_ERROR: биржа недоступна
        status=UNKNOWN: ответ непонятен
        """

    @abstractmethod
    async def get_positions(self) -> PositionResult:
        """
        Возвращает открытые позиции.
        Всегда возвращает PositionResult — никогда не бросает исключение.
        status=OK: positions содержит список {"symbol": str, "quantity": float}
        status=API_ERROR: не удалось получить данные
        status=UNKNOWN: данные получены, но интерпретировать нельзя
        """

    async def get_balance(self) -> float | None:
        """Возвращает свободный баланс в USD. None если не поддерживается."""
        return None

    async def get_mark_price(self, symbol: str) -> float:
        """Получает текущую mark price для символа."""
        raise NotImplementedError(f"{self.name} не реализовал get_mark_price")

    async def get_liquidation_info(self, symbol: str) -> dict | None:
        """
        Возвращает информацию о ликвидации для открытой позиции.
        {"liquidation_price": float, "mark_price": float, "leverage": str}
        Возвращает None если биржа не поддерживает или нет позиции.
        """
        return None

    async def close(self):
        """Закрывает соединения (если нужно). По умолчанию ничего не делает."""
        pass
