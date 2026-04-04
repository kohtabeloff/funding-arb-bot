import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BOT_LANG = os.getenv("BOT_LANG", "ru")  # "ru" or "en"

# Стратегия
SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", 60))
MIN_PAIR_APR = float(os.getenv("MIN_PAIR_APR", 50))
MIN_VOLUME_USD = float(os.getenv("MIN_VOLUME_USD", 50_000))
POSITION_SIZE_USD = float(os.getenv("POSITION_SIZE_USD", 100))

# Backpack Exchange (Ed25519)
BACKPACK_API_KEY = os.getenv("BACKPACK_API_KEY", "")
BACKPACK_API_SECRET = os.getenv("BACKPACK_API_SECRET", "")

# Lighter DEX
LIGHTER_API_PRIVATE_KEY = os.getenv("LIGHTER_API_PRIVATE_KEY", "")
LIGHTER_API_KEY_INDEX = int(os.getenv("LIGHTER_API_KEY_INDEX", "2"))
LIGHTER_ACCOUNT_INDEX = int(os.getenv("LIGHTER_ACCOUNT_INDEX", "0"))

# Hyperliquid
HYPERLIQUID_PRIVATE_KEY = os.getenv("HYPERLIQUID_PRIVATE_KEY", "")
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "")

# GRVT (EIP-712 signing)
GRVT_API_KEY = os.getenv("GRVT_API_KEY", "")
GRVT_PRIVATE_KEY = os.getenv("GRVT_PRIVATE_KEY", "")          # ETH private key для подписи ордеров
GRVT_TRADING_ACCOUNT_ID = os.getenv("GRVT_TRADING_ACCOUNT_ID", "")  # Sub-account ID

# Aster
ASTER_API_KEY = os.getenv("ASTER_API_KEY", "")
ASTER_API_SECRET = os.getenv("ASTER_API_SECRET", "")

# Защита: пороги автозакрытия
LIQ_WARN_PCT = 20.0           # % до ликвидации → предупреждение
LIQ_AUTO_CLOSE_PCT = 15.0     # % до ликвидации → автозакрытие
PRICE_WARN_PCT = 10.0         # % отклонения цены от входа → предупреждение
PRICE_AUTO_CLOSE_PCT = 15.0   # % отклонения цены от входа → автозакрытие
NEG_APR_HARD_CLOSE = -50.0    # APR пары ниже этого → немедленное автозакрытие
NEG_APR_WAIT_HOURS = 4.0      # часов ожидания при мягком минусе

# Автор
AUTHOR_CHANNEL = "https://t.me/hubcryptocis"
AUTHOR_CHANNEL_NAME = "@hubcryptocis"
DONATION_WALLET_EVM = "0xA3aCe3905fb080930f7Eeac9Fe401F5B41b16629"
DONATION_WALLET_SOL = "5UztCBoUq2HvtH5nibLmWgxuR5fU5AeagkX9mqdXa5Pq"

# Реестр бирж: какие биржи доступны в системе
# Ключ — внутренний ID, значение — человекочитабельное имя
EXCHANGES = {
    "backpack": "Backpack",
    "lighter": "Lighter",
    "hyperliquid": "Hyperliquid",
    "grvt": "GRVT",
    "aster": "Aster",
}
