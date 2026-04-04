# Funding Arbitrage Bot

> 🇷🇺 [Русская версия](README_RU.md)

A Telegram bot for delta-neutral funding rate arbitrage on crypto perpetual exchanges.

**Strategy:** open a long on one exchange and a short on another — earn the funding rate spread while staying market-neutral.

**Supported exchanges:**
- Backpack
- Lighter
- Hyperliquid
- GRVT
- Aster

Any exchange can be paired with any other — the bot finds the best combinations automatically.

---

## ⚠️ Disclaimer

This bot is provided free of charge, as is. The author **takes no responsibility** for loss of funds, technical failures, exchange API changes, or any other consequences of using the bot. Crypto trading involves risk — you act at your own discretion.

**Recommendation:** before using, paste the code into any AI (ChatGPT, Claude, Gemini) and ask it to review for safety and correctness. Takes 5 minutes and gives extra confidence.

---

## Getting help

If something doesn't work — open [Claude Code](https://claude.ai/code) or [ChatGPT](https://chatgpt.com) directly in the bot folder. The AI will help with any installation step, explain errors, and suggest fixes.

---

## Table of Contents

1. [What you need](#1-what-you-need)
2. [Getting a VPS](#2-getting-a-vps)
3. [Getting API keys](#3-getting-api-keys)
4. [Creating a Telegram bot](#4-creating-a-telegram-bot)
5. [Installing the bot on VPS](#5-installing-the-bot-on-vps)
6. [Configuring .env](#6-configuring-env)
7. [Running](#7-running)
8. [Auto-start on reboot](#8-auto-start-on-reboot)
9. [How to use](#9-how-to-use)

---

## 1. What you need

- VPS server (Linux, Ubuntu 22.04+)
- Accounts on exchanges: Backpack, Lighter, Hyperliquid, GRVT, Aster (not all required — the bot works with any subset)
- Telegram bot (created via BotFather in 1 minute)
- Starting capital: from ~$100 (minimum $10–15 per leg for testing)

---

## 2. Getting a VPS

A VPS is a remote server that runs your bot 24/7. Without it, the bot only works while your computer is on.

### Minimum requirements
| Parameter | Minimum |
|-----------|---------|
| CPU | 1 vCPU |
| RAM | 1 GB |
| Disk | 10 GB SSD |
| OS | Ubuntu 22.04 LTS |
| Python | 3.10+ (3.11 recommended) |

> **Important:** choose a server **outside Russia** (Netherlands, Finland, Germany) — some exchanges block Russian IPs.

### Where to buy (card or crypto)

- **[Vultr](https://www.vultr.com/)** — card or crypto, servers worldwide
- **[Hetzner](https://www.hetzner.com/)** — reliable, affordable, European servers
- **[DigitalOcean](https://www.digitalocean.com/)** — beginner-friendly

---

## 3. Getting API keys

### Backpack
1. Sign up: [Backpack](https://backpack.exchange/join/65d923ff-b224-4dfb-aa6c-cd5346c77651)
2. Complete KYC
3. Deposit funds (USDC)
4. Create API key: **Settings → API Keys → Create API Key**
   - Give it a name, e.g. `arb-bot`
   - Enable permissions: `Order` (read + trade)
   - Save `API Key` and `Secret Key`

### Lighter
1. Sign up: [Lighter](https://app.lighter.xyz/?referral=KOHTA) (connect an EVM wallet, e.g. MetaMask)
2. Deposit USDC via Arbitrum
3. Create API key: **Settings → API Keys → Generate API Key**
   - Set `API Key Index` to `2` (0 and 1 are reserved)
   - Click `Generate`
   - Save the `Private Key`
4. Note your `Account Index` — visible in account settings

### Hyperliquid
1. Sign up: [Hyperliquid](https://app.hyperliquid.xyz/join/KOHTA)
2. Deposit USDC via Arbitrum
3. Hyperliquid has no separate API keys — the bot uses your EVM wallet private key

   > 💡 **Recommended: API Wallet (agent key)**
   >
   > Instead of your main wallet's private key, create an **API Wallet** — a separate key with trading rights only, no withdrawal access. Much safer.
   >
   > How to create: **More → API → Generate API Wallet** → save the agent private key. Put it in `HYPERLIQUID_PRIVATE_KEY` in `.env`, and put your **main** wallet address in `WALLET_ADDRESS`.

   If using your main wallet key: MetaMask → three dots on account → `Account details` → `Export private key`. Better to use a dedicated trading wallet.

### GRVT
1. Sign up: [GRVT](https://grvt.io/exchange/earn-on-equity?ref=BNZ8NKI)
2. Deposit funds
3. Create API key: **Settings → API Keys → Create API Key**
   - Make sure `Trade` permission is enabled
   - Save `API Key`
4. Note your `Trading Account ID` — visible in the URL or sub-account settings
5. Private key — the same EVM wallet you use to manage your GRVT account

### Aster
1. Sign up: [Aster](https://www.asterdex.com/en/referral/rLfLbr)
2. Deposit USDC
3. Create API key: **Account → API Management → Create API Key**
   - Enable trading permission
   - Save `API Key` and `Secret Key`

---

## 4. Creating a Telegram bot

1. Open [@BotFather](https://t.me/BotFather) in Telegram
2. Send `/newbot`
3. Choose a name and username (e.g. `my_arb_bot`)
4. BotFather will give you a **token** — save it
5. Get your `chat_id`: message [@userinfobot](https://t.me/userinfobot) — it will reply with your ID

---

## 5. Installing the bot on VPS

### Connecting to the server

After purchasing a VPS you'll receive an IP address, login, and password. Connect via SSH.

**Mac / Linux** — open Terminal and run:
```bash
ssh root@YOUR_IP
```
Enter the password when prompted (characters won't show while typing — that's normal).

**Windows** — open PowerShell (Win+R → powershell) and run the same command. Or download [PuTTY](https://putty.org).

> 💡 If stuck — ask an AI: "how to connect to VPS via SSH from Windows/Mac".

---

Run commands one by one after connecting:

### Update the system
```bash
sudo apt update && sudo apt upgrade -y
```

### Install Python and Git
```bash
sudo apt install python3.11 python3.11-venv python3-pip git -y
```

### Download the bot
```bash
cd ~
git clone https://github.com/kohtabeloff/funding-arb-bot.git
cd funding-arb-bot
```

### Create virtual environment
```bash
python3.11 -m venv venv
source venv/bin/activate
```

### Install dependencies
```bash
pip install -r requirements.txt
```

---

## 6. Configuring .env

Create the config file from the example:
```bash
cp .env.example .env
nano .env
```

Fill in the required fields (exchanges you don't use can be left empty):

```env
# Telegram
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Bot language: en or ru
BOT_LANG=en

# Strategy
MIN_PAIR_APR=50             # minimum net APR for a pair signal (%)
SCAN_INTERVAL_SECONDS=60    # how often to scan (seconds)
POSITION_SIZE_USD=100       # default position size per leg (USD)

# Backpack
BACKPACK_API_KEY=
BACKPACK_API_SECRET=

# Lighter
LIGHTER_API_PRIVATE_KEY=
LIGHTER_API_KEY_INDEX=2
LIGHTER_ACCOUNT_INDEX=0

# Hyperliquid
HYPERLIQUID_PRIVATE_KEY=
WALLET_ADDRESS=

# GRVT
GRVT_API_KEY=
GRVT_PRIVATE_KEY=
GRVT_TRADING_ACCOUNT_ID=

# Aster
ASTER_API_KEY=
ASTER_API_SECRET=
```

Save the file: `Ctrl+O`, then `Ctrl+X`.

---

## 7. Running

```bash
source venv/bin/activate
python main.py
```

If everything is configured correctly, the bot will send a welcome message in Telegram.

---

## 8. Auto-start on reboot

Create a service file:
```bash
sudo nano /etc/systemd/system/funding-arb-bot.service
```

Paste the content (replace `YOUR_USER` with your login — usually `root`):

```ini
[Unit]
Description=Funding Arbitrage Bot
After=network.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/home/YOUR_USER/funding-arb-bot
ExecStart=/home/YOUR_USER/funding-arb-bot/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Save (`Ctrl+O`, `Ctrl+X`) and enable:
```bash
sudo systemctl daemon-reload
sudo systemctl enable funding-arb-bot
sudo systemctl start funding-arb-bot
```

Check that the bot is running:
```bash
sudo systemctl status funding-arb-bot
```

View logs:
```bash
sudo journalctl -u funding-arb-bot -f
```

---

## 9. How to use

### Main buttons

| Button | What it does |
|--------|-------------|
| 📊 My Positions | Open pairs: current APR, earnings, duration |
| 🔍 Scan Now | Manual scan — top opportunities right now |
| 💰 Balances | Current balances on all connected exchanges |
| 📋 History | Closed pairs with results |
| ⚙️ Settings | Exchanges, position size |
| 💙 Support Author | Donation wallets |

### How to open a pair

1. The bot automatically sends a signal when it finds a good opportunity on any exchange combination
2. Or press **🔍 Scan Now** to check immediately
3. In the signal message, press **✅ Open Pair** — the bot opens both legs automatically

### How to close a pair

1. Press **📊 My Positions**
2. Find the pair and press **❌ Close Pair**

### How to add to a position

To increase the size of an already open pair:

1. Press **📊 My Positions**
2. Find the pair and press **➕ Add**
3. Enter the amount in USD — the bot will add to both legs proportionally

### Settings

In **⚙️ Settings** you can:
- Enable and disable individual exchanges
- Choose position size mode: **global** (same size for all) or **per-exchange** (separate size for each)

### Automatic protection

The bot closes a pair automatically if:
- Net APR drops below **−50%**
- APR goes negative and **doesn't recover within 4 hours**
- Price moves against any leg by more than **15%** from entry (warning at 10%)
- Any leg is less than **15%** from liquidation (warning at 20%)

---

## Tips

**Start small.** Open your first positions with minimum amounts — $10–15 per leg. Make sure the bot correctly opens and closes positions, monitoring works, and notifications arrive. Only then increase position sizes.

**Fewer positions is better.** Every open/close costs money: exchange fees plus spread. Better to hold 1–2 pairs with larger sizes than spread capital across 5–10 small positions.

**Use dedicated wallets.** For Hyperliquid and GRVT the bot uses an EVM wallet private key. Create a separate wallet just for the bot — don't use your main one.

---

## Updates and questions

Author's channel — bot updates, strategies, insights: [@hubcryptocis](https://t.me/hubcryptocis)

Support (EVM): `0xA3aCe3905fb080930f7Eeac9Fe401F5B41b16629`
Support (SOL): `5UztCBoUq2HvtH5nibLmWgxuR5fU5AeagkX9mqdXa5Pq`
