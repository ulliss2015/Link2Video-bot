#!/bin/bash

# Session name
SESSION_NAME="Link2Video-bot"

# File path
#BOT_PATH="source ~/Link2Video-bot/.venv/bin/activate; cd ~/Link2Video-bot && python3 ~/Link2Video-bot/bot_main.py"
BOT_CMD="source $BOT_DIR/.venv/bin/activate && cd $BOT_DIR && python3 bot_main.py"

# Window name
WINDOW_NAME="link2Video-bot"
BOT_DIR="$HOME/Link2Video-bot"
COOKIES_SOURCE="$HOME/cookies.txt"
COOKIES_DEST="$BOT_DIR/cookies.txt"

# Checking Cookies source
if [ -f "$COOKIES_SOURCE" ]; then
    cp -f "$COOKIES_SOURCE" "$COOKIES_DEST"
    echo "File cookies.txt copied to $BOT_DIR/"
else
    echo "Error: file $COOKIES_SOURCE not found!"
    exit 1
fi

# Check if session exists
if ! tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
	# Create a new session and window
	tmux new-session -d -s "$SESSION_NAME" -n "$WINDOW_NAME" bash
fi

# go to session and window tmux
#tmux send-keys -t "$SESSION_NAME:$WINDOW_NAME" "$BOT_PATH" C-m
tmux send-keys -t "$SESSION_NAME:$WINDOW_NAME" "$BOT_CMD" C-m

echo “Done! Tmux session ‘$SESSION_NAME’ started.”

# attach to session
#tmux attach-session -t "$SESSION_NAME"

