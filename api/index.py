import os
import json
import re
import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

app = FastAPI()

BOT_CONFIGS = {}
USER_STATES = {}
USER_DATA = {}

class StartBotPayload(BaseModel):
    token: str
    graph: dict

@app.get("/", response_class=HTMLResponse)
async def read_index():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"<h1>Ошибка: {str(e)}</h1>"

@app.post("/api/start-bot")
async def start_bot(payload: StartBotPayload, request: Request):
    try:
        token = payload.token
        graph = payload.graph

        BOT_CONFIGS[token] = graph

        host_url = str(request.base_url).rstrip('/')
        webhook_url = f"{host_url}/api/webhook/{token}"
        
        tg_url = f"https://api.telegram.org/bot{token}/setWebhook?url={webhook_url}"
        res = requests.get(tg_url).json()

        if res.get("ok"):
            return {"success": True, "message": "Бот обновлен и готов к работе!"}
        else:
            return JSONResponse({"success": False, "message": res.get("description")}, status_code=400)
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)

def normalize_cmd(text: str) -> str:
    text = text.lower().strip()
    if text.startswith("/"):
        text = text[1:]
    return text

def build_keyboard(btn_raw, btn_type, callback_id=""):
    if not btn_raw:
        return None
    buttons = [b.strip() for b in btn_raw.split(",") if b.strip()]
    if not buttons:
        return None

    if btn_type == "inline":
        inline_keyboard = [[{"text": btn_text, "callback_data": f"btn_{callback_id}_{idx}"}] for idx, btn_text in enumerate(buttons)]
        return {"inline_keyboard": inline_keyboard}
    else:
        reply_keyboard = [[{"text": btn_text}] for btn_text in buttons]
        return {"keyboard": reply_keyboard, "resize_keyboard": True}

def replace_vars(text: str, user_vars: dict) -> str:
    for var_name, var_val in user_vars.items():
        pattern = re.compile(rf"\{{{var_name}\}}", re.IGNORECASE)
        text = pattern.sub(str(var_val), text)
    return text

def get_next_node_id(node):
    outs = node.get("outputs", {}).get("output_1", {}).get("connections", [])
    if outs:
        return outs[0].get("node")
    return None

def process_node_execution(token, chat_id, node_id, drawflow_data):
    node = drawflow_data.get(node_id)
    if not node:
        return

    b_type = node.get("block_type", "message")
    
    if b_type == "trigger":
        next_id = get_next_node_id(node)
        if next_id:
            process_node_execution(token, chat_id, next_id, drawflow_data)
        return

    elif b_type == "message":
        send_url = f"https://api.telegram.org/bot{token}/sendMessage"
        raw_text = node.get("custom_text", "")
        final_text = replace_vars(raw_text, USER_DATA.get(chat_id, {}))
        
        btn_raw = node.get("custom_btn", "")
        btn_type = node.get("custom_type", "inline")
        next_id = get_next_node_id(node)

        payload = {"chat_id": chat_id, "text": final_text or "..."}
        markup = build_keyboard(btn_raw, btn_type, callback_id=next_id)
        if markup:
            payload["reply_markup"] = markup

        requests.post(send_url, json=payload)

    elif b_type == "input_var":
        send_url = f"https://api.telegram.org/bot{token}/sendMessage"
        raw_text = node.get("custom_text", "Введите значение:")
        final_text = replace_vars(raw_text, USER_DATA.get(chat_id, {}))

        USER_STATES[chat_id] = node_id

        payload = {"chat_id": chat_id, "text": final_text}
        requests.post(send_url, json=payload)

    elif b_type == "media":
        media_url = node.get("custom_media_url", "")
        media_type = node.get("custom_media_type", "document")
        raw_caption = node.get("custom_text", "")
        caption = replace_vars(raw_caption, USER_DATA.get(chat_id, {}))

        endpoint = "sendPhoto" if media_type == "photo" else "sendDocument"
        field_name = "photo" if media_type == "photo" else "document"
        send_url = f"https://api.telegram.org/bot{token}/{endpoint}"

        if media_url:
            payload = {
                "chat_id": chat_id,
                field_name: media_url,
                "caption": caption
            }
            requests.post(send_url, json=payload)

        next_id = get_next_node_id(node)
        if next_id:
            process_node_execution(token, chat_id, next_id, drawflow_data)

@app.post("/api/webhook/{token}")
async def handle_webhook(token: str, request: Request):
    try:
        data = await request.json()
        graph = BOT_CONFIGS.get(token, {})
        drawflow_data = graph.get("drawflow", {}).get("Home", {}).get("data", {})

        chat_id = None
        user_input = None
        clicked_target_node = None

        if "message" in data:
            chat_id = str(data["message"]["chat"]["id"])
            user_input = data["message"].get("text", "").strip()
        elif "callback_query" in data:
            chat_id = str(data["callback_query"]["message"]["chat"]["id"])
            callback_data = data["callback_query"].get("data", "")
            if callback_data.startswith("btn_"):
                parts = callback_data.split("_")
                if len(parts) >= 2:
                    clicked_target_node = parts[1]

        if chat_id and drawflow_data:
            if chat_id not in USER_DATA:
                USER_DATA[chat_id] = {}

            if clicked_target_node:
                process_node_execution(token, chat_id, clicked_target_node, drawflow_data)

            elif chat_id in USER_STATES and user_input:
                waiting_node_id = USER_STATES.pop(chat_id)
                current_node = drawflow_data.get(waiting_node_id)

                if current_node:
                    var_name = current_node.get("custom_var")
                    if var_name:
                        USER_DATA[chat_id][var_name] = user_input

                    next_id = get_next_node_id(current_node)
                    if next_id:
                        process_node_execution(token, chat_id, next_id, drawflow_data)

            elif user_input:
                clean_input = normalize_cmd(user_input)

                for node_id, node in drawflow_data.items():
                    b_type = node.get("block_type", "")
                    
                    if b_type == "trigger":
                        trg = normalize_cmd(node.get("custom_trigger", ""))
                        if trg and clean_input == trg:
                            process_node_execution(token, chat_id, node_id, drawflow_data)
                            break
                    
                    elif b_type == "message":
                        btns = [normalize_cmd(b) for b in node.get("custom_btn", "").split(",") if b.strip()]
                        if clean_input in btns:
                            next_id = get_next_node_id(node)
                            if next_id:
                                process_node_execution(token, chat_id, next_id, drawflow_data)
                            break

        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
