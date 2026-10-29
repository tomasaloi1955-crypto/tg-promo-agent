#!/data/data/com.termux/files/usr/bin/bash
# Установка агента-уборщика в Termux. Запуск: bash setup.sh
set -e
cd "$(dirname "$0")"

pkg install -y python termux-api
# доступ к памяти телефона (появится системный запрос — нажмите «Разрешить»)
[ -d /storage/emulated/0 ] && [ -r /storage/emulated/0 ] || termux-setup-storage

python cleaner.py > /dev/null || true   # создаёт config.json с настройками по умолчанию

# автоуборка раз в неделю (переживает перезагрузку телефона)
termux-job-scheduler --job-id 7101 --cancel >/dev/null 2>&1 || true
termux-job-scheduler --job-id 7101 --script "$PWD/run_weekly.sh" \
    --period-ms 604800000 --persisted true --battery-not-low true

echo
echo "Готово. Сначала посмотрите отчёт:   python $PWD/cleaner.py"
echo "Убрать мусор:                       python $PWD/cleaner.py --apply"
echo "Вернуть последнюю уборку:           python $PWD/cleaner.py restore"
echo "Раз в неделю уборка будет запускаться сама (уведомление придёт в шторку)."
