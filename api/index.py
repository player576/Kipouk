import os
import json
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from telegram import Bot, Update
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters

app = FastAPI()

# Временное хранилище конфигов в памяти процесса
BOT_CONFIGS = {}

@app.get("/", response_class=HTMLResponse)
async def read_index():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.post("/api/start-bot")
async def start_bot(request: Request):
    data = await request.json()
    token = data.get("token")
    graph = data.get("graph")

    if not token:
        return JSONResponse({"success": False, "message": "Токен не указан!"}, status_code=400)

    BOT_CONFIGS[token] = graph

    # Настраиваем Webhook в Telegram
    host_url = str(request.base_url).rstrip('/')
    webhook_url = f"{host_url}/api/webhook/{token}"
    
    bot = Bot(token=token)
    bot.set_webhook(url=webhook_url)

    return {"success": True, "message": "Вебхук успешно установлен! Бот готов к работе."}

@app.post("/api/webhook/{token}")
async def handle_webhook(token: str, request: Request):
    data = await request.json()
    bot = Bot(token=token)
    
    # Получаем структуру графа
    graph = BOT_CONFIGS.get(token, {})
    drawflow_data = graph.get("drawflow", {}).get("Home", {}).get("data", {})

    # Простейшая обработка входящего сообщения
    if "message" in data and "text" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"]["text"]

        # Ищем первый узел со стартовым текстом или ответом
        reply_text = "Привет! Я бот, работающий на Vercel."
        for node_id, node in drawflow_data.items():
            if node.get("name") == "start" and text == "/start":
                reply_text = node.get("html_text", reply_text)
                break

        bot.send_message(chat_id=chat_id, text=reply_text)

    return {"status": "ok"}
