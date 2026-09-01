import json
import threading
from flask import Flask, render_template_string, request, jsonify
from telebot import TeleBot

app = Flask(__name__)

# Глобальные переменные для управления активным ботом
current_bot_thread = None
active_bot_instance = None
bot_running = False

def run_bot(token, graph_data):
    """Фоновая функция запуска бота и обработки сообщений по графу"""
    global bot_running
    try:
        bot = TeleBot(token)
        bot_running = True
        print(f"[+] Бот успешно запущен!")

        # Поиск стартового узла в схеме
        nodes = graph_data.get("nodes", {})
        start_node_id = graph_data.get("start_node", "node_1")

        @bot.message_handler(commands=['start'])
        def handle_start(message):
            if start_node_id in nodes:
                node = nodes[start_node_id]
                bot.send_message(message.chat.id, node.get("text", "Привет!"))

        @bot.message_handler(func=lambda msg: True)
        def handle_all_messages(message):
            # Простой эхо-ответ для проверки динамической логики
            bot.send_message(message.chat.id, f"Вы написали: {message.text}")

        bot.infinity_polling()
    except Exception as e:
        print(f"[-] Ошибка работы бота: {e}")
        bot_running = False

@app.route('/')
def index():
    """Считывание index.html и отображение страницы"""
    with open("index.html", "r", encoding="utf-8") as f:
        html_content = f.read()
    return render_template_string(html_content)

@app.route('/api/start-bot', methods=['POST'])
def start_bot():
    """Эндпоинт для приема токена и схемы бота из конструктора"""
    global current_bot_thread, bot_running
    data = request.json or {}
    token = data.get("token")
    graph = data.get("graph")

    if not token:
        return jsonify({"success": False, "message": "Токен не указан!"}), 400

    # Сохраняем в config.json для локальной отладки
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump({"token": token, "graph": graph}, f, ensure_ascii=False, indent=2)

    # Запускаем бота в отдельном потоке
    thread = threading.Thread(target=run_bot, args=(token, graph), daemon=True)
    thread.start()

    return jsonify({"success": True, "message": "Бот успешно запущен!"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
