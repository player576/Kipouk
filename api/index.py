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

def build_dynamic_keyboard(buttons_list, btn_type, node_id):
    if not buttons_list:
        return None

    if btn_type == "inline":
        inline_keyboard = []
        for idx, btn_text in enumerate(buttons_list):
            output_num = idx + 1
            inline_keyboard.append([{
                "text": btn_text,
                "callback_data": f"btn_{node_id}_{output_num}"
            }])
        return {"inline_keyboard": inline_keyboard}
    else:
        reply_keyboard = [[{"text": btn_text}] for btn_text in buttons_list]
        return {"keyboard": reply_keyboard, "resize_keyboard": True}

def replace_vars(text: str, user_vars: dict) -> str:
    for var_name, var_val in user_vars.items():
        pattern = re.compile(rf"\{{{var_name}\}}", re.IGNORECASE)
        text = pattern.sub(str(var_val), text)
    return text

def get_node_connection_by_output(node, output_name="output_1"):
    outs = node.get("outputs", {}).get(output_name, {}).get("connections", [])
    if outs:
        return outs[0].get("node")
    return None

def extract_file_id_from_message(msg: dict) -> str:
    if "document" in msg:
        return msg["document"]["file_id"]
    elif "photo" in msg:
        return msg["photo"][-1]["file_id"]
    elif "audio" in msg:
        return msg["audio"]["file_id"]
    elif "video" in msg:
        return msg["video"]["file_id"]
    elif "voice" in msg:
        return msg["voice"]["file_id"]
    elif "sticker" in msg:
        return msg["sticker"]["file_id"]
    return ""

def process_node_execution(token, chat_id, node_id, drawflow_data):
    node = drawflow_data.get(node_id)
    if not node:
        return

    b_type = node.get("block_type", "message")
    
    if b_type == "trigger":
        next_id = get_node_connection_by_output(node, "output_1")
        if next_id:
            process_node_execution(token, chat_id, next_id, drawflow_data)
        return

    elif b_type == "message":
        send_url = f"https://api.telegram.org/bot{token}/sendMessage"
        raw_text = node.get("custom_text", "")
        final_text = replace_vars(raw_text, USER_DATA.get(chat_id, {}))
        
        buttons_list = node.get("custom_buttons_list", [])
        btn_type = node.get("custom_type", "inline")

        payload = {"chat_id": chat_id, "text": final_text or "..."}
        markup = build_dynamic_keyboard(buttons_list, btn_type, node_id)
        if markup:
            payload["reply_markup"] = markup

        requests.post(send_url, json=payload)

        # ЕСЛИ КНОПОК НЕТ: сразу автоматически переходим к следующему блоку по output_1
        if not buttons_list:
            next_id = get_node_connection_by_output(node, "output_1")
            if next_id:
                process_node_execution(token, chat_id, next_id, drawflow_data)

    elif b_type in ["input_var", "get_file_id"]:
        send_url = f"https://api.telegram.org/bot{token}/sendMessage"
        default_prompt = "Введите значение:" if b_type == "input_var" else "Отправьте файл:"
        raw_text = node.get("custom_text", default_prompt)
        final_text = replace_vars(raw_text, USER_DATA.get(chat_id, {}))

        USER_STATES[chat_id] = node_id

        payload = {"chat_id": chat_id, "text": final_text}
        requests.post(send_url, json=payload)

    elif b_type == "media":
        media_url_raw = node.get("custom_media_url", "")
        final_media_url = replace_vars(media_url_raw, USER_DATA.get(chat_id, {}))
        
        media_type = node.get("custom_media_type", "document")
        raw_caption = node.get("custom_text", "")
        caption = replace_vars(raw_caption, USER_DATA.get(chat_id, {}))

        endpoint = "sendPhoto" if media_type == "photo" else "sendDocument"
        field_name = "photo" if media_type == "photo" else "document"
        send_url = f"https://api.telegram.org/bot{token}/{endpoint}"

        if final_media_url:
            payload = {
                "chat_id": chat_id,
                field_name: final_media_url,
                "caption": caption
            }
            requests.post(send_url, json=payload)

        next_id = get_node_connection_by_output(node, "output_1")
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
        target_node_id = None
        output_port = "output_1"
        raw_msg = None

        if "message" in data:
            raw_msg = data["message"]
            chat_id = str(raw_msg["chat"]["id"])
            user_input = raw_msg.get("text", "").strip()
        elif "callback_query" in data:
            chat_id = str(data["callback_query"]["message"]["chat"]["id"])
            callback_data = data["callback_query"].get("data", "")
            if callback_data.startswith("btn_"):
                parts = callback_data.split("_")
                if len(parts) >= 3:
                    target_node_id = parts[1]
                    output_num = parts[2]
                    output_port = f"output_{output_num}"

        if chat_id and drawflow_data:
            if chat_id not in USER_DATA:
                USER_DATA[chat_id] = {}

            if target_node_id:
                next_id = get_node_connection_by_output(drawflow_data.get(target_node_id), output_port)
                if next_id:
                    process_node_execution(token, chat_id, next_id, drawflow_data)

            elif chat_id in USER_STATES:
                waiting_node_id = USER_STATES.pop(chat_id)
                current_node = drawflow_data.get(waiting_node_id)

                if current_node:
                    b_type = current_node.get("block_type", "")
                    var_name = current_node.get("custom_var") or "file_id"

                    if b_type == "input_var" and user_input:
                        USER_DATA[chat_id][var_name] = user_input
                    elif b_type == "get_file_id" and raw_msg:
                        extracted_id = extract_file_id_from_message(raw_msg)
                        if extracted_id:
                            USER_DATA[chat_id][var_name] = extracted_id
                        else:
                            USER_DATA[chat_id][var_name] = user_input or ""

                    next_id = get_node_connection_by_output(current_node, "output_1")
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
                        buttons_list = node.get("custom_buttons_list", [])
                        for idx, btn_text in enumerate(buttons_list):
                            if normalize_cmd(btn_text) == clean_input:
                                out_port = f"output_{idx + 1}"
                                next_id = get_node_connection_by_output(node, out_port)
                                if next_id:
                                    process_node_execution(token, chat_id, next_id, drawflow_data)
                                break

        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
