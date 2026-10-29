#!/data/data/com.termux/files/usr/bin/bash
# Запускается по расписанию termux-job-scheduler (см. setup.sh).
cd "$(dirname "$0")"
python cleaner.py --apply --quiet >> "$HOME/.phone_cleaner.log" 2>&1
