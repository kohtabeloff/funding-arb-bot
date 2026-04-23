# Деплой бота на VPS

## 1. Загрузи проект на VPS

```bash
cd ~
git clone https://github.com/kohtabeloff/funding-arb-bot funding-arb-bot
cd funding-arb-bot
```

## 2. Установи зависимости

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 3. Создай .env файл

```bash
cp .env.example .env
nano .env   # заполни все ключи
```

## 4. Проверь что бот запускается

```bash
source venv/bin/activate
python main.py
# Ctrl+C после проверки
```

## 5. Установи systemd сервис

```bash
sudo cp deploy/delta-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable delta-bot
sudo systemctl start delta-bot
```

## 6. Полезные команды

```bash
# Статус бота
sudo systemctl status delta-bot

# Смотреть логи в реальном времени
journalctl -u delta-bot -f

# Перезапустить после обновления кода
sudo systemctl restart delta-bot

# Остановить
sudo systemctl stop delta-bot
```

## 7. Обновление кода

```bash
cd ~/funding-arb-bot
git pull
sudo systemctl restart delta-bot
```
