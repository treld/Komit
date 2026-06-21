import json
import sys
import os
import urllib.request
import requests
import threading
import time
from PyQt5 import QtCore, QtWidgets, QtWebEngineWidgets, QtGui


class FramelessWindow(QtWidgets.QMainWindow):
    """Окно без рамок с кастомным заголовком"""

    def __init__(self, url, port):
        super().__init__()
        self.url = url
        self.port = port
        self.drag_pos = None
        self.is_shutting_down = False
        self.init_ui()

    def init_ui(self):
        # Убираем флаг WindowStaysOnTopHint - теперь окно будет вести себя нормально
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.WindowCloseButtonHint  # Добавляем кнопку закрытия в системное меню
        )

        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)

        central_widget = QtWidgets.QWidget()
        central_widget.setObjectName("centralWidget")
        self.setCentralWidget(central_widget)

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        central_widget.setLayout(layout)

        # Заголовок
        title_bar = QtWidgets.QWidget()
        title_bar.setObjectName("titleBar")
        title_bar.setFixedHeight(42)
        title_bar_layout = QtWidgets.QHBoxLayout()
        title_bar_layout.setContentsMargins(12, 0, 12, 0)
        title_bar_layout.setSpacing(8)
        title_bar.setLayout(title_bar_layout)

        # Иконка
        icon_label = QtWidgets.QLabel("🚀")
        icon_label.setStyleSheet("""
            QLabel {
                color: #e6edf3;
                font-size: 16px;
            }
        """)
        title_bar_layout.addWidget(icon_label)

        # Название
        title_label = QtWidgets.QLabel("Komit — Менеджер плагинов")
        title_label.setObjectName("titleLabel")
        title_label.setStyleSheet("""
            QLabel {
                color: #e6edf3;
                font-size: 14px;
                font-weight: 600;
                font-family: 'Inter', -apple-system, sans-serif;
            }
        """)
        title_bar_layout.addWidget(title_label)

        title_bar_layout.addStretch()

        # Кнопка свернуть
        self.minimize_btn = QtWidgets.QPushButton("─")
        self.minimize_btn.setFixedSize(32, 32)
        self.minimize_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.minimize_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #8b949e;
                border: none;
                font-size: 16px;
                font-weight: 300;
                border-radius: 6px;
            }
            QPushButton:hover {
                background: #1c2333;
                color: #e6edf3;
            }
        """)
        self.minimize_btn.clicked.connect(self.showMinimized)
        title_bar_layout.addWidget(self.minimize_btn)

        # Кнопка закрыть
        self.close_btn = QtWidgets.QPushButton("✕")
        self.close_btn.setFixedSize(32, 32)
        self.close_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.close_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #8b949e;
                border: none;
                font-size: 16px;
                font-weight: 300;
                border-radius: 6px;
            }
            QPushButton:hover {
                background: #da3633;
                color: white;
            }
        """)
        self.close_btn.clicked.connect(self.shutdown)
        title_bar_layout.addWidget(self.close_btn)

        layout.addWidget(title_bar)

        # WebView с анимацией загрузки
        self.browser = QtWebEngineWidgets.QWebEngineView()
        self.browser.setUrl(QtCore.QUrl(self.url))
        self.browser.page().settings().setAttribute(
            QtWebEngineWidgets.QWebEngineSettings.ScrollAnimatorEnabled, False
        )

        # Добавляем индикатор загрузки
        self.browser.loadStarted.connect(self.on_load_started)
        self.browser.loadFinished.connect(self.on_load_finished)

        layout.addWidget(self.browser)

        # Стили
        self.setStyleSheet("""
            QMainWindow {
                background: transparent;
            }
            #centralWidget {
                background: #0d1117;
                border: 1px solid #1c2333;
                border-radius: 12px;
            }
            #titleBar {
                background: #0d1117;
                border-top-left-radius: 12px;
                border-top-right-radius: 12px;
            }
            QWebEngineView {
                background: #0a0e17;
                border-bottom-left-radius: 12px;
                border-bottom-right-radius: 12px;
            }
        """)

        self.resize(1200, 800)

        # Центрируем
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)

    def on_load_started(self):
        """Начало загрузки"""
        self.setWindowTitle("Komit — Загрузка...")

    def on_load_finished(self, ok):
        """Загрузка завершена"""
        if ok:
            self.setWindowTitle("Komit — Менеджер плагинов")
        else:
            self.setWindowTitle("Komit — Ошибка загрузки")

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.drag_pos = event.globalPos()

    def mouseMoveEvent(self, event):
        if self.drag_pos is not None:
            delta = event.globalPos() - self.drag_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.drag_pos = event.globalPos()

    def mouseReleaseEvent(self, event):
        self.drag_pos = None

    def closeEvent(self, event):
        """Перехватываем событие закрытия окна с анимацией"""
        if not self.is_shutting_down:
            event.ignore()
            self.shutdown()
        else:
            event.accept()

    def shutdown(self):
        """Завершение работы с анимацией"""
        if self.is_shutting_down:
            return

        self.is_shutting_down = True

        # Показываем сообщение о завершении
        print("🔄 Остановка всех плагинов...")

        # Отправляем запрос на завершение сервера в отдельном потоке
        def send_shutdown():
            try:
                response = requests.post(
                    f"http://localhost:{self.port}/api/shutdown",
                    timeout=2,
                    json={"from_window": True}
                )
                print("✅ Сервер получил команду на завершение")
            except requests.exceptions.RequestException as e:
                print(f"⚠️ Ошибка при отправке команды завершения: {e}")
            except Exception as e:
                print(f"⚠️ Неизвестная ошибка: {e}")

            # Закрываем окно с задержкой
            QtCore.QTimer.singleShot(500, self.close_window)

        # Запускаем в отдельном потоке, чтобы не блокировать UI
        threading.Thread(target=send_shutdown, daemon=True).start()

    def close_window(self):
        """Закрываем окно"""
        self.close()
        # Завершаем приложение
        QtWidgets.QApplication.quit()


class OverlayApp:
    def __init__(self, port=8080):
        self.port = port
        self.url = f"http://localhost:{self.port}/"
        self.run()

    def run(self):
        # Проверяем сервер с прогрессом
        attempts = 0
        max_attempts = 10

        while attempts < max_attempts:
            try:
                urllib.request.urlopen(f"http://localhost:{self.port}", timeout=1)
                break
            except:
                attempts += 1
                if attempts == max_attempts:
                    reply = QtWidgets.QMessageBox.question(
                        None,
                        "Сервер не запущен",
                        f"Сервер на порту {self.port} не отвечает.\n\n"
                        "Убедитесь, что Komit запущен.\n"
                        "Попробовать переподключиться?",
                        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
                    )
                    if reply == QtWidgets.QMessageBox.No:
                        sys.exit(0)
                    else:
                        QtCore.QTimer.singleShot(2000, self.run)
                        return
                time.sleep(0.5)

        app = QtWidgets.QApplication.instance()
        if not app:
            app = QtWidgets.QApplication(sys.argv)

        window = FramelessWindow(self.url, self.port)
        window.show()

        sys.exit(app.exec_())


def runwindowkomit(port):
    app = OverlayApp(port)