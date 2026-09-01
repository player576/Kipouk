import os
import json
import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI()
BOT_CONFIGS = {}

@app.get("/", response_class=HTMLResponse)
async def read_index():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"<h1>Ошибка: {str(e)}</h1>"

@app.post("/api/start-bot")
async def start_bot(request: Request):
    try:
        data = await request.json()
        token = data.get("token")
        graph = data.get("graph")

        if not token:
            return JSONResponse({"success": False, "message": "Токен не указан!"}, status_code=400)

        BOT_CONFIGS[token] = graph

        host_url = str(request.base_url).rstrip('/')
        webhook_url = f"{host_url}/api/webhook/{token}"
        
        tg_url = f"https://api.telegram.org/bot{token}/setWebhook?url={webhook_url}"
        res = requests.get(tg_url).json()

        if res.get("ok"):
            return {"success": True, "message": "Схема обновлена! Бот готов."}
        else:
            return JSONResponse({"success": False, "message": res.get("description")}, status_code=400)
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)

@app.post("/api/webhook/{token}")
async def handle_webhook(token: str, request: Request):
    try:
        data = await request.json()
        graph = BOT_CONFIGS.get(token, {})
        drawflow_data = graph.get("drawflow", {}).get("Home", {}).get("data", {})

        send_url = f"https://api.telegram.org/bot{token}/sendMessage"

        # Обработка сообщения или клика по Inline-кнопке
        chat_id = None
        user_input = None
        is_callback = False

        if "message" in data:
            chat_id = data["message"]["chat"]["id"]
            user_input = data["message"].get("text", "")
        elif "callback_query" in data:
            chat_id = data["callback_query"]["message"]["chat"]["id"]
            user_input = data["callback_query"].get("data", "")
            is_callback = True

        if chat_id and drawflow_data:
            # Обработка /start
            if user_input == "/start":
                start_node = drawflow_data.get("1", {})
                text = start_node.get("custom_text", "Привет!")
                btn_text = start_node.get("custom_btn", "")

                payload = {"chat_id": chat_id, "text": text}
                
                # Если в узел добавлена кнопка, отправляем её
                if btn_text:
                    payload["reply_markup"] = {
                        "inline_keyboard": [[{"text": btn_text, "callback_data": "next_step"}]]
                    }

                requests.post(send_url, json=payload)

            # Обработка клика по кнопке
            elif user_input == "next_step":
                # Ищем следующий узел, соединенный со стартовым
                next_text = "Вы нажали кнопку!"
                if "1" in drawflow_data and "outputs" in drawflow_data["1"]:
                    output_connections = drawflow_data["1"]["outputs"].get("output_1", {}).get("connections", [])
                    if output_connections:
                        target_node_id = output_connections[0].get("node")
                        if target_node_id in drawflow_data:
                            next_text = drawflow_data[target_node_id].get("custom_text", next_text)

                requests.post(send_url, json={"chat_id": chat_id, "text": next_text})

        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
