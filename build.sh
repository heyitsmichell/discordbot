#!/usr/bin/env bash
# Install system dependencies required by the music cog and voice support
apt-get update && apt-get install -y --no-install-recommends ffmpeg libopus0 libopus-dev libsodium-dev libffi-dev python3-dev || true

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt
