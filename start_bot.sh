#!/bin/bash

# Session name
SESSION_NAME="Link2Video-bot"

# File path
BOT_PATH="source ~/Link2Video-bot/.venv/bin/activate; cd ~/Link2Video-bot && python3 ~/Link2Video-bot/bot_main.py"

# Window name
WINDOW_NAME="link2Video-bot"

# Check if session exists
if ! tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
	# Create a new session and window
	tmux new-session -d -s "$SESSION_NAME" -n "$WINDOW_NAME" bash
fi

# go to session and window tmux
tmux send-keys -t "$SESSION_NAME:$WINDOW_NAME" "$BOT_PATH" C-m

# attach to session
#tmux attach-session -t "$SESSION_NAME"

