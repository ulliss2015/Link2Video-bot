#!/bin/bash

# Имя сессии tmux (можно изменить на ваше предпочтение)
SESSION_NAME="Link2Video-bot"

# Путь к файлу 
BOT_PATH="source .venv/bin/activate && python3 bot_main.py"

# Название окна tmux (можно изменить на ваше предпочтение)
WINDOW_NAME="link2Video-bot"

# Проверяем, существует ли сессия tmux
if ! tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
	# Если сессия не существует, создаем ее
	tmux new-session -d -s "$SESSION_NAME" -n "$WINDOW_NAME"
fi

# Переходим в сессию и окно tmux
tmux send-keys -t "$SESSION_NAME:$WINDOW_NAME" "$BOT_PATH" C-m

# Переключаемся в сессию tmux
#tmux attach-session -t "$SESSION_NAME"

