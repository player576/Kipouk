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
            return {"success": True, "message": "Конфигурация бота обновлена!"}
        else:
            return JSONResponse({"success": False, "message": res.get("description")}, status_code=400)
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)

def build_keyboard(btn_text, btn_type, callback_id=""):
    """Формирует структурированную клавиатуру: Inline (с дропом) или Reply (без дропа)"""
    if not btn_text:
        return None

    if btn_type == "inline":
        return {
            "inline_keyboard": [[{"text": btn_text, "callback_data": f"btn_{callback_id}"}]]
        }
    else:  # reply (обычная клавиатура внизу)
        return {
            "keyboard": [[{"text": btn_text}]],
            "resize_keyboard": True
        }

@app.post("/api/webhook/{token}")
async def handle_webhook(token: str, request: Request):
    try:
        data = await request.json()
        graph = BOT_CONFIGS.get(token, {})
        drawflow_data = graph.get("drawflow", {}).get("Home", {}).get("data", {})

        send_url = f"https://api.telegram.org/bot{token}/sendMessage"
        chat_id = None
        user_input = None
        clicked_target_node = None

        # Разбор входных данных (сообщение или клик на Inline-кнопку)
        if "message" in data:
            chat_id = data["message"]["chat"]["id"]
            user_input = data["message"].get("text", "").strip()
        elif "callback_query" in data:
            chat_id = data["callback_query"]["message"]["chat"]["id"]
            callback_data = data["callback_query"].get("data", "")
            if callback_data.startswith("btn_"):
                clicked_target_node = callback_data.replace("btn_", "")

        if chat_id and drawflow_data:
            target_node = None

            # 1. Если был клик по Inline-кнопке (с дропом) — переходим на целевой узел
            if clicked_target_node and clicked_target_node in drawflow_data:
                target_node = drawflow_data[clicked_target_node]

            # 2. Иначе ищем узел по тексту триггера или по нажатой Reply-кнопке (без дропа)
            if not target_node:
                for node_id, node in drawflow_data.items():
                    trg = node.get("custom_trigger", "").lower()
                    btn = node.get("custom_btn", "").lower()

                    # Совпадение по названию триггера или тексту обычной кнопки
                    if (trg and user_input.lower() == trg) or (btn and user_input.lower() == btn):
                        # Берём узел, соединённый с текущим, если есть выходное соединение
                        outs = node.get("outputs", {}).get("output_1", {}).get("connections", [])
                        if outs:
                            next_id = outs[0].get("node")
                            target_node = drawflow_data.get(next_id)
                        else:
                            target_node = node
                        break

            # 3. Отправка ответа
            if target_node:
                text = target_node.get("custom_text", "")
                btn_text = target_node.get("custom_btn", "")
                btn_type = target_node.get("custom_type", "inline")

                # Определяем, куда вести при клике на Inline-кнопку
                next_node_id = ""
                outs = target_node.get("outputs", {}).get("output_1", {}).get("connections", [])
                if outs:
                    next_node_id = outs[0].get("node")

                payload = {"chat_id": chat_id, "text": text}
                markup = build_keyboard(btn_text, btn_type, callback_id=next_node_id)
                if markup:
                    payload["reply_markup"] = markup

                requests.post(send_url, json=payload)

        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
