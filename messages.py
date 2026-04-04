"""
Bot messages in Russian and English.
Set BOT_LANG=ru or BOT_LANG=en in .env
"""

RU = {
    # ─── Main keyboard buttons ───────────────────────────────────────────────
    "btn_positions": "📊 Мои позиции",
    "btn_scan": "🔍 Сканировать сейчас",
    "btn_history": "📋 История",
    "btn_settings": "⚙️ Настройки",
    "btn_balances": "💰 Балансы",
    "btn_support": "💙 Поддержать автора",

    # ─── Inline buttons ──────────────────────────────────────────────────────
    "btn_subscribed": "✅ Подписался!",
    "btn_open_pair": "✅ Открыть пару",
    "btn_skip": "❌ Пропустить",
    "btn_add": "➕ Добавить",
    "btn_close_pair": "❌ Закрыть пару",
    "btn_close": "❌ Закрыть",
    "btn_enter_manual": "✏️ Ввести вручную",

    # ─── Direction labels ────────────────────────────────────────────────────
    "long_arrow": "лонг ↑",
    "short_arrow": "шорт ↓",
    "long": "лонг",
    "short": "шорт",

    # ─── Welcome ─────────────────────────────────────────────────────────────
    "welcome_new": (
        "👋 Привет! Это бот для дельта-нейтрального арбитража фандинга.\n\n"
        "Бот бесплатный — я делюсь им с сообществом. "
        "Если хочешь поддержать и следить за обновлениями, "
        "подпишись на канал 👉 {channel_name}\n\n"
        "{channel}"
    ),
    "welcome_back": "👋 Привет! Кнопки управления внизу 👇",
    "welcome_subscribed": "✅ Спасибо! Добро пожаловать 🤝",
    "control_buttons": "👇 Кнопки управления:",

    # ─── Positions ───────────────────────────────────────────────────────────
    "no_positions": "📭 Открытых позиций нет",
    "size_label": "💵 Размер",
    "opened_label": "⏱ Открыта",
    "h_ago": "ч назад",
    "net_apr_label": "└ Нетто APR",
    "earned_label": "💰 Заработано",
    "earned_estimate": "~оценка",
    "no_data": "нет данных",
    "type_label": "📋 Тип",
    "entry_price_label": "📈 Цена входа",
    "apr_label": "📊 APR",
    "per_leg": "на ногу",

    # ─── Balances ────────────────────────────────────────────────────────────
    "loading_balances": "⏳ Загружаю балансы...",
    "balances_title": "💰 <b>Балансы</b>",
    "balances_total": "📊 Итого",
    "no_api_balance": "нет API баланса",
    "balance_error": "❌ ошибка",

    # ─── Settings ────────────────────────────────────────────────────────────
    "settings_title": "⚙️ <b>Настройки</b>",
    "settings_exchanges_header": "── Биржи ──",
    "settings_size_header": "── Размер позиций ──",
    "settings_global_btn": "Общий",
    "settings_per_exchange_btn": "Раздельный",
    "settings_enter_manual": "✏️ Ввести вручную",
    "settings_enter_exchange": "✏️ Ввести ({exch})",
    "settings_enabled": "Включены",
    "settings_mode_global": "Режим: <b>общий</b> — <code>${size:.0f}</code> на каждую ногу",
    "settings_mode_per_exchange": "Режим: <b>раздельный</b>",
    "settings_none_enabled": "ни одна",
    "enter_size_prompt": "✏️ Введи размер позиции в USD для {target}:",
    "all_exchanges": "всех бирж",
    "size_set_ok": "✅ Размер {target}: <code>${size:.0f}</code>",
    "size_set_ok_global": "общий",
    "min_size_error": "❌ Минимум $5",
    "enter_number_error": "❌ Введи число, например: <code>100</code>",

    # ─── History ─────────────────────────────────────────────────────────────
    "no_history": "📭 Закрытых позиций пока нет",
    "history_title": "📋 <b>История</b>",
    "history_page": "стр. {page}/{total}",
    "history_funding": "Фандинг",
    "history_total": "Итого",
    "history_fees": "💸 Комиссии",

    # ─── Scan ────────────────────────────────────────────────────────────────
    "scanning": "🔍 Сканирую...",
    "no_exchange_data": "❌ Нет данных ни от одной биржи",
    "no_pairs": "📭 Нет подходящих пар сейчас",
    "scan_result": "✅ <b>{count} пар</b> (APR от {min:.0f}% до {max:.0f}%)",

    # ─── Trading ─────────────────────────────────────────────────────────────
    "already_opening": "⏳ Уже открываю эту пару...",
    "opening_pair": "⏳ Проверяю фандинг и открываю {symbol}...",
    "funding_changed": "⚠️ Фандинг изменился! Текущий нетто APR: {apr:.1f}%\nПара не открыта.",
    "pair_opened": (
        "✅ <b>Пара открыта: {symbol}</b>\n\n"
        "  {exch_a}: <code>{size_a:.4f}</code> шт × <code>${price_a:.4f}</code> ({dir_a})\n"
        "  {exch_b}: <code>{size_b:.4f}</code> шт × <code>${price_b:.4f}</code> ({dir_b})\n"
        "💵 Размер: <code>~${size}</code> на ногу"
    ),
    "open_error": "❌ Ошибка открытия пары:\n<code>{error}</code>",
    "closing_pair": "⏳ Закрываю пару {symbol}...",
    "pair_closed": "✅ Пара {symbol} закрыта.",
    "close_error": "❌ Ошибка закрытия:\n<code>{error}</code>",
    "closing_position": "⏳ Закрываю позицию {symbol}...",
    "position_closed": "✅ Позиция {symbol} на {exchange} закрыта.",
    "position_not_found": "❌ Позиция не найдена (id={id})",
    "scale_in_prompt": "✏️ Введи сумму для добавления к паре {symbol} (в USD):",
    "scale_in_adding": "⏳ Добавляю ${amount} к паре {symbol}...",
    "scale_in_done": "✅ Добавлено <code>${amount}</code> к паре {symbol}",
    "scale_in_error": "❌ Ошибка scale in:\n<code>{error}</code>",

    # ─── Support ─────────────────────────────────────────────────────────────
    "support_title": "💙 <b>Поддержать автора</b>",
    "support_channel": "Канал",

    # ─── Monitoring alerts ───────────────────────────────────────────────────
    "negative_funding_alert": (
        "⚠️ <b>Фандинг ушёл в минус — {symbol}</b>\n\n"
        "{apr_details}\n"
        "Нетто: <code>{net_apr:+.1f}%</code> APR\n\n"
        "Жду <code>{wait_hours}ч</code> — если не восстановится, закрою автоматически."
    ),
    "auto_close_ok": (
        "🤖 <b>АВТОЗАКРЫТИЕ — {symbol}</b> ({exchanges})\n\n"
        "Причина: {reason}\n\n"
        "✅ Пара закрыта автоматически."
    ),
    "auto_close_fail": (
        "🚨 <b>АВТОЗАКРЫТИЕ ПРОВАЛИЛОСЬ — {symbol}!</b>\n\n"
        "Причина: {reason}\n\n"
        "❌ Ошибка: <code>{error}</code>\n\n"
        "⚠️ <b>Закрой пару вручную немедленно!</b>"
    ),
    "liq_risk_alert": (
        "⚠️ <b>РИСК ЛИКВИДАЦИИ — {symbol}</b>\n\n"
        "{exchange} ({direction}): до ликвидации <code>{distance:.1f}%</code>\n"
        "  Цена: <code>${mark:.4f}</code> → Ликвидация: <code>${liq:.4f}</code> (плечо {leverage}x)\n\n"
        "⚠️ Закрою автоматически при <code>{threshold}%</code>"
    ),
    "price_risk_alert": (
        "⚠️ <b>РИСК — {symbol}</b>\n\n"
        "{exchange} ({direction}): цена {direction_str} на <code>{loss:.1f}%</code>\n"
        "  Вход: <code>${entry:.4f}</code> → Сейчас: <code>${current:.4f}</code>\n\n"
        "⚠️ Закрою при <code>{threshold}%</code>"
    ),
    "position_mismatch": (
        "🚨 <b>РАСХОЖДЕНИЕ ПОЗИЦИЙ!</b>\n\n"
        "{alerts}\n\n"
        "<i>Проверь позиции на биржах и в боте (📊 Мои позиции).</i>"
    ),
    "mismatch_disappeared": "<b>{symbol}</b> {exchange}: позиция исчезла (в БД: {direction})",
    "mismatch_direction": "<b>{symbol}</b> {exchange}: направление не совпадает (БД: {db_dir}, биржа: {real_dir})",
    "auto_close_reason_neg_apr": "нетто APR упал до <code>{apr:.1f}%</code> (порог {threshold}%)\n{details}",
    "auto_close_reason_neg_wait": "нетто APR <code>{apr:+.1f}%</code> не восстановился за <code>{hours:.0f}ч</code>",
    "auto_close_reason_liq": "до ликвидации {exchange} осталось <code>{distance:.1f}%</code> (порог {threshold}%)\nЦена: <code>${mark:.4f}</code> → Ликвидация: <code>${liq:.4f}</code> (плечо {leverage}x)",
    "auto_close_reason_price": "{exchange} ({direction}): цена {direction_str} на <code>{loss:.1f}%</code> от входа\nВход: <code>${entry:.4f}</code> → Сейчас: <code>${current:.4f}</code>",
    "price_went_down": "упала",
    "price_went_up": "выросла",

    # ─── Signal (bot/telegram.py) ────────────────────────────────────────────
    "signal_net_apr": "📈 Нетто",
    "signal_fee": "комиссия",
}

