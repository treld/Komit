import os
import json
import shutil
import zipfile
import requests
import subprocess
import sys
import threading
import time
import atexit
import signal
import webbrowser
import tempfile
import logging
from pathlib import Path
from flask import Flask, render_template, jsonify, request, send_file, send_from_directory
from datetime import datetime

# Настройка логирования
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

log_file = log_dir / f"komit_{datetime.now().strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Конфигурация
PLUGINS_DIR = Path("plugins")
REGISTRY_FILE = Path("registry.json")
PLUGINS_REGISTRY_URL = "https://cdn.jsdelivr.net/gh/treld/Komit@main/plugins_registry.json"
PORT = 8080
STATIC_FOLDER = Path("static")

# Создаём папки
PLUGINS_DIR.mkdir(exist_ok=True)
STATIC_FOLDER.mkdir(exist_ok=True)

# Хранилище запущенных плагинов
running_plugins = {}
plugin_processes = []
stop_event = threading.Event()
is_shutting_down = False


def load_local_registry():
    """Загружает локальный реестр"""
    if REGISTRY_FILE.exists():
        try:
            with open(REGISTRY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки реестра: {e}")
            return {"installed": []}
    return {"installed": []}


def save_local_registry(registry):
    """Сохраняет локальный реестр"""
    try:
        with open(REGISTRY_FILE, 'w', encoding='utf-8') as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)
        logger.info(f"Реестр сохранен: {len(registry.get('installed', []))} плагинов")
    except Exception as e:
        logger.error(f"Ошибка сохранения реестра: {e}")


def scan_plugins_folder():
    """Сканирует папку plugins и добавляет найденные плагины в реестр"""
    local = load_local_registry()
    installed = local.get("installed", [])
    found = []

    if PLUGINS_DIR.exists():
        for item in PLUGINS_DIR.iterdir():
            if item.is_dir():
                manifest_path = item / "manifest.json"
                if manifest_path.exists():
                    plugin_id = item.name
                    found.append(plugin_id)
                    if plugin_id not in installed:
                        installed.append(plugin_id)
                        logger.info(f"Найден новый плагин: {plugin_id}")

    local["installed"] = installed
    save_local_registry(local)
    logger.info(f"Просканировано плагинов: {len(found)}")
    return installed


def get_plugin_info(plugin_id):
    """Получает информацию из manifest.json"""
    plugin_path = PLUGINS_DIR / plugin_id
    manifest_path = plugin_path / "manifest.json"

    if not manifest_path.exists():
        return None

    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)

        icon_path = plugin_path / "icon.png"
        manifest["_has_icon"] = icon_path.exists()

        # Проверяем, запущен ли плагин
        is_running = plugin_id in running_plugins
        process_id = None
        if is_running:
            process = running_plugins[plugin_id]
            if process.poll() is None:
                process_id = process.pid
            else:
                # Процесс завершился, удаляем из списка
                del running_plugins[plugin_id]
                is_running = False

        manifest["_is_running"] = is_running
        manifest["_process_id"] = process_id

        return manifest
    except Exception as e:
        logger.error(f"Ошибка чтения manifest для {plugin_id}: {e}")
        return None


def get_installed_plugins():
    """Возвращает список установленных плагинов"""
    scan_plugins_folder()
    local = load_local_registry()
    installed = []

    for plugin_id in local.get("installed", []):
        info = get_plugin_info(plugin_id)
        if info:
            installed.append({
                "id": plugin_id,
                "name": info.get("name", plugin_id),
                "version": info.get("version", "unknown"),
                "author": info.get("author", "unknown"),
                "description": info.get("description", ""),
                "port": info.get("port", None),
                "main_file": info.get("main_file", "main.py"),
                "icon": info.get("icon", ""),
                "_has_icon": info.get("_has_icon", False),
                "is_running": info.get("_is_running", False),
                "process_id": info.get("_process_id", None)
            })

    return installed


