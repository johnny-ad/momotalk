#!/bin/bash
# MomoTalk IRL — Quick Start
# Run this with: bash start.sh

# Create venv if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Setting up virtual environment..."
    python3 -m venv venv
fi

# Always activate and install deps
source venv/bin/activate
pip install -r requirements.txt --quiet
pip install "python-telegram-bot[job-queue]" --quiet
pip install --upgrade anthropic httpx --quiet

# Copy .env from template if it doesn't exist
if [ ! -f ".env" ]; then
    # Try to find .env from previous version folders
    FOUND_ENV=""
    for dir in ../momotalk-irl-v* ../momotalk-irl-v*\ * ../momotalk; do
        if [ -f "$dir/.env" ]; then
            FOUND_ENV="$dir/.env"
        fi
    done

    if [ -n "$FOUND_ENV" ]; then
        echo "Found .env from previous version: $FOUND_ENV"
        cp "$FOUND_ENV" .env
        echo "Copied. Starting bots..."
    else
        echo "No .env file found. Copying template..."
        cp .env.example .env
        echo "Fill in your tokens in .env, then run this script again."
        exit 1
    fi
fi

# Run all bots
python run.py all
