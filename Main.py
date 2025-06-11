import sqlite3
import sys
import logging
import os
import json
import asyncio
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QTextEdit,
    QMessageBox, QStackedWidget, QInputDialog, QSplitter, QFrame, QProgressDialog, QListWidgetItem
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QObject
from telethon import TelegramClient, errors
import discord
from qasync import QEventLoop, asyncSlot

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AsyncSignals(QObject):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

class AsyncWorker(QThread):
    def __init__(self, coroutine, parent=None):
        super().__init__(parent)
        self.coroutine = coroutine
        self.signals = AsyncSignals()

    def run(self):
        try:
            loop = asyncio.get_event_loop()
            result = loop.run_until_complete(self.coroutine)
            self.signals.finished.emit(result)
        except Exception as e:
            self.signals.error.emit(str(e))

import re  #Добавлено для проверки номера телефона

class TelegramLoginWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        self.phone_label = QLabel("Phone Number (with country code):")
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("+1234567890")
        self.api_id_label = QLabel("API ID:")
        self.api_id_input = QLineEdit()
        self.api_id_input.setText("")
        self.api_hash_label = QLabel("API Hash:")
        self.api_hash_input = QLineEdit()
        self.api_hash_input.setText("")
        self.login_button = QPushButton("Login to Telegram")
        self.login_button.clicked.connect(self.init_telegram_login)
        layout.addWidget(self.phone_label)
        layout.addWidget(self.phone_input)
        layout.addWidget(self.api_id_label)
        layout.addWidget(self.api_id_input)
        layout.addWidget(self.api_hash_label)
        layout.addWidget(self.api_hash_input)
        layout.addWidget(self.login_button)
        self.setLayout(layout)
        self.setStyleSheet("""
            QWidget { background-color: #E5F3FF; padding: 10px; }
            QLineEdit { border: 1px solid #40C4FF; border-radius: 5px; padding: 5px; }
            QPushButton { background-color: #40C4FF; color: white; border: none; padding: 8px; border-radius: 5px; }
            QPushButton:hover { background-color: #0288D1; }
            QLabel { color: #0288D1; font-weight: bold; }
        """)

    @asyncSlot()
    async def init_telegram_login(self):
        phone = self.phone_input.text().strip()
        api_id = self.api_id_input.text().strip()  # Исправлено: было phone_input
        api_hash = self.api_hash_input.text().strip()

        # Проверка заполненности полей
        if not all([phone, api_id, api_hash]):
            QMessageBox.warning(self, "Error", "Please fill in all Telegram fields.")
            return

        # Проверка формата номера телефона
        if not re.match(r'^\+\d{10,15}$', phone):
            QMessageBox.warning(self, "Error", "Invalid phone number format. Use: +1234567890")
            return

        self.parent.phone_number = phone
        self.parent.api_id = api_id
        self.parent.api_hash = api_hash

        # Очистка номера для имени файла
        safe_phone = re.sub(r'[^\d]', '', phone)  # Удаляем всё, кроме цифр
        session_path = f'sessions/{safe_phone}'

        # Проверка и создание папки sessions
        try:
            os.makedirs('sessions', exist_ok=True)
        except OSError as e:
            QMessageBox.critical(self, "Error", f"Failed to create sessions directory: {str(e)}")
            logger.error(f"Failed to create sessions directory: {str(e)}")
            return

        progress = None
        try:
            progress = QProgressDialog("Connecting to Telegram...", None, 0, 0, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.show()

            self.parent.telegram_client = TelegramClient(
                session_path, int(api_id), api_hash, system_version='5.15.2-vxCUSTOM'
            )
            await self.parent.connect_telegram()
            self.save_credentials()
            progress.close()
            self.parent.on_telegram_connected(True)
        except errors.FloodWaitError as e:
            if progress:
                progress.close()
            QMessageBox.critical(self, "Error", f"Too many attempts. Please wait {e.seconds} seconds.")
            logger.error(f"Telegram FloodWaitError: {str(e)}")
        except errors.PhoneNumberInvalidError:
            if progress:
                progress.close()
            QMessageBox.critical(self, "Error", "Invalid phone number. Please use format: +1234567890")
            logger.error(f"Telegram PhoneNumberInvalidError")
        except sqlite3.OperationalError as e:
            if progress:
                progress.close()
            QMessageBox.critical(self, "Error", f"Cannot access session file. Check permissions for 'sessions' directory: {str(e)}")
            logger.error(f"SQLite error: {str(e)}")
        except Exception as e:
            if progress:
                progress.close()
            QMessageBox.critical(self, "Error", f"Telegram login failed: {str(e)}")
            logger.error(f"Telegram login error: {str(e)}", exc_info=True)

    def save_credentials(self):
        creds = {
            'phone': self.parent.phone_number,
            'api_id': self.parent.api_id,
            'api_hash': self.parent.api_hash,
            'discord_token': self.parent.discord_token or ''
        }
        try:
            os.makedirs('sessions', exist_ok=True)
            safe_phone = re.sub(r'[^\d]', '', self.parent.phone_number)  # Очистка номера
            session_file = f'sessions/{safe_phone}_creds.json'  # Формируем путь
            with open(session_file, 'w') as f:
                json.dump(creds, f)
        except OSError as e:
            logger.error(f"Failed to save credentials: {str(e)}")

class TelegramChatWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        self.tg_chats_label = QLabel("Telegram Chats:")
        self.tg_chats_list = QListWidget() # Чаты
        self.tg_chats_list.itemClicked.connect(self._on_tg_chat_clicked)
        self.tg_messages_label = QLabel("Messages:")
        self.tg_messages_list = QListWidget() #Сообщения внутри
        self.tg_messages_list.itemDoubleClicked.connect(self._on_tg_message_double_clicked)
        self.message_preview_label = QLabel("Message Preview (from Discord):")  # Поле превью
        self.message_preview = QTextEdit()
        self.message_preview.setReadOnly(True)
        self.forward_button = QPushButton("Forward to Telegram")  # Кнопка для отправки из Discord
        self.forward_button.clicked.connect(self.forward_to_telegram)
        self.load_chats_button = QPushButton("Load Chats") # Загрузка чатов
        self.load_chats_button.clicked.connect(self.load_telegram_chats)
        self.logout_button = QPushButton("Log Out from Telegram") # Кнопка выхода из телеграм
        self.logout_button.clicked.connect(self.logout_telegram)
        layout.addWidget(self.tg_chats_label)
        layout.addWidget(self.tg_chats_list)
        layout.addWidget(self.tg_messages_label)
        layout.addWidget(self.tg_messages_list)
        layout.addWidget(self.message_preview_label)
        layout.addWidget(self.message_preview)
        layout.addWidget(self.forward_button)
        layout.addWidget(self.load_chats_button)
        layout.addWidget(self.logout_button)
        self.setLayout(layout)
        self.setStyleSheet("""
            QWidget { background-color: #E5F3FF; padding: 10px; }
            QListWidget { border: 1px solid #40C4FF; border-radius: 5px; }
            QTextEdit { border: 1px solid #40C4FF; border-radius: 5px; background-color: #FFFFFF; color: black; }
            QPushButton { background-color: #40C4FF; color: white; border: none; padding: 8px; border-radius: 5px; }
            QPushButton:hover { background-color: #0288D1; }
            QLabel { color: #0288D1; font-weight: bold; }
        """)

    def populate_tg_chats(self, chats):
        self.tg_chats_list.clear()
        for name, chat_id in chats:
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, chat_id)
            self.tg_chats_list.addItem(item)

    @asyncSlot()
    async def load_telegram_chats(self):
        if not self.parent.telegram_client or not self.parent.telegram_client.is_connected():
            QMessageBox.critical(self, "Error", "Not connected to Telegram. Please log in first.")
            return
        progress = QProgressDialog("Loading Telegram chats...", None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        try:
            chats = []
            async for dialog in self.parent.telegram_client.iter_dialogs():
                if dialog.is_channel or dialog.is_group or dialog.is_user:
                    chats.append((dialog.name, dialog.id))
            self.populate_tg_chats(chats)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load chats: {str(e)}")
            logger.error(f"Load chats error: {str(e)}", exc_info=True)
        finally:
            progress.close()

    def _on_tg_chat_clicked(self, item):
        chat_id = item.data(Qt.UserRole)
        if chat_id:
            self.parent.selected_tg_chat = chat_id  # Сохраняем ID чата для отправки
            asyncio.ensure_future(self.select_tg_chat(chat_id))

    def _on_tg_message_double_clicked(self, item):
        message_id = item.data(Qt.UserRole)
        if message_id:
            # Извлекаем полное сообщение по ID
            asyncio.ensure_future(self.select_tg_message(message_id))

    @asyncSlot()
    async def select_tg_chat(self, chat_id):
        if not self.parent.telegram_client or not self.parent.telegram_client.is_connected():
            QMessageBox.critical(self, "Error", "Not connected to Telegram. Please log in first.")
            return
        progress = QProgressDialog("Loading messages...", None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        try:
            self.tg_messages_list.clear()
            async for message in self.parent.telegram_client.iter_messages(chat_id, limit=50):
                if message.message:
                    text = message.message[:50] + "..." if len(message.message) > 50 else message.message
                    item = QListWidgetItem(text)
                    item.setData(Qt.UserRole, message.id)
                    self.tg_messages_list.addItem(item)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load messages: {str(e)}")
            logger.error(f"Load messages error: {str(e)}", exc_info=True)
        finally:
            progress.close()

    @asyncSlot()
    async def select_tg_message(self, message_id):
        try:
            async for message in self.parent.telegram_client.iter_messages(self.parent.selected_tg_chat, ids=[message_id]):
                if message.message:
                    self.parent.selected_tg_message = message.message
                    self.parent.discord_chat_widget.message_preview.setText(message.message)
                    QMessageBox.information(self, "Success", "Message selected for forwarding to Discord.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to select message: {str(e)}")
            logger.error(f"Select message error: {str(e)}", exc_info=True)

    @asyncSlot()
    async def forward_to_telegram(self):
        message = self.message_preview.toPlainText()
        if not message or not self.parent.selected_tg_chat:
            QMessageBox.warning(self, "Error", "Please select a Discord message and a Telegram chat.")
            return
        progress = QProgressDialog("Sending message to Telegram...", None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        try:
            await self.parent.telegram_client.send_message(self.parent.selected_tg_chat, message)
            progress.close()
            QMessageBox.information(self, "Success", "Message forwarded to Telegram!")
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "Error", f"Failed to send message: {str(e)}")
            logger.error(f"Send to Telegram error: {str(e)}", exc_info=True)

    @asyncSlot()
    async def logout_telegram(self):
        if not self.parent.telegram_client or not self.parent.telegram_client.is_connected():
            QMessageBox.warning(self, "Warning", "Not logged in to Telegram.")
            return
        reply = QMessageBox.question(self, "Confirm Logout", "Are you sure you want to log out from Telegram?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.No:
            return
        progress = QProgressDialog("Logging out from Telegram...", None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        try:
            await self.parent.telegram_client.log_out()
            safe_phone = re.sub(r'[^\d]', '', self.parent.phone_number)
            session_file = f'sessions/{safe_phone}.session'
            creds_file = f'sessions/{safe_phone}_creds.json'
            if os.path.exists(session_file):
                os.remove(session_file)
            if os.path.exists(creds_file):
                os.remove(creds_file)
            self.parent.telegram_client = None
            self.parent.phone_number = ""
            self.parent.api_id = ""
            self.parent.api_hash = ""
            self.tg_chats_list.clear()
            self.tg_messages_list.clear()
            self.message_preview.clear()
            self.parent.telegram_stacked.setCurrentWidget(self.parent.telegram_login_widget)
            progress.close()
            QMessageBox.information(self, "Success", "Logged out from Telegram.")
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "Error", f"Logout failed: {str(e)}")
            logger.error(f"Telegram logout error: {str(e)}", exc_info=True)

    def populate_tg_messages(self, messages):
        self.tg_messages_list.clear()
        for msg_id, msg_text in messages:
            preview = msg_text[:50] + "..." if len(msg_text) > 50 else msg_text
            self.tg_messages_list.addItem(f"{msg_id}: {preview}")

class DiscordLoginWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        self.discord_token_label = QLabel("Discord Token:")
        self.discord_token_input = QLineEdit()
        self.discord_token_input.setPlaceholderText("Enter your Discord token")
        self.login_button = QPushButton("Login to Discord")
        self.login_button.clicked.connect(self.init_discord_login)
        layout.addWidget(self.discord_token_label)
        layout.addWidget(self.discord_token_input)
        layout.addWidget(self.login_button)
        self.setLayout(layout)
        self.setStyleSheet("""
            QWidget { background-color: #36393F; padding: 10px; }
            QLineEdit { border: 1px solid #7289DA; border-radius: 5px; padding: 5px; color: white; }
            QPushButton { background-color: #7289DA; color: white; border: none; padding: 8px; border-radius: 5px; }
            QPushButton:hover { background-color: #677BC4; }
            QLabel { color: #7289DA; font-weight: bold; }
        """)

    @asyncSlot()
    async def init_discord_login(self):
        discord_token = self.discord_token_input.text().strip()
        if not discord_token:
            QMessageBox.warning(self, "Error", "Please enter a Discord token.")
            return
        self.parent.discord_token = discord_token
        try:
            intents = discord.Intents.default()
            intents.message_content = True
            self.parent.discord_client = discord.Client(intents=intents)
            progress = QProgressDialog("Connecting to Discord...", None, 0, 0, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.show()
            await self.parent.connect_discord()
            progress.close()
            self.parent.telegram_login_widget.save_credentials()
            self.parent.on_discord_connected(True)
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "Error", f"Discord login failed: {str(e)}")

class DiscordChatWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.selected_discord_channel = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        self.discord_channels_label = QLabel("Discord Channels:")
        self.discord_channels_list = QListWidget()
        self.discord_channels_list.itemClicked.connect(self._on_discord_channel_clicked)
        self.discord_messages_label = QLabel("Messages:")  # Новый список сообщений
        self.discord_messages_list = QListWidget()
        self.discord_messages_list.itemDoubleClicked.connect(self._on_discord_message_double_clicked)
        self.message_preview_label = QLabel("Message Preview (from Telegram):")
        self.message_preview = QTextEdit()
        self.message_preview.setReadOnly(True)
        self.forward_button = QPushButton("Forward to Discord")
        self.forward_button.clicked.connect(self.forward_to_discord)
        self.load_channels_button = QPushButton("Load Channels")
        self.load_channels_button.clicked.connect(self.load_discord_channels)
        self.logout_button = QPushButton("Log Out from Discord")
        self.logout_button.clicked.connect(self.logout_discord)
        layout.addWidget(self.discord_channels_label)
        layout.addWidget(self.discord_channels_list)
        layout.addWidget(self.discord_messages_label)
        layout.addWidget(self.discord_messages_list)
        layout.addWidget(self.message_preview_label)
        layout.addWidget(self.message_preview)
        layout.addWidget(self.forward_button)
        layout.addWidget(self.load_channels_button)
        layout.addWidget(self.logout_button)
        self.setLayout(layout)
        self.setStyleSheet("""
            QWidget { background-color: #36393F; padding: 10px; }
            QListWidget { border: 1px solid #7289DA; border-radius: 5px; color: white; }
            QTextEdit { border: 1px solid #7289DA; border-radius: 5px; background-color: #2C2F33; color: white; }
            QPushButton { background-color: #7289DA; color: white; border: none; padding: 8px; border-radius: 5px; }
            QPushButton:hover { background-color: #5B6EAE; }
            QLabel { color: #7289DA; font-weight: bold; }
        """)

    def _on_discord_channel_clicked(self, item):
        self.selected_discord_channel = item.data(Qt.UserRole)
        if self.selected_discord_channel:
            asyncio.ensure_future(self.select_discord_channel())

    def _on_discord_message_double_clicked(self, item):
        message_id = item.data(Qt.UserRole)
        if message_id:
            asyncio.ensure_future(self.select_discord_message(message_id))

    def populate_discord_channels(self, channels):
        self.discord_channels_list.clear()
        for name, channel_id in channels:
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, channel_id)
            self.discord_channels_list.addItem(item)

    def populate_discord_messages(self, messages):
        self.discord_messages_list.clear()
        for content, message_id in messages:
            text = content[:50] + "..." if len(content) > 50 else content
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, message_id)
            self.discord_messages_list.addItem(item)

    @asyncSlot()
    async def load_discord_channels(self):
        if not self.parent.discord_client or self.parent.discord_client.is_closed():
            QMessageBox.critical(self, "Error", "Not connected to Discord. Please log in first.")
            return
        progress = QProgressDialog("Loading Discord channels...", None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        try:
            channels = []
            for guild in self.parent.discord_client.guilds:
                for channel in guild.text_channels:
                    channels.append((f"{guild.name}/{channel.name}", channel.id))
            self.populate_discord_channels(channels)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load channels: {str(e)}")
            logger.error(f"Load channels error: {str(e)}", exc_info=True)
        finally:
            progress.close()

    @asyncSlot()
    async def select_discord_channel(self):
        if not self.parent.discord_client or self.parent.discord_client.is_closed():
            QMessageBox.critical(self, "Error", "Not connected to Discord. Please log in first.")
            return
        progress = QProgressDialog("Loading Discord messages...", None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        try:
            self.discord_messages_list.clear()
            channel = self.parent.discord_client.get_channel(int(self.selected_discord_channel))
            messages = []
            async for message in channel.history(limit=50):
                if message.content:
                    messages.append((message.content, message.id))
            self.populate_discord_messages(messages)
            # Обновляем превью для Telegram, если сообщение уже выбрано
            if self.parent.selected_tg_message:
                self.message_preview.setText(self.parent.selected_tg_message)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load messages: {str(e)}")
            logger.error(f"Load Discord messages error: {str(e)}", exc_info=True)
        finally:
            progress.close()

    @asyncSlot()
    async def select_discord_message(self, message_id):
        try:
            channel = self.parent.discord_client.get_channel(int(self.selected_discord_channel))
            message = await channel.fetch_message(message_id)
            if message.content:
                self.parent.selected_discord_message = message.content
                self.parent.telegram_chat_widget.message_preview.setText(message.content)
                QMessageBox.information(self, "Success", "Message selected for forwarding to Telegram.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to select message: {str(e)}")
            logger.error(f"Select Discord message error: {str(e)}", exc_info=True)

    @asyncSlot()
    async def forward_to_discord(self):
        message = self.message_preview.toPlainText()
        if not message or not self.selected_discord_channel:
            QMessageBox.warning(self, "Error", "Please select a Telegram message and a Discord channel.")
            return
        progress = QProgressDialog("Sending message to Discord...", None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        try:
            channel = self.parent.discord_client.get_channel(int(self.selected_discord_channel))
            await channel.send(message)
            progress.close()
            QMessageBox.information(self, "Success", "Message forwarded to Discord!")
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "Error", f"Failed to send message: {str(e)}")
            logger.error(f"Send to Discord error: {str(e)}", exc_info=True)

    @asyncSlot()
    async def logout_discord(self):
        if not self.parent.discord_client or self.parent.discord_client.is_closed():
            QMessageBox.warning(self, "Warning", "Not logged in to Discord.")
            return
        reply = QMessageBox.question(self, "Confirm Logout",
                                    "Are you sure you want to log out from Discord?",
                                    QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.No:
            return
        progress = QProgressDialog("Logging out from Discord...", None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        try:
            await self.parent.discord_client.close()
            self.parent.discord_client = None
            self.parent.discord_token = ""
            safe_phone = re.sub(r'[^\d]', '', self.parent.phone_number) if self.parent.phone_number else ""
            if safe_phone:
                creds_file = f'sessions/{safe_phone}_creds.json'
                if os.path.exists(creds_file):
                    with open(creds_file, 'r') as f:
                        creds = json.load(f)
                    creds['discord_token'] = ""
                    with open(creds_file, 'w') as f:
                        json.dump(creds, f)
            self.discord_channels_list.clear()
            self.discord_messages_list.clear()
            self.message_preview.clear()
            self.parent.discord_stacked.setCurrentWidget(self.parent.discord_login_widget)
            progress.close()
            QMessageBox.information(self, "Success", "Logged out from Discord.")
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "Error", f"Logout failed: {str(e)}")
            logger.error(f"Discord logout error: {str(e)}", exc_info=True)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Telegram-Discord Bridge")
        self.resize(1200, 700)
        self.telegram_client = None
        self.discord_client = None
        self.phone_number = None
        self.api_id = None
        self.api_hash = None
        self.discord_token = None
        self.selected_tg_chat = None
        self.selected_discord_channel = None
        self.selected_tg_message = None
        self.selected_discord_message = None
        self.splitter = QSplitter(Qt.Horizontal)
        self.telegram_frame = QFrame()
        self.telegram_frame.setFrameShape(QFrame.StyledPanel)
        self.discord_frame = QFrame()
        self.discord_frame.setFrameShape(QFrame.StyledPanel)
        self.splitter.addWidget(self.telegram_frame)
        self.splitter.addWidget(self.discord_frame)
        self.setCentralWidget(self.splitter)
        self.init_ui()
        self.check_saved_session()

    def init_ui(self):
        self.telegram_layout = QVBoxLayout(self.telegram_frame)
        self.telegram_stacked = QStackedWidget()
        self.telegram_login_widget = TelegramLoginWidget(self)
        self.telegram_chat_widget = TelegramChatWidget(self)
        self.telegram_stacked.addWidget(self.telegram_login_widget)
        self.telegram_stacked.addWidget(self.telegram_chat_widget)
        self.telegram_layout.addWidget(self.telegram_stacked)
        self.discord_layout = QVBoxLayout(self.discord_frame)
        self.discord_stacked = QStackedWidget()
        self.discord_login_widget = DiscordLoginWidget(self)
        self.discord_chat_widget = DiscordChatWidget(self)
        self.discord_stacked.addWidget(self.discord_login_widget)
        self.discord_stacked.addWidget(self.discord_chat_widget)
        self.discord_layout.addWidget(self.discord_stacked)

    def check_saved_session(self):
        if not os.path.exists('sessions'):
            return
        session_files = [f for f in os.listdir('sessions') if f.endswith('_creds.json')]
        if not session_files:
            return
        try:
            with open(f'sessions/{session_files[0]}', 'r') as f:
                creds = json.load(f)
            self.phone_number = creds.get('phone')
            self.api_id = creds.get('api_id')
            self.api_hash = creds.get('api_hash')
            self.discord_token = creds.get('discord_token')
            if self.phone_number and self.api_id and self.api_hash:
                self.telegram_login_widget.phone_input.setText(self.phone_number)
                self.telegram_login_widget.api_id_input.setText(self.api_id)
                self.telegram_login_widget.api_hash_input.setText(self.api_hash)
                asyncio.ensure_future(self.telegram_login_widget.init_telegram_login())
            if self.discord_token:
                self.discord_login_widget.discord_token_input.setText(self.discord_token)
                asyncio.ensure_future(self.discord_login_widget.init_discord_login())
        except Exception as e:
            logger.error(f"Error loading saved session: {e}")

    async def connect_telegram(self):
        try:
            await self.telegram_client.connect()
            if not await self.telegram_client.is_user_authorized():
                await self.telegram_client.send_code_request(self.phone_number)
                code, ok = QInputDialog.getText(self, "Code Verification", "Enter your code:")
                if ok and code:
                    try:
                        await self.telegram_client.sign_in(self.phone_number, code)
                    except errors.SessionPasswordNeededError:
                        password, ok = QInputDialog.getText(self, "2FA", "Enter 2FA password:", QLineEdit.Password)
                        if ok and password:
                            await self.telegram_client.sign_in(password=password)
                        else:
                            raise Exception("2FA password required")
                else:
                    raise Exception("Verification code required")
            return True
        except errors.PhoneNumberInvalidError:
            raise Exception("Invalid phone number. Please use format: +1234567890")
        except errors.PhoneCodeInvalidError:
            raise Exception("Invalid verification code")
        except Exception as e:
            raise Exception(f"Telegram connection failed: {str(e)}")

    async def connect_discord(self):
        try:
            await self.discord_client.login(self.discord_token)
            asyncio.create_task(self.discord_client.connect())
            return True
        except discord.LoginFailure:
            raise Exception("Invalid Discord token. Please check your token.")
        except Exception as e:
            raise Exception(f"Discord connection failed: {str(e)}")

    def on_telegram_connected(self, success):
        if success:
            self.telegram_stacked.setCurrentIndex(1)
            logger.info("Successfully connected to Telegram")
        else:
            self.telegram_stacked.setCurrentIndex(0)

    def on_discord_connected(self, success):
        if success:
            self.discord_stacked.setCurrentIndex(1)
            logger.info("Successfully connected to Discord")
        else:
            self.discord_stacked.setCurrentIndex(0)

    def select_tg_message(self, item):
        msg_text = item.text().split(': ', 1)[1]
        if len(msg_text) > 50:
            msg_text = msg_text.rstrip('...')
        self.discord_chat_widget.message_preview.setPlainText(msg_text)
        if self.selected_discord_channel:
            self.discord_chat_widget.forward_button.setEnabled(True)

    def select_discord_channel(self, item):
        channel_info = item.text()
        self.selected_discord_channel = channel_info.split('(')[-1][:-1]
        if self.discord_chat_widget.message_preview.toPlainText():
            self.discord_chat_widget.forward_button.setEnabled(True)

    @asyncSlot()
    async def forward_message(self):
        message = self.discord_chat_widget.message_preview.toPlainText()
        if not message or not self.selected_discord_channel:
            QMessageBox.warning(self, "Error", "Please select a message and a Discord channel.")
            return
        progress = QProgressDialog("Sending message...", None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        try:
            channel = self.discord_client.get_channel(int(self.selected_discord_channel))
            if not channel:
                raise Exception("Invalid channel selected")
            await channel.send(message)
            progress.close()
            QMessageBox.information(self, "Success", "Message forwarded to Discord!")
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "Error", f"Failed to send message: {str(e)}")

if __name__ == '__main__':
    def handle_exception(exc_type, exc_value, exc_traceback):
        logger.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
        QMessageBox.critical(None, "Error", f"Unhandled exception: {str(exc_value)}")

    sys.excepthook = handle_exception
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    window = MainWindow()
    window.show()
    with loop:
        loop.run_forever()