def fetch_plugins_registry():
    """Загружает список плагинов из сети"""
    try:
        logger.info("Загрузка реестра плагинов...")
        response = requests.get(PLUGINS_REGISTRY_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        logger.info(f"Загружено {len(data.get('plugins', []))} плагинов")
        return data
    except Exception as e:
        logger.error(f"Ошибка загрузки реестра: {e}")
        return None


def download_plugin(plugin_id, download_url):
    """Скачивает и устанавливает плагин"""
    try:
        logger.info(f"Скачивание плагина: {plugin_id}")

        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp:
            response = requests.get(download_url, stream=True)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0

            for chunk in response.iter_content(chunk_size=8192):
                tmp.write(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    progress = (downloaded / total_size) * 100
                    if progress % 10 < 1:
                        logger.info(f"Загрузка: {progress:.1f}%")

            tmp_path = tmp.name

        extract_path = PLUGINS_DIR / plugin_id
        if extract_path.exists():
            shutil.rmtree(extract_path)

        with zipfile.ZipFile(tmp_path, 'r') as zip_ref:
            zip_ref.extractall(extract_path)

        manifest_path = extract_path / "manifest.json"
        if not manifest_path.exists():
            os.unlink(tmp_path)
            shutil.rmtree(extract_path)
            return False, "manifest.json не найден в архиве"

        os.unlink(tmp_path)

        local = load_local_registry()
        if plugin_id not in local["installed"]:
            local["installed"].append(plugin_id)
        save_local_registry(local)

        logger.info(f"Плагин {plugin_id} успешно установлен")
        return True, "Плагин успешно установлен"

    except Exception as e:
        logger.error(f"Ошибка установки {plugin_id}: {e}")
        return False, f"Ошибка: {str(e)}"


def uninstall_plugin(plugin_id):
    """Удаляет плагин"""
    try:
        logger.info(f"Удаление плагина: {plugin_id}")

        if plugin_id in running_plugins:
            stop_plugin(plugin_id)

        plugin_path = PLUGINS_DIR / plugin_id
        if plugin_path.exists():
            shutil.rmtree(plugin_path)

        local = load_local_registry()
        if plugin_id in local["installed"]:
            local["installed"].remove(plugin_id)
        save_local_registry(local)

        logger.info(f"Плагин {plugin_id} удален")
        return True, "Плагин удалён"
    except Exception as e:
        logger.error(f"Ошибка удаления {plugin_id}: {e}")
        return False, f"Ошибка: {str(e)}"


def find_free_port():
    """Находит свободный порт"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

def start_plugin(plugin_id):
    """Запускает плагин"""
    try:
        if plugin_id in running_plugins:
            process = running_plugins[plugin_id]
            if process.poll() is None:
                return False, "Плагин уже запущен"
            else:
                del running_plugins[plugin_id]

        plugin_path = PLUGINS_DIR / plugin_id
        manifest_path = plugin_path / "manifest.json"

        if not manifest_path.exists():
            return False, "manifest.json не найден"

        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)

        main_file = manifest.get("main_file", "main.py")
        main_path = plugin_path / main_file

        if not main_path.exists():
            return False, f"Файл {main_file} не найден"

        plugin_port = manifest.get("port")
        if not plugin_port:
            plugin_port = find_free_port()
            manifest["port"] = plugin_port
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)

        # Добавляем переменные окружения
        env = os.environ.copy()
        env['PORT'] = str(plugin_port)
        env['PLUGIN_PORT'] = str(plugin_port)
        env['PLUGIN_ID'] = plugin_id
        env['PYTHONUNBUFFERED'] = '1'
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUTF8'] = '1'

        logger.info(f"🚀 Запуск плагина: {plugin_id}")
        logger.info(f"   Порт: {plugin_port}")
        logger.info(f"   Файл: {main_file}")
        logger.info(f"   Рабочая папка: {plugin_path}")

        # Создаем отдельный процесс для плагина
        if sys.platform == "win32":
            process = subprocess.Popen(
                [sys.executable, "-u", main_file],
                cwd=str(plugin_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW,
                bufsize=0
            )
        else:
            process = subprocess.Popen(
                [sys.executable, "-u", main_file],
                cwd=str(plugin_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                env=env,
                bufsize=0
            )

        running_plugins[plugin_id] = process
        plugin_processes.append(process)

        # Запускаем поток для чтения вывода
        def read_output():
            try:
                while True:
                    if process.poll() is not None:
                        break

                    line = process.stdout.readline()
                    if line:
                        line = line.strip()
                        if line:
                            print(f"[{plugin_id}] {line}")
                            logger.info(f"[{plugin_id}] {line}")
                    else:
                        time.sleep(0.01)
            except Exception as e:
                print(f"[{plugin_id}] Ошибка чтения вывода: {e}")
                logger.error(f"[{plugin_id}] Ошибка чтения вывода: {e}")
            finally:
                if plugin_id in running_plugins:
                    del running_plugins[plugin_id]
                if process in plugin_processes:
                    plugin_processes.remove(process)

        thread = threading.Thread(target=read_output, daemon=True)
        thread.start()

        # Даем время на запуск
        time.sleep(3)

        if process.poll() is not None:
            return False, f"Плагин завершился с кодом {process.poll()}"

        logger.info(f"✅ Плагин {plugin_id} запущен на порту {plugin_port} (PID: {process.pid})")
        return True, f"Плагин запущен на порту {plugin_port} (PID: {process.pid})"

    except Exception as e:
        error_msg = f"Ошибка запуска {plugin_id}: {e}"
        logger.error(error_msg)
        import traceback
        traceback.print_exc()
        return False, f"Ошибка: {str(e)}"


def stop_plugin(plugin_id):
    """Останавливает плагин"""
    try:
        if plugin_id not in running_plugins:
            return False, "Плагин не запущен"

        process = running_plugins[plugin_id]
        logger.info(f"Остановка плагина: {plugin_id} (PID: {process.pid})")

        process.terminate()

        # Ждем завершения
        for _ in range(10):
            if process.poll() is not None:
                break
            time.sleep(0.1)

        if process.poll() is None:
            process.kill()

        if process in plugin_processes:
            plugin_processes.remove(process)

        if plugin_id in running_plugins:
            del running_plugins[plugin_id]

        logger.info(f"✅ Плагин {plugin_id} остановлен")
        return True, "Плагин остановлен"

    except Exception as e:
        logger.error(f"Ошибка остановки {plugin_id}: {e}")
        return False, f"Ошибка: {str(e)}"


def check_updates():
    """Проверяет обновления"""
    remote = fetch_plugins_registry()
    if not remote:
        return []

    local = load_local_registry()
    updates = []

    for plugin_data in remote.get("plugins", []):
        plugin_id = plugin_data.get("id")
        if plugin_id in local.get("installed", []):
            local_info = get_plugin_info(plugin_id)
            if local_info:
                local_version = local_info.get("version", "0.0.0")
                remote_version = plugin_data.get("version", "0.0.0")
                if local_version != remote_version:
                    updates.append({
                        "id": plugin_id,
                        "name": plugin_data.get("name", plugin_id),
                        "local_version": local_version,
                        "remote_version": remote_version,
                        "download_url": plugin_data.get("download_url")
                    })

    return updates


def update_plugin(plugin_id, download_url):
    """Обновляет плагин"""
    if plugin_id in running_plugins:
        stop_plugin(plugin_id)

    plugin_path = PLUGINS_DIR / plugin_id
    if plugin_path.exists():
        shutil.rmtree(plugin_path)

    return download_plugin(plugin_id, download_url)


def cleanup():
    """Очистка при завершении"""
    global is_shutting_down

    if is_shutting_down:
        return

    is_shutting_down = True
    logger.info("🔄 Остановка всех плагинов...")

    stopped_count = 0
    for plugin_id in list(running_plugins.keys()):
        try:
            stop_plugin(plugin_id)
            stopped_count += 1
        except Exception as e:
            logger.error(f"Ошибка при остановке {plugin_id}: {e}")

    logger.info(f"✅ Остановлено плагинов: {stopped_count}")
    logger.info("👋 Komit завершил работу")


def signal_handler(signum, frame):
    """Обработчик сигналов"""
    logger.info("⚠️ Получен сигнал завершения")
    cleanup()
    sys.exit(0)


atexit.register(cleanup)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# ========== Flask Routes ==========

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/static/<path:filename>')
def serve_static(filename):
    """Отдача статических файлов"""
    return send_from_directory('static', filename)


@app.route('/plugins/<plugin_id>/icon.png')
def serve_plugin_icon(plugin_id):
    """Отдача иконки плагина"""
    icon_path = PLUGINS_DIR / plugin_id / "icon.png"
    if icon_path.exists():
        return send_file(icon_path, mimetype='image/png')
    return "", 404


@app.route('/api/plugins')
def api_plugins():
    """Полный список плагинов"""
    remote_data = fetch_plugins_registry()
    remote_plugins = remote_data.get("plugins", []) if remote_data else []

    installed = get_installed_plugins()
    installed_ids = {p["id"] for p in installed}
    installed_map = {p["id"]: p for p in installed}
    updates = {u["id"]: u for u in check_updates()}

    all_plugins = []

    # Установленные плагины
    for plugin in installed:
        plugin_data = {
            **plugin,
            "is_installed": True,
            "has_update": plugin["id"] in updates,
            "remote_version": updates[plugin["id"]]["remote_version"] if plugin["id"] in updates else None,
            "is_running": plugin["is_running"],
            "icon_url": f"/plugins/{plugin['id']}/icon.png" if plugin.get("_has_icon") else ""
        }
        all_plugins.append(plugin_data)

    # Доступные плагины
    for remote in remote_plugins:
        plugin_id = remote.get("id")
        if plugin_id not in installed_ids:
            all_plugins.append({
                "id": plugin_id,
                "name": remote.get("name", plugin_id),
                "version": remote.get("version", "unknown"),
                "author": remote.get("author", "unknown"),
                "description": remote.get("description", ""),
                "icon": remote.get("icon", ""),
                "icon_url": "",
                "download_url": remote.get("download_url", ""),
                "is_installed": False,
                "has_update": False,
                "is_running": False
            })

    return jsonify(all_plugins)


@app.route('/api/install', methods=['POST'])
def api_install():
    data = request.json
    plugin_id = data.get('id')
    download_url = data.get('download_url')

    if not plugin_id or not download_url:
        return jsonify({"success": False, "message": "Недостаточно данных"})

    success, message = download_plugin(plugin_id, download_url)
    return jsonify({"success": success, "message": message})


@app.route('/api/uninstall', methods=['POST'])
def api_uninstall():
    data = request.json
    plugin_id = data.get('id')

    if not plugin_id:
        return jsonify({"success": False, "message": "ID не указан"})

    success, message = uninstall_plugin(plugin_id)
    return jsonify({"success": success, "message": message})


@app.route('/api/start', methods=['POST'])
def api_start():
    data = request.json
    plugin_id = data.get('id')

    if not plugin_id:
        return jsonify({"success": False, "message": "ID не указан"})

    success, message = start_plugin(plugin_id)
    return jsonify({"success": success, "message": message})


@app.route('/api/process/<plugin_id>')
def api_process_info(plugin_id):
    """Информация о процессе плагина"""
    if plugin_id not in running_plugins:
        return jsonify({"running": False})

    process = running_plugins[plugin_id]
    return jsonify({
        "running": True,
        "pid": process.pid,
        "poll": process.poll(),
        "is_running": process.poll() is None
    })

@app.route('/api/stop', methods=['POST'])
def api_stop():
    data = request.json
    plugin_id = data.get('id')

    if not plugin_id:
        return jsonify({"success": False, "message": "ID не указан"})

    success, message = stop_plugin(plugin_id)
    return jsonify({"success": success, "message": message})


@app.route('/api/update', methods=['POST'])
def api_update():
    data = request.json
    plugin_id = data.get('id')
    download_url = data.get('download_url')

    if not plugin_id or not download_url:
        return jsonify({"success": False, "message": "Недостаточно данных"})

    success, message = update_plugin(plugin_id, download_url)
    return jsonify({"success": success, "message": message})


@app.route('/api/check_updates')
def api_check_updates():
    updates = check_updates()
    return jsonify({"updates": updates, "count": len(updates)})


@app.route('/api/open_plugin/<plugin_id>')
def api_open_plugin(plugin_id):
    """Открывает плагин в браузере"""
    try:
        if plugin_id not in running_plugins:
            return jsonify({"success": False, "message": "Плагин не запущен"})

        plugin_path = PLUGINS_DIR / plugin_id
        manifest_path = plugin_path / "manifest.json"

        if not manifest_path.exists():
            return jsonify({"success": False, "message": "manifest.json не найден"})

        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)

        port = manifest.get("port")
        if not port:
            return jsonify({"success": False, "message": "Порт не указан"})

        url = f"http://localhost:{port}"
        webbrowser.open(url)

        return jsonify({"success": True, "url": url})
    except Exception as e:
        logger.error(f"Ошибка открытия {plugin_id}: {e}")
        return jsonify({"success": False, "message": str(e)})


@app.route('/api/config/<plugin_id>')
def api_get_config(plugin_id):
    config_path = PLUGINS_DIR / plugin_id / "config.json"
    if not config_path.exists():
        return jsonify({"exists": False})

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return jsonify({"exists": True, "config": config})
    except Exception as e:
        logger.error(f"Ошибка чтения конфига {plugin_id}: {e}")
        return jsonify({"exists": False, "error": "Ошибка чтения"})


@app.route('/api/config/<plugin_id>', methods=['POST'])
def api_save_config(plugin_id):
    config_path = PLUGINS_DIR / plugin_id / "config.json"
    data = request.json

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Сохранен конфиг для {plugin_id}")
        return jsonify({"success": True, "message": "Сохранено"})
    except Exception as e:
        logger.error(f"Ошибка сохранения конфига {plugin_id}: {e}")
        return jsonify({"success": False, "message": str(e)})


@app.route('/api/rescan')
def api_rescan():
    scan_plugins_folder()
    return jsonify({"success": True, "message": "Папка просканирована"})


@app.route('/api/shutdown', methods=['POST'])
def api_shutdown():
    """API для завершения работы"""

    def shutdown():
        time.sleep(0.5)
        cleanup()
        os._exit(0)

    thread = threading.Thread(target=shutdown)
    thread.daemon = True
    thread.start()
    return jsonify({"success": True, "message": "Завершение работы..."})


@app.route('/api/logs')
def api_get_logs():
    """Получает логи Komit"""
    try:
        log_file_path = log_dir / f"komit_{datetime.now().strftime('%Y%m%d')}.log"
        if not log_file_path.exists():
            return jsonify({"exists": False, "message": "Логи не найдены"})

        with open(log_file_path, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()

        return jsonify({
            "exists": True,
            "logs": lines[-200:],
            "total": len(lines)
        })
    except Exception as e:
        return jsonify({"exists": False, "error": str(e)})


@app.route('/api/plugin_logs/<plugin_id>')
def api_get_plugin_logs(plugin_id):
    """Получает логи плагина"""
    try:
        log_file_path = log_dir / plugin_id / f"{datetime.now().strftime('%Y%m%d')}.log"
        if not log_file_path.exists():
            return jsonify({"exists": False, "message": "Логи не найдены"})

        with open(log_file_path, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()

        return jsonify({
            "exists": True,
            "logs": lines[-200:],
            "total": len(lines)
        })
    except Exception as e:
        return jsonify({"exists": False, "error": str(e)})


@app.route('/api/status')
def api_status():
    """Статус системы"""
    return jsonify({
        "running_plugins": len(running_plugins),
        "plugin_processes": len(plugin_processes),
        "is_shutting_down": is_shutting_down,
        "plugins_dir": str(PLUGINS_DIR.absolute()),
        "port": PORT,
        "python": sys.executable
    })


def run_app():
    """Запуск приложения"""
    logger.info("Starting Flask server...")
    app.run(debug=False, host='127.0.0.1', port=PORT, threaded=True)


if __name__ == '__main__':
    scan_plugins_folder()

    print("=" * 60)
    print("🚀 Komit запущен!")
    print(f"📡 http://localhost:{PORT}")
    print(f"📁 Плагины: {PLUGINS_DIR.absolute()}")
    print(f"📝 Логи: {log_dir.absolute()}")
    print("💡 Нажмите ✕ в окне для завершения работы")
    print("=" * 60)
    print()

    logger.info("=" * 60)
    logger.info("🚀 Komit запущен!")
    logger.info(f"📡 http://localhost:{PORT}")
    logger.info(f"📁 Плагины: {PLUGINS_DIR.absolute()}")
    logger.info(f"📝 Логи: {log_dir.absolute()}")
    logger.info("=" * 60)

    # Запускаем Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_app, daemon=True)
    flask_thread.start()

    # Проверяем, что сервер запустился
    time.sleep(2)

    # Запускаем окно в основном потоке
    try:
        # Импортируем модуль для окна
        try:
            from ver2.window import runwindowkomit
            runwindowkomit(PORT)
        except ImportError:
            print("Окно не найдено, запуск в браузере...")
            webbrowser.open(f"http://localhost:{PORT}")
            # Держим процесс живым
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
    except KeyboardInterrupt:
        logger.info("\n⚠️ Прервано пользователем")
    except Exception as e:
        logger.error(f"Ошибка: {e}")
    finally:
        cleanup()
        logger.info("👋 До свидания!")