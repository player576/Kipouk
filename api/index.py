import os
import json
import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI()

# Хранилище конфигов в памяти процесса
BOT_CONFIGS = {}

@app.get("/", response_class=HTMLResponse)
async def read_index():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"<h1>Ошибка чтения index.html: {str(e)}</h1>"

@app.post("/api/start-bot")
async def start_bot(request: Request):
    try:
        data = await request.json()
        token = data.get("token")
        graph = data.get("graph")

        if not token:
            return JSONResponse({"success": False, "message": "Токен не указан!"}, status_code=400)

        BOT_CONFIGS[token] = graph

        # Устанавливаем Webhook через прямой запрос к Telegram API
        host_url = str(request.base_url).rstrip('/')
        webhook_url = f"{host_url}/api/webhook/{token}"
        
        tg_url = f"https://api.telegram.org/bot{token}/setWebhook?url={webhook_url}"
        res = requests.get(tg_url).json()

        if res.get("ok"):
            return {"success": True, "message": "Вебхук успешно установлен! Бот работает."}
        else:
            return JSONResponse({"success": False, "message": f"Ошибка Telegram API: {res.get('description')}"}, status_code=400)
            
    except Exception as e:
        return JSONResponse({"success": False, "message": f"Ошибка сервера: {str(e)}"}, status_code=500)

@app.post("/api/webhook/{token}")
async def handle_webhook(token: str, request: Request):
    try:
        data = await request.json()
        
        # Получаем данные графа
        graph = BOT_CONFIGS.get(token, {})
        drawflow_data = graph.get("drawflow", {}).get("Home", {}).get("data", {})

        if "message" in data and "text" in data["message"]:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"]["text"]

            # Текст по умолчанию
            reply_text = "Привет! Я бот, работающий на Vercel."
            
            # Поиск кастомного текста из нода
            if "1" in drawflow_data:
                reply_text = drawflow_data["1"].get("html_text", reply_text)

            # Отправка сообщения обратно пользователю
            send_url = f"https://api.telegram.org/bot{token}/sendMessage"
            requests.post(send_url, json={"chat_id": chat_id, "text": reply_text})

        return {"status": "ok"}
    except Exception as e:
        print(f"Webhook Error: {e}")
        return {"status": "error", "message": str(e)}