EN = {
    # ─── Main keyboard buttons ───────────────────────────────────────────────
    "btn_positions": "📊 My Positions",
    "btn_scan": "🔍 Scan Now",
    "btn_history": "📋 History",
    "btn_settings": "⚙️ Settings",
    "btn_balances": "💰 Balances",
    "btn_support": "💙 Support Author",

    # ─── Inline buttons ──────────────────────────────────────────────────────
    "btn_subscribed": "✅ Subscribed!",
    "btn_open_pair": "✅ Open Pair",
    "btn_skip": "❌ Skip",
    "btn_add": "➕ Add",
    "btn_close_pair": "❌ Close Pair",
    "btn_close": "❌ Close",
    "btn_enter_manual": "✏️ Enter manually",

    # ─── Direction labels ────────────────────────────────────────────────────
    "long_arrow": "long ↑",
    "short_arrow": "short ↓",
    "long": "long",
    "short": "short",

    # ─── Welcome ─────────────────────────────────────────────────────────────
    "welcome_new": (
        "👋 Hi! This is a delta-neutral funding arbitrage bot.\n\n"
        "The bot is free — I'm sharing it with the community. "
        "If you'd like to support and follow updates, "
        "subscribe to the channel 👉 {channel_name}\n\n"
        "{channel}"
    ),
    "welcome_back": "👋 Hi! Control buttons below 👇",
    "welcome_subscribed": "✅ Thanks! Welcome 🤝",
    "control_buttons": "👇 Control buttons:",

    # ─── Positions ───────────────────────────────────────────────────────────
    "no_positions": "📭 No open positions",
    "size_label": "💵 Size",
    "opened_label": "⏱ Opened",
    "h_ago": "h ago",
    "net_apr_label": "└ Net APR",
    "earned_label": "💰 Earned",
    "earned_estimate": "~estimate",
    "no_data": "no data",
    "type_label": "📋 Type",
    "entry_price_label": "📈 Entry price",
    "apr_label": "📊 APR",
    "per_leg": "per leg",

    # ─── Balances ────────────────────────────────────────────────────────────
    "loading_balances": "⏳ Loading balances...",
    "balances_title": "💰 <b>Balances</b>",
    "balances_total": "📊 Total",
    "no_api_balance": "no API balance",
    "balance_error": "❌ error",

    # ─── Settings ────────────────────────────────────────────────────────────
    "settings_title": "⚙️ <b>Settings</b>",
    "settings_exchanges_header": "── Exchanges ──",
    "settings_size_header": "── Position Size ──",
    "settings_global_btn": "Global",
    "settings_per_exchange_btn": "Per-exchange",
    "settings_enter_manual": "✏️ Enter manually",
    "settings_enter_exchange": "✏️ Enter ({exch})",
    "settings_enabled": "Enabled",
    "settings_mode_global": "Mode: <b>global</b> — <code>${size:.0f}</code> per leg",
    "settings_mode_per_exchange": "Mode: <b>per-exchange</b>",
    "settings_none_enabled": "none",
    "enter_size_prompt": "✏️ Enter position size in USD for {target}:",
    "all_exchanges": "all exchanges",
    "size_set_ok": "✅ Size {target}: <code>${size:.0f}</code>",
    "size_set_ok_global": "global",
    "min_size_error": "❌ Minimum $5",
    "enter_number_error": "❌ Enter a number, e.g.: <code>100</code>",

    # ─── History ─────────────────────────────────────────────────────────────
    "no_history": "📭 No closed positions yet",
    "history_title": "📋 <b>History</b>",
    "history_page": "page {page}/{total}",
    "history_funding": "Funding",
    "history_total": "Total",
    "history_fees": "💸 Fees",

    # ─── Scan ────────────────────────────────────────────────────────────────
    "scanning": "🔍 Scanning...",
    "no_exchange_data": "❌ No data from any exchange",
    "no_pairs": "📭 No suitable pairs right now",
    "scan_result": "✅ <b>{count} pairs</b> (APR from {min:.0f}% to {max:.0f}%)",

    # ─── Trading ─────────────────────────────────────────────────────────────
    "already_opening": "⏳ Already opening this pair...",
    "opening_pair": "⏳ Checking funding and opening {symbol}...",
    "funding_changed": "⚠️ Funding changed! Current net APR: {apr:.1f}%\nPair not opened.",
    "pair_opened": (
        "✅ <b>Pair opened: {symbol}</b>\n\n"
        "  {exch_a}: <code>{size_a:.4f}</code> × <code>${price_a:.4f}</code> ({dir_a})\n"
        "  {exch_b}: <code>{size_b:.4f}</code> × <code>${price_b:.4f}</code> ({dir_b})\n"
        "💵 Size: <code>~${size}</code> per leg"
    ),
    "open_error": "❌ Error opening pair:\n<code>{error}</code>",
    "closing_pair": "⏳ Closing pair {symbol}...",
    "pair_closed": "✅ Pair {symbol} closed.",
    "close_error": "❌ Error closing:\n<code>{error}</code>",
    "closing_position": "⏳ Closing position {symbol}...",
    "position_closed": "✅ Position {symbol} on {exchange} closed.",
    "position_not_found": "❌ Position not found (id={id})",
    "scale_in_prompt": "✏️ Enter amount to add to pair {symbol} (in USD):",
    "scale_in_adding": "⏳ Adding ${amount} to pair {symbol}...",
    "scale_in_done": "✅ Added <code>${amount}</code> to pair {symbol}",
    "scale_in_error": "❌ Scale in error:\n<code>{error}</code>",

    # ─── Support ─────────────────────────────────────────────────────────────
    "support_title": "💙 <b>Support Author</b>",
    "support_channel": "Channel",

    # ─── Monitoring alerts ───────────────────────────────────────────────────
    "negative_funding_alert": (
        "⚠️ <b>Funding went negative — {symbol}</b>\n\n"
        "{apr_details}\n"
        "Net: <code>{net_apr:+.1f}%</code> APR\n\n"
        "Waiting <code>{wait_hours}h</code> — if it doesn't recover, I'll close automatically."
    ),
    "auto_close_ok": (
        "🤖 <b>AUTO-CLOSE — {symbol}</b> ({exchanges})\n\n"
        "Reason: {reason}\n\n"
        "✅ Pair closed automatically."
    ),
    "auto_close_fail": (
        "🚨 <b>AUTO-CLOSE FAILED — {symbol}!</b>\n\n"
        "Reason: {reason}\n\n"
        "❌ Error: <code>{error}</code>\n\n"
        "⚠️ <b>Close the pair manually immediately!</b>"
    ),
    "liq_risk_alert": (
        "⚠️ <b>LIQUIDATION RISK — {symbol}</b>\n\n"
        "{exchange} ({direction}): <code>{distance:.1f}%</code> to liquidation\n"
        "  Price: <code>${mark:.4f}</code> → Liquidation: <code>${liq:.4f}</code> (leverage {leverage}x)\n\n"
        "⚠️ Will auto-close at <code>{threshold}%</code>"
    ),
    "price_risk_alert": (
        "⚠️ <b>RISK — {symbol}</b>\n\n"
        "{exchange} ({direction}): price {direction_str} by <code>{loss:.1f}%</code>\n"
        "  Entry: <code>${entry:.4f}</code> → Now: <code>${current:.4f}</code>\n\n"
        "⚠️ Will close at <code>{threshold}%</code>"
    ),
    "position_mismatch": (
        "🚨 <b>POSITION MISMATCH!</b>\n\n"
        "{alerts}\n\n"
        "<i>Check positions on exchanges and in the bot (📊 My Positions).</i>"
    ),
    "mismatch_disappeared": "<b>{symbol}</b> {exchange}: position disappeared (DB: {direction})",
    "mismatch_direction": "<b>{symbol}</b> {exchange}: direction mismatch (DB: {db_dir}, exchange: {real_dir})",
    "auto_close_reason_neg_apr": "net APR dropped to <code>{apr:.1f}%</code> (threshold {threshold}%)\n{details}",
    "auto_close_reason_neg_wait": "net APR <code>{apr:+.1f}%</code> did not recover in <code>{hours:.0f}h</code>",
    "auto_close_reason_liq": "{exchange} liquidation distance <code>{distance:.1f}%</code> (threshold {threshold}%)\nPrice: <code>${mark:.4f}</code> → Liquidation: <code>${liq:.4f}</code> (leverage {leverage}x)",
    "auto_close_reason_price": "{exchange} ({direction}): price {direction_str} by <code>{loss:.1f}%</code> from entry\nEntry: <code>${entry:.4f}</code> → Now: <code>${current:.4f}</code>",
    "price_went_down": "dropped",
    "price_went_up": "rose",

    # ─── Signal (bot/telegram.py) ────────────────────────────────────────────
    "signal_net_apr": "📈 Net",
    "signal_fee": "fee",
}
