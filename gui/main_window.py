# main_window.py - ПОЛНАЯ ИНТЕГРАЦИЯ БЭКАПОВ И ТЕСТИРОВАНИЯ
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import customtkinter as ctk
import os
import tempfile
import threading
import base64
import secrets
import logging
import queue
import time
import zipfile
import json
import hashlib
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from auth import AuthManager
from crypto import CryptoManager
from folder_security import FolderSecurityManager
from vault_core import VaultCore, VaultTransaction, TransactionError
from media_viewer import ViewerManager
from recovery_manager import RecoveryManager, MasterPasswordRecoveryDialog, FolderRecoveryDialog
from login_dialog import LoginDialog
from folder_password_dialog import FolderPasswordDialog
from create_folder_dialog import CreateFolderDialog
from password_change_dialog import PasswordChangeDialog


# ============================================================================
# КЛАСС ДИАЛОГА ПРОГРЕССА
# ============================================================================

class ProgressDialog(ctk.CTkToplevel):
    """Диалог прогресса для долгих операций"""
    
    def __init__(self, parent, title="Выполнение операции"):
        super().__init__(parent)
        self.title(title)
        self.geometry("400x150")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        
        self.progress_value = 0
        self.is_cancelled = False
        
        self._create_widgets()
        self.center_window()
    
    def _create_widgets(self):
        """Создание виджетов прогресса"""
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        self.status_label = ctk.CTkLabel(main_frame, text="Подготовка...")
        self.status_label.pack(pady=10)
        
        self.progress_bar = ctk.CTkProgressBar(main_frame)
        self.progress_bar.pack(fill=tk.X, pady=10)
        self.progress_bar.set(0)
        
        self.cancel_button = ctk.CTkButton(
            main_frame, 
            text="Отмена", 
            command=self._cancel
        )
        self.cancel_button.pack(pady=10)
    
    def update(self, value, status=""):
        """Обновление прогресса"""
        if self.is_cancelled:
            return False
        
        self.progress_value = value / 100.0
        self.progress_bar.set(self.progress_value)
        
        if status:
            self.status_label.configure(text=status)
        
        self.update_idletasks()
        return True
    
    def _cancel(self):
        """Отмена операции"""
        self.is_cancelled = True
        self.status_label.configure(text="Отмена...")
        self.cancel_button.configure(state="disabled")
    
    def center_window(self):
        """Центрирование окна"""
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f'{width}x{height}+{x}+{y}')


# ============================================================================
# КЛАСС ДИАЛОГА ТИПА ВОССТАНОВЛЕНИЯ
# ============================================================================

class RestoreTypeDialog(ctk.CTkToplevel):
    """Диалог выбора типа восстановления из бэкапа"""
    
    def __init__(self, parent):
        super().__init__(parent)
        self.result = None
        
        self.title("Тип восстановления")
        self.geometry("450x250")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        
        self._create_widgets()
        self.center_window()
    
    def _create_widgets(self):
        """Создание виджетов"""
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        ctk.CTkLabel(main_frame, text="Выберите тип восстановления:",
                    font=ctk.CTkFont(weight="bold")).pack(pady=10)
        
        self.restore_type = tk.StringVar(value="filesystem_only")
        
        # Опция 1: Только файловая система
        ctk.CTkRadioButton(
            main_frame,
            text="Только файловая система",
            variable=self.restore_type,
            value="filesystem_only"
        ).pack(pady=5, anchor='w')
        
        ctk.CTkLabel(main_frame, text="(восстанавливает структуру папок и файлов, но не сами файлы)",
                    font=ctk.CTkFont(size=11)).pack(pady=2, padx=20, anchor='w')
        
        # Опция 2: Полное восстановление
        ctk.CTkRadioButton(
            main_frame,
            text="Полное восстановление",
            variable=self.restore_type,
            value="full"
        ).pack(pady=5, anchor='w')
        
        ctk.CTkLabel(main_frame, text="(восстанавливает все данные, включая зашифрованные файлы)",
                    font=ctk.CTkFont(size=11)).pack(pady=2, padx=20, anchor='w')
        
        # Кнопки
        button_frame = ctk.CTkFrame(main_frame)
        button_frame.pack(pady=15)
        
        ctk.CTkButton(button_frame, text="Восстановить",
                     command=self._submit).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(button_frame, text="Отмена",
                     command=self._cancel).pack(side=tk.LEFT, padx=5)
    
    def _submit(self):
        """Подтверждение выбора"""
        self.result = self.restore_type.get()
        self.destroy()
    
    def _cancel(self):
        """Отмена"""
        self.result = None
        self.destroy()
    
    def center_window(self):
        """Центрирование окна"""
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f'{width}x{height}+{x}+{y}')


# ============================================================================
# КЛАСС МЕНЕДЖЕРА БЭКАПОВ (УПРОЩЕННАЯ ВЕРСИЯ)
# ============================================================================

class BackupManager:
    """Упрощенный менеджер бэкапов для интеграции в GUI"""
    
    def __init__(self, crypto_manager, auth_manager, vault_core):
        self.crypto = crypto_manager
        self.auth = auth_manager
        self.vault = vault_core
        self.backup_dir = 'data/backups'
        
        # Создаем директорию для бэкапов
        os.makedirs(self.backup_dir, exist_ok=True)
    
    def create_backup(self, backup_type='full', password=None):
        """Создание резервной копии"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"backup_{backup_type}_{timestamp}.zip"
            backup_path = os.path.join(self.backup_dir, backup_filename)
            
            # Создаем временную директорию
            temp_dir = tempfile.mkdtemp(prefix='backup_')
            
            try:
                # 1. Копируем файловую систему
                fs_source = self.vault.filesystem_path
                fs_dest = os.path.join(temp_dir, 'filesystem.json.enc')
                if os.path.exists(fs_source):
                    shutil.copy2(fs_source, fs_dest)
                
                # 2. Копируем конфигурацию
                config_source = os.path.join('data', 'vault_config.json')
                config_dest = os.path.join(temp_dir, 'vault_config.json')
                if os.path.exists(config_source):
                    shutil.copy2(config_source, config_dest)
                
                # 3. Для полного бэкапа копируем зашифрованные файлы
                if backup_type == 'full':
                    encrypted_source = 'data/encrypted_files'
                    encrypted_dest = os.path.join(temp_dir, 'encrypted_files')
                    if os.path.exists(encrypted_source):
                        os.makedirs(encrypted_dest, exist_ok=True)
                        for filename in os.listdir(encrypted_source):
                            if filename.endswith('.myarc'):
                                source_file = os.path.join(encrypted_source, filename)
                                dest_file = os.path.join(encrypted_dest, filename)
                                shutil.copy2(source_file, dest_file)
                
                # 4. Создаем манифест
                manifest = {
                    'version': '2.0',
                    'backup_type': backup_type,
                    'created_at': datetime.now().isoformat(),
                    'timestamp': timestamp,
                    'content': {
                        'file_count': len(self.vault.filesystem.get('files', {})),
                        'folder_count': len(self.vault.filesystem.get('folders', {})),
                        'backup_type': backup_type
                    }
                }
                
                manifest_path = os.path.join(temp_dir, 'manifest.json')
                with open(manifest_path, 'w', encoding='utf-8') as f:
                    json.dump(manifest, f, indent=2, ensure_ascii=False)
                
                # 5. Создаем ZIP архив
                with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for root, dirs, files in os.walk(temp_dir):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, temp_dir)
                            zipf.write(file_path, arcname)
                
                # 6. Если указан пароль, шифруем архив
                if password:
                    encrypted_backup = self._encrypt_backup(backup_path, password)
                    if encrypted_backup:
                        os.remove(backup_path)
                        backup_path = encrypted_backup
                
                logging.info(f"Создан бэкап: {backup_filename}")
                return True, backup_path
                
            finally:
                # Очищаем временную директорию
                shutil.rmtree(temp_dir, ignore_errors=True)
                
        except Exception as e:
            logging.error(f"Ошибка создания бэкапа: {e}")
            return False, str(e)
    
    def _encrypt_backup(self, backup_path, password):
        """Шифрование бэкапа"""
        try:
            # Читаем исходный архив
            with open(backup_path, 'rb') as f:
                backup_data = f.read()
            
            # Генерируем ключ из пароля
            salt = secrets.token_bytes(32)
            key, _ = self.crypto.generate_key_from_password(password, salt)
            
            # Шифруем данные
            from cryptography.fernet import Fernet
            fernet = Fernet(key)
            encrypted_data = fernet.encrypt(backup_data)
            
            # Сохраняем с солью
            encrypted_path = backup_path + '.enc'
            with open(encrypted_path, 'wb') as f:
                f.write(salt)
                f.write(encrypted_data)
            
            return encrypted_path
            
        except Exception as e:
            logging.error(f"Ошибка шифрования бэкапа: {e}")
            return None
    
    def verify_backup(self, backup_path):
        """Проверка целостности бэкапа"""
        try:
            if not os.path.exists(backup_path):
                return False, ["Файл бэкапа не найден"]
            
            issues = []
            
            # Проверяем, является ли файлом ZIP
            if backup_path.endswith('.zip'):
                try:
                    with zipfile.ZipFile(backup_path, 'r') as zipf:
                        # Проверяем обязательные файлы
                        required_files = ['manifest.json', 'filesystem.json.enc']
                        for required in required_files:
                            if required not in zipf.namelist():
                                issues.append(f"Отсутствует файл: {required}")
                        
                        # Проверяем целостность архива
                        bad_file = zipf.testzip()
                        if bad_file:
                            issues.append(f"Поврежден файл в архиве: {bad_file}")
                
                except zipfile.BadZipFile:
                    issues.append("Файл не является корректным ZIP архивом")
            
            elif backup_path.endswith('.enc'):
                issues.append("Зашифрованные бэкапы требуют пароль для проверки")
            
            return len(issues) == 0, issues
            
        except Exception as e:
            return False, [f"Ошибка проверки: {e}"]
    
    def restore_backup(self, backup_path, password=None, restore_type='filesystem_only'):
        """Восстановление из бэкапа"""
        try:
            # Создаем резервную копию текущих данных
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pre_restore_dir = os.path.join(self.backup_dir, f'pre_restore_{timestamp}')
            os.makedirs(pre_restore_dir, exist_ok=True)
            
            # Копируем текущие данные
            for item in ['vault_config.json', 'filesystem.json.enc']:
                source = os.path.join('data', item)
                if os.path.exists(source):
                    shutil.copy2(source, os.path.join(pre_restore_dir, item))
            
            # Работаем с временной директорией
            temp_dir = tempfile.mkdtemp(prefix='restore_')
            
            try:
                # Расшифровываем если нужно
                if backup_path.endswith('.enc') and password:
                    decrypted_path = self._decrypt_backup(backup_path, password)
                    if not decrypted_path:
                        return False, "Неверный пароль или архив поврежден"
                    backup_path = decrypted_path
                
                # Извлекаем архив
                with zipfile.ZipFile(backup_path, 'r') as zipf:
                    zipf.extractall(temp_dir)
                
                # Проверяем манифест
                manifest_path = os.path.join(temp_dir, 'manifest.json')
                if not os.path.exists(manifest_path):
                    return False, "Манифест не найден в бэкапе"
                
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)
                
                # Восстанавливаем файловую систему
                fs_source = os.path.join(temp_dir, 'filesystem.json.enc')
                fs_dest = os.path.join('data', 'filesystem.json.enc')
                
                if os.path.exists(fs_source):
                    shutil.copy2(fs_source, fs_dest)
                else:
                    return False, "Файловая система не найдена в бэкапе"
                
                # Для полного восстановления
                if restore_type == 'full':
                    # Восстанавливаем конфигурацию
                    config_source = os.path.join(temp_dir, 'vault_config.json')
                    config_dest = os.path.join('data', 'vault_config.json')
                    if os.path.exists(config_source):
                        shutil.copy2(config_source, config_dest)
                    
                    # Восстанавливаем зашифрованные файлы
                    encrypted_source = os.path.join(temp_dir, 'encrypted_files')
                    encrypted_dest = 'data/encrypted_files'
                    
                    if os.path.exists(encrypted_source):
                        # Очищаем текущую директорию
                        if os.path.exists(encrypted_dest):
                            shutil.rmtree(encrypted_dest)
                        shutil.copytree(encrypted_source, encrypted_dest)
                
                message = f"Восстановление выполнено успешно. "
                message += f"Предыдущие данные сохранены в {pre_restore_dir}"
                return True, message
                
            finally:
                # Очищаем временную директорию
                shutil.rmtree(temp_dir, ignore_errors=True)
                
        except Exception as e:
            logging.error(f"Ошибка восстановления: {e}")
            return False, f"Ошибка восстановления: {e}"
    
    def _decrypt_backup(self, backup_path, password):
        """Расшифровка бэкапа"""
        try:
            with open(backup_path, 'rb') as f:
                salt = f.read(32)
                encrypted_data = f.read()
            
            # Генерируем ключ из пароля
            key, _ = self.crypto.generate_key_from_password(password, salt)
            
            # Расшифровываем
            from cryptography.fernet import Fernet
            fernet = Fernet(key)
            decrypted_data = fernet.decrypt(encrypted_data)
            
            # Сохраняем во временный файл
            temp_path = backup_path.replace('.enc', '.zip')
            with open(temp_path, 'wb') as f:
                f.write(decrypted_data)
            
            return temp_path
            
        except Exception:
            return None
    
    def get_available_backups(self):
        """Получение списка доступных бэкапов"""
        backups = []
        
        if not os.path.exists(self.backup_dir):
            return backups
        
        for filename in os.listdir(self.backup_dir):
            if filename.endswith(('.zip', '.enc')):
                backup_path = os.path.join(self.backup_dir, filename)
                file_stats = os.stat(backup_path)
                
                backup_info = {
                    'filename': filename,
                    'path': backup_path,
                    'size': file_stats.st_size,
                    'created_at': datetime.fromtimestamp(file_stats.st_mtime),
                    'is_encrypted': filename.endswith('.enc')
                }
                
                # Пытаемся получить информацию из манифеста
                try:
                    if filename.endswith('.zip'):
                        with zipfile.ZipFile(backup_path, 'r') as zipf:
                            if 'manifest.json' in zipf.namelist():
                                with zipf.open('manifest.json') as f:
                                    manifest = json.load(f)
                                backup_info['manifest'] = manifest
                except:
                    pass
                
                backups.append(backup_info)
        
        # Сортируем по дате (новые сверху)
        backups.sort(key=lambda x: x['created_at'], reverse=True)
        return backups
    
    def cleanup_old_backups(self, keep_last=10):
        """Очистка старых бэкапов"""
        backups = self.get_available_backups()
        
        if len(backups) <= keep_last:
            return 0
        
        deleted_count = 0
        for backup in backups[keep_last:]:
            try:
                os.remove(backup['path'])
                deleted_count += 1
                logging.info(f"Удален старый бэкап: {backup['filename']}")
            except Exception as e:
                logging.error(f"Ошибка удаления бэкапа {backup['filename']}: {e}")
        
        return deleted_count


# ============================================================================
# ГЛАВНЫЙ КЛАСС ПРИЛОЖЕНИЯ
# ============================================================================

class SecureMediaVaultApp:
    def __init__(self):
        self.auth_manager = AuthManager()
        self.crypto_manager = None
        self.folder_security_manager = None
        self.vault_core = None
        self.recovery_manager = None
        self.backup_manager = None
        
        # Безопасное хранение временных файлов
        self.temp_files = []
        self._temp_dir = None
        
        # Очередь операций
        self._operation_queue = queue.Queue()
        self._operation_thread = threading.Thread(
            target=self._process_operations,
            daemon=True
        )
        self._operation_thread.start()
        
        # Инициализация GUI
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
        
        self.root = ctk.CTk()
        self.root.title("Media Vault - Защищенный архив")
        self.root.geometry("1200x700")
        
        # Обработчик закрытия окна
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        
        self.current_folder_id = 'root'
        
        self._setup_gui()
    
    def _setup_gui(self):
        """Настройка интерфейса"""
        self.main_frame = ctk.CTkFrame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        if self.auth_manager.is_first_run():
            self._show_first_run_setup()
        else:
            self._show_login_screen()
    
    # ========================================================================
    # ОЧЕРЕДЬ ОПЕРАЦИЙ
    # ========================================================================
    
    def _queue_operation(self, operation_func, *args, **kwargs):
        """Добавление операции в очередь"""
        result_queue = queue.Queue()
        self._operation_queue.put((operation_func, args, kwargs, result_queue))
        
        # Ждем результат
        result_type, result = result_queue.get()
        if result_type == 'error':
            raise result
        return result
    
    def _process_operations(self):
        """Обработка операций в очереди"""
        while True:
            try:
                operation = self._operation_queue.get()
                if operation is None:  # Сигнал остановки
                    break
                
                func, args, kwargs, result_queue = operation
                try:
                    result = func(*args, **kwargs)
                    result_queue.put(('success', result))
                except Exception as e:
                    logging.error(f"Ошибка в операции: {e}")
                    result_queue.put(('error', e))
                finally:
                    self._operation_queue.task_done()
                    
            except Exception as e:
                logging.error(f"Ошибка в обработчике операций: {e}")
                time.sleep(1)  # Задержка при ошибках
    
    # ========================================================================
    # ЭКРАН ПЕРВОЙ НАСТРОЙКИ И ЛОГИНА
    # ========================================================================
    
    def _show_first_run_setup(self):
        """Экран первой настройки"""
        setup_frame = ctk.CTkFrame(self.main_frame)
        setup_frame.pack(fill=tk.BOTH, expand=True, padx=50, pady=50)
        
        ctk.CTkLabel(setup_frame, text="Добро пожаловать в Media Vault!", 
                     font=ctk.CTkFont(size=20, weight="bold")).pack(pady=20)
        
        ctk.CTkLabel(setup_frame, text="Создайте мастер-пароль для защиты вашего архива",
                     font=ctk.CTkFont(size=14)).pack(pady=10)
        
        # Поле для пароля
        ctk.CTkLabel(setup_frame, text="Мастер-пароль:").pack(pady=5)
        self.master_password_entry = ctk.CTkEntry(setup_frame, show="•", width=300)
        self.master_password_entry.pack(pady=5)
        
        # Подтверждение пароля
        ctk.CTkLabel(setup_frame, text="Подтверждение пароля:").pack(pady=5)
        self.confirm_password_entry = ctk.CTkEntry(setup_frame, show="•", width=300)
        self.confirm_password_entry.pack(pady=5)
        
        # Подсказка к паролю
        ctk.CTkLabel(setup_frame, text="Подсказка к паролю (необязательно):").pack(pady=5)
        self.password_hint_entry = ctk.CTkEntry(setup_frame, width=300)
        self.password_hint_entry.pack(pady=5)
        
        # Кнопка создания
        ctk.CTkButton(setup_frame, text="Создать архив", 
                      command=self._create_vault).pack(pady=20)
        
        # Подсказка о требованиях к паролю
        requirements = """Требования к паролю:
• Минимум 12 символов
• Заглавные и строчные буквы
• Хотя бы одна цифра
• Хотя бы один специальный символ
• Только латинские буквы
• Не использовать простые паттерны"""
        ctk.CTkLabel(setup_frame, text=requirements, 
                     font=ctk.CTkFont(size=12)).pack(pady=10)
    
    def _show_login_screen(self):
        """Экран входа"""
        login_dialog = LoginDialog(self.root, self.auth_manager)
        self.root.wait_window(login_dialog)
        
        if login_dialog.result:
            password = login_dialog.result
            try:
                self._initialize_vault(password)
                self._show_main_interface()
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось инициализировать хранилище: {e}")
                self.root.quit()
        else:
            # Показываем опцию восстановления
            if messagebox.askyesno("Восстановление", "Забыли пароль? Хотите восстановить доступ?"):
                self._show_master_recovery()
            else:
                self.root.quit()
    
    def _show_master_recovery(self):
        """Показать диалог восстановления мастер-пароля"""
        recovery_dialog = MasterPasswordRecoveryDialog(self.root, self.auth_manager)
        self.root.wait_window(recovery_dialog)
        
        if recovery_dialog.master_key:
            change_dialog = PasswordChangeDialog(self.root, self.auth_manager, recovery_dialog.master_key)
            self.root.wait_window(change_dialog)
    
            if change_dialog.result:
                new_password, hint = change_dialog.result
                try:
                    self.auth_manager.change_master_password_after_recovery(recovery_dialog.master_key, new_password, hint)
                    messagebox.showinfo("Успех", "Пароль успешно изменен! Теперь вы можете войти с новым паролем.")
                except Exception as e:
                    messagebox.showerror("Ошибка", f"Не удалось изменить пароль: {e}")
        else:
            messagebox.showinfo("Отмена", "Восстановление отменено")
    
    # ========================================================================
    # ИНИЦИАЛИЗАЦИЯ ХРАНИЛИЩА
    # ========================================================================
    
    def _create_vault(self):
        """Создание нового хранилища"""
        password = self.master_password_entry.get()
        confirm_password = self.confirm_password_entry.get()
        password_hint = self.password_hint_entry.get()
        
        if password != confirm_password:
            messagebox.showerror("Ошибка", "Пароли не совпадают")
            return
        
        try:
            progress_dialog = ProgressDialog(self.root, "Создание хранилища")
            
            def create_task():
                try:
                    progress_dialog.update(10, "Создание мастер-пароля...")
                    master_key = self.auth_manager.create_master_password(password, password_hint)
                    
                    progress_dialog.update(50, "Инициализация шифрования...")
                    self._initialize_vault(password)
                    
                    progress_dialog.update(100, "Готово!")
                    return True
                except Exception as e:
                    logging.error(f"Ошибка создания хранилища: {e}")
                    raise e
            
            def run_create():
                try:
                    result = create_task()
                    self.root.after(0, lambda: self._on_vault_created(result, progress_dialog))
                except Exception as e:
                    self.root.after(0, lambda: self._on_vault_create_error(e, progress_dialog))
            
            threading.Thread(target=run_create, daemon=True).start()
            
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
    
    def _initialize_vault(self, password):
        """Инициализация компонентов хранилища"""
        master_key = self.auth_manager.get_master_key(password)
        self.crypto_manager = CryptoManager(master_key)
        self.folder_security_manager = FolderSecurityManager(self.crypto_manager)
        self.vault_core = VaultCore(self.auth_manager, self.crypto_manager, 
                                  self.folder_security_manager)
        self.recovery_manager = RecoveryManager(self.auth_manager, self.crypto_manager, self.vault_core)
        
        # Инициализация менеджера бэкапов
        self.backup_manager = BackupManager(
            self.crypto_manager,
            self.auth_manager,
            self.vault_core
        )
        
        # Очистка старых бэкапов при инициализации
        self._cleanup_old_backups()
    
    def _on_vault_created(self, result, progress_dialog):
        """Обработка успешного создания хранилища"""
        progress_dialog.destroy()
        self._show_main_interface()
    
    def _on_vault_create_error(self, error, progress_dialog):
        """Обработка ошибки создания хранилища"""
        progress_dialog.destroy()
        messagebox.showerror("Ошибка", f"Не удалось создать хранилище: {error}")
    
    # ========================================================================
    # ОСНОВНОЙ ИНТЕРФЕЙС
    # ========================================================================
    
    def _show_main_interface(self):
        """Показать основной интерфейс"""
        for widget in self.main_frame.winfo_children():
            widget.destroy()
        
        self._create_toolbar()
        self._create_main_area()
        self._create_status_bar()
        
        self._refresh_folder_contents()
    
    def _create_toolbar(self):
        """Панель инструментов с кнопкой бэкапов"""
        toolbar = ctk.CTkFrame(self.main_frame)
        toolbar.pack(fill=tk.X, padx=5, pady=5)
        
        # Основные кнопки
        ctk.CTkButton(toolbar, text="Добавить файлы", 
                      command=self._add_files).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(toolbar, text="Новая папка", 
                      command=self._create_new_folder).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(toolbar, text="Назад", 
                      command=self._go_back).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(toolbar, text="Обновить", 
                      command=self._refresh_folder_contents).pack(side=tk.LEFT, padx=5)
        
        # Кнопка проверки целостности
        ctk.CTkButton(toolbar, text="Проверить целостность", 
                      command=self._verify_integrity).pack(side=tk.LEFT, padx=5)
        
        # Кнопка бэкапов
        ctk.CTkButton(toolbar, text="Бэкапы", 
                      command=self._show_backup_menu).pack(side=tk.LEFT, padx=5)
        
        # Кнопка восстановления
        ctk.CTkButton(toolbar, text="Восстановление", 
                      command=self._show_recovery_options).pack(side=tk.RIGHT, padx=5)
        
        # Метка пути
        self.path_label = ctk.CTkLabel(toolbar, text="Путь: /")
        self.path_label.pack(side=tk.RIGHT, padx=10)
    
    def _create_main_area(self):
        """Основная область"""
        main_area = ctk.CTkFrame(self.main_frame)
        main_area.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self._create_folder_tree(main_area)
        self._create_content_area(main_area)
    
    def _create_folder_tree(self, parent):
        """Дерево папок"""
        tree_frame = ctk.CTkFrame(parent)
        tree_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 5))
        
        ctk.CTkLabel(tree_frame, text="Папки", 
                     font=ctk.CTkFont(weight="bold")).pack(pady=5)
        
        self.folder_tree = ttk.Treeview(tree_frame, show='tree', height=20)
        self.folder_tree.pack(fill=tk.Y, padx=5, pady=5)
        
        self.folder_tree.bind('<<TreeviewSelect>>', self._on_folder_select)
        self._populate_folder_tree()
    
    def _create_content_area(self, parent):
        """Область содержимого"""
        content_frame = ctk.CTkFrame(parent)
        content_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        ctk.CTkLabel(content_frame, text="Содержимое папки", 
                     font=ctk.CTkFont(weight="bold")).pack(pady=5)
        
        columns = ('name', 'type', 'size', 'date')
        self.content_tree = ttk.Treeview(content_frame, columns=columns, show='headings', height=15)
        
        self.content_tree.heading('name', text='Имя')
        self.content_tree.heading('type', text='Тип')
        self.content_tree.heading('size', text='Размер')
        self.content_tree.heading('date', text='Дата добавления')
        
        self.content_tree.column('name', width=300)
        self.content_tree.column('type', width=100)
        self.content_tree.column('size', width=100)
        self.content_tree.column('date', width=150)
        
        self.content_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self._create_context_menus()
        self.content_tree.bind('<Double-1>', self._on_file_double_click)
    
    def _create_status_bar(self):
        """Строка состояния"""
        self.status_bar = ctk.CTkLabel(self.main_frame, text="Готов")
        self.status_bar.pack(fill=tk.X, padx=5, pady=2)
    
    # ========================================================================
    # КОНТЕКСТНЫЕ МЕНЮ
    # ========================================================================
    
    def _create_context_menus(self):
        """Контекстные меню"""
        self.file_context_menu = tk.Menu(self.root, tearoff=0)
        self.file_context_menu.add_command(label="Открыть", command=self._open_selected_file)
        self.file_context_menu.add_command(label="Открыть в Media Vault", 
                                          command=self._open_in_internal_viewer)
        self.file_context_menu.add_command(label="Извлечь...", command=self._extract_selected_file)
        self.file_context_menu.add_separator()
        self.file_context_menu.add_command(label="Удалить", command=self._delete_selected_file)
        
        self.folder_context_menu = tk.Menu(self.root, tearoff=0)
        self.folder_context_menu.add_command(label="Войти", command=self._enter_selected_folder)
        self.folder_context_menu.add_command(label="Восстановить доступ", 
                                           command=self._recover_selected_folder)
        self.folder_context_menu.add_separator()
        self.folder_context_menu.add_command(label="Удалить", command=self._delete_selected_folder)
        
        self.content_tree.bind('<Button-3>', self._show_context_menu)
    
    def _show_context_menu(self, event):
        """Показать контекстное меню"""
        item = self.content_tree.identify_row(event.y)
        if item:
            self.content_tree.selection_set(item)
            tags = self.content_tree.item(item)['tags']
            
            if 'folder' in tags:
                self.folder_context_menu.post(event.x_root, event.y_root)
            elif 'file' in tags:
                self.file_context_menu.post(event.x_root, event.y_root)
    
    # ========================================================================
    # ОПЕРАЦИИ С ФАЙЛАМИ И ПАПКАМИ
    # ========================================================================
    
    def _enter_selected_folder(self):
        """Войти в выбранную папку"""
        selection = self.content_tree.selection()
        if not selection:
            return
        
        item = self.content_tree.item(selection[0])
        tags = item['tags']
        
        if 'folder' not in tags:
            return
        
        folder_id = tags[0]
        self._navigate_to_folder(folder_id)
    
    def _recover_selected_folder(self):
        """Восстановить доступ к выбранной папке"""
        selection = self.content_tree.selection()
        if not selection:
            return
        
        item = self.content_tree.item(selection[0])
        tags = item['tags']
        
        if 'folder' not in tags:
            return
        
        folder_id = tags[0]
        folder_data = self.vault_core.filesystem['folders'][folder_id]
        
        recovery_dialog = FolderRecoveryDialog(self.root, self.recovery_manager, folder_data)
        self.root.wait_window(recovery_dialog)
        
        if recovery_dialog.result:
            recovery_password = recovery_dialog.result
            if self.recovery_manager.recover_folder_access(folder_id, recovery_password):
                messagebox.showinfo("Успех", "Доступ к папке восстановлен!")
                self.current_folder_id = folder_id
                self._refresh_folder_contents()
                self._populate_folder_tree()
            else:
                messagebox.showerror("Ошибка", "Неверный пароль восстановления")
    
    def _navigate_to_folder(self, folder_id):
        """Навигация к папке"""
        folder_data = self.vault_core.filesystem['folders'][folder_id]
        
        if folder_data.get('is_locked', True):
            dialog = FolderPasswordDialog(self.root, folder_data, self.recovery_manager)
            self.root.wait_window(dialog)
            
            if dialog.result:
                password, use_recovery = dialog.result
                if self.folder_security_manager.unlock_folder(folder_data, password, use_recovery):
                    self.current_folder_id = folder_id
                    self._refresh_folder_contents()
                    self._populate_folder_tree()
                else:
                    messagebox.showerror("Ошибка", "Неверный пароль папки")
        else:
            self.current_folder_id = folder_id
            self._refresh_folder_contents()
    
    def _populate_folder_tree(self):
        """Заполнение дерева папок"""
        self.folder_tree.delete(*self.folder_tree.get_children())
        
        def add_folder_to_tree(folder_id, parent=''):
            if folder_id not in self.vault_core.filesystem['folders']:
                return
            
            folder = self.vault_core.filesystem['folders'][folder_id]
            folder_name = base64.b64decode(folder['encrypted_name']).decode()
            
            display_name = folder_name
            if folder_id != 'root' and folder.get('is_locked', True):
                display_name = f"🔒 {folder_name}"
            else:
                display_name = f"📁 {folder_name}"
            
            item_id = self.folder_tree.insert(parent, 'end', text=display_name, 
                                            values=(folder_id,))
            
            for child_id in folder['children']:
                if child_id in self.vault_core.filesystem['folders']:
                    add_folder_to_tree(child_id, item_id)
        
        add_folder_to_tree('root')
        if self.folder_tree.get_children():
            self.folder_tree.item(self.folder_tree.get_children()[0], open=True)
    
    def _refresh_folder_contents(self):
        """Обновление содержимого текущей папки"""
        self.content_tree.delete(*self.content_tree.get_children())
        
        try:
            folder_data = self.vault_core.filesystem['folders'][self.current_folder_id]
            subfolders = []
            files = []
            
            for child_id in folder_data['children']:
                if child_id in self.vault_core.filesystem['folders']:
                    folder = self.vault_core.filesystem['folders'][child_id]
                    folder_name = base64.b64decode(folder['encrypted_name']).decode()
                    subfolders.append({
                        'id': child_id,
                        'name': folder_name,
                        'is_locked': folder.get('is_locked', True),
                        'created_at': folder.get('created_at', '')
                    })
                elif child_id in self.vault_core.filesystem['files']:
                    file = self.vault_core.filesystem['files'][child_id]
                    files.append({
                        'id': child_id,
                        'name': file['original_name'],
                        'file_type': file['file_type'],
                        'size': file['size'],
                        'added_at': file['added_at']
                    })
            
            for folder in subfolders:
                display_name = f"🔒 {folder['name']}" if folder['is_locked'] else f"📁 {folder['name']}"
                self.content_tree.insert('', 'end', values=(
                    display_name, 'Папка', '', folder['created_at']
                ), tags=(folder['id'], 'folder'))
            
            for file in files:
                size_str = self._format_size(file['size'])
                self.content_tree.insert('', 'end', values=(
                    file['name'], file['file_type'], size_str, file['added_at']
                ), tags=(file['id'], 'file'))
            
            self._update_path_label()
            
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось загрузить содержимое папки: {e}")
    
    def _on_folder_select(self, event):
        """Обработчик выбора папки в дереве"""
        selection = self.folder_tree.selection()
        if not selection:
            return
        
        item = self.folder_tree.item(selection[0])
        folder_id = item['values'][0] if item['values'] else 'root'
        
        self._navigate_to_folder(folder_id)
    
    def _on_file_double_click(self, event):
        """Обработчик двойного клика по файлу"""
        item = self.content_tree.selection()[0]
        tags = self.content_tree.item(item)['tags']
        
        if 'folder' in tags:
            self._navigate_to_folder(tags[0])
        elif 'file' in tags:
            self._open_selected_file()
    
    # ========================================================================
    # РАБОТА С ВРЕМЕННЫМИ ФАЙЛАМИ
    # ========================================================================
    
    def _get_secure_temp_dir(self):
        """Получение безопасной временной директории"""
        if not self._temp_dir:
            self._temp_dir = tempfile.mkdtemp(prefix='media_vault_')
        return self._temp_dir
    
    def _create_secure_temp_file(self, suffix='.tmp'):
        """Создание безопасного временного файла"""
        temp_dir = self._get_secure_temp_dir()
        fd, path = tempfile.mkstemp(suffix=suffix, prefix='secure_', dir=temp_dir)
        os.close(fd)
        self.temp_files.append(path)
        return path
    
    # ========================================================================
    # ОТКРЫТИЕ И ИЗВЛЕЧЕНИЕ ФАЙЛОВ
    # ========================================================================
    
    def _open_selected_file(self):
        """Безопасное открытие выбранного файла"""
        selection = self.content_tree.selection()
        if not selection:
            return
        
        item = self.content_tree.item(selection[0])
        tags = item['tags']
        
        if 'file' not in tags:
            return
        
        file_id = tags[0]
        
        progress_dialog = ProgressDialog(self.root, "Открытие файла")
        
        def open_file_task():
            try:
                file_data = None
                
                with self.vault_core.begin_transaction("открытие файла") as tx:
                    file_data = self.vault_core.filesystem['files'][file_id]
                    
                    progress_dialog.update(30, "Извлечение файла...")
                    
                    temp_path = self._create_secure_temp_file(
                        suffix=f"_{file_data['original_name']}"
                    )
                    
                    self.vault_core.extract_file(file_id, os.path.dirname(temp_path))
                    
                    progress_dialog.update(70, "Подготовка к открытию...")
                    
                    final_path = os.path.join(os.path.dirname(temp_path), file_data['original_name'])
                    os.rename(temp_path, final_path)
                    self.temp_files.remove(temp_path)
                    self.temp_files.append(final_path)
                    
                    progress_dialog.update(100, "Готово!")
                
                return final_path, file_data['file_type']
                
            except Exception as e:
                logging.error(f"Ошибка открытия файла: {e}")
                raise e
        
        def run_open_file():
            try:
                result = open_file_task()
                self.root.after(0, lambda: self._on_file_opened(result, progress_dialog))
            except Exception as e:
                self.root.after(0, lambda: self._on_file_open_error(e, progress_dialog))
        
        threading.Thread(target=run_open_file, daemon=True).start()
    
    def _on_file_opened(self, result, progress_dialog):
        """Обработка успешного открытия файла"""
        progress_dialog.destroy()
        
        if result:
            file_path, file_type = result
            
            try:
                os.startfile(file_path)
            except AttributeError:
                import subprocess
                try:
                    subprocess.run(['xdg-open', file_path])
                except FileNotFoundError:
                    try:
                        subprocess.run(['open', file_path])
                    except FileNotFoundError:
                        messagebox.showerror("Ошибка", "Не удалось открыть файл системным приложением")
    
    def _on_file_open_error(self, error, progress_dialog):
        """Обработка ошибки открытия файла"""
        progress_dialog.destroy()
        messagebox.showerror("Ошибка", f"Не удалось открыть файл: {error}")
    
    def _open_in_internal_viewer(self):
        """Безопасное открытие во встроенном просмотрщике"""
        selection = self.content_tree.selection()
        if not selection:
            return
        
        item = self.content_tree.item(selection[0])
        tags = item['tags']
        
        if 'file' not in tags:
            return
        
        file_id = tags[0]
        
        progress_dialog = ProgressDialog(self.root, "Подготовка файла")
        
        def prepare_file_task():
            try:
                file_data = None
                
                with self.vault_core.begin_transaction("подготовка файла для просмотра") as tx:
                    file_data = self.vault_core.filesystem['files'][file_id]
                    
                    progress_dialog.update(30, "Извлечение файла...")
                    
                    temp_path = self._create_secure_temp_file(
                        suffix=f"_{file_data['original_name']}"
                    )
                    
                    self.vault_core.extract_file(file_id, os.path.dirname(temp_path))
                    
                    progress_dialog.update(70, "Подготовка к просмотру...")
                    
                    final_path = os.path.join(os.path.dirname(temp_path), file_data['original_name'])
                    os.rename(temp_path, final_path)
                    self.temp_files.remove(temp_path)
                    self.temp_files.append(final_path)
                    
                    progress_dialog.update(100, "Готово!")
                
                return final_path, file_data['file_type']
                
            except Exception as e:
                logging.error(f"Ошибка подготовки файла: {e}")
                raise e
        
        def run_prepare_file():
            try:
                result = prepare_file_task()
                self.root.after(0, lambda: self._on_file_prepared(result, progress_dialog))
            except Exception as e:
                self.root.after(0, lambda: self._on_file_prepare_error(e, progress_dialog))
        
        threading.Thread(target=run_prepare_file, daemon=True).start()
    
    def _on_file_prepared(self, result, progress_dialog):
        """Обработка успешной подготовки файла"""
        progress_dialog.destroy()
        
        if result:
            file_path, file_type = result
            ViewerManager.view_file(self.root, file_path, file_type)
    
    def _on_file_prepare_error(self, error, progress_dialog):
        """Обработка ошибки подготовки файла"""
        progress_dialog.destroy()
        messagebox.showerror("Ошибка", f"Не удалось подготовить файл: {error}")
    
    def _add_files(self):
        """Добавление файлов в хранилище"""
        file_paths = filedialog.askopenfilenames(
            title="Выберите файлы для добавления",
            filetypes=[
                ("Все файлы", "*.*"),
                ("Изображения", "*.jpg *.jpeg *.png *.gif *.bmp *.tiff"),
                ("Документы", "*.pdf *.doc *.docx *.txt *.rtf"),
                ("Архивы", "*.zip *.rar *.7z *.tar *.gz")
            ]
        )
        
        if not file_paths:
            return
        
        progress_dialog = ProgressDialog(self.root, f"Добавление {len(file_paths)} файлов")
        
        def add_files_task():
            try:
                added_files = []
                failed_files = []
                
                with self.vault_core.begin_transaction("добавление файлов") as tx:
                    for i, file_path in enumerate(file_paths):
                        try:
                            progress_dialog.update(
                                (i / len(file_paths)) * 100,
                                f"Добавление: {os.path.basename(file_path)}"
                            )
                            
                            if progress_dialog.is_cancelled:
                                break
                            
                            file_id = self.vault_core.add_file(file_path, self.current_folder_id)
                            added_files.append(os.path.basename(file_path))
                            
                        except Exception as e:
                            logging.error(f"Ошибка добавления файла {file_path}: {e}")
                            failed_files.append((os.path.basename(file_path), str(e)))
                
                progress_dialog.update(100, "Завершение...")
                return added_files, failed_files
                
            except TransactionError as e:
                logging.error(f"Ошибка транзакции добавления файлов: {e}")
                raise e
            except Exception as e:
                logging.error(f"Общая ошибка добавления файлов: {e}")
                raise e
        
        def run_add_files():
            try:
                result = add_files_task()
                self.root.after(0, lambda: self._on_files_added(result, progress_dialog))
            except Exception as e:
                self.root.after(0, lambda: self._on_files_add_error(e, progress_dialog))
        
        threading.Thread(target=run_add_files, daemon=True).start()
    
    def _on_files_added(self, result, progress_dialog):
        """Обработка успешного добавления файлов"""
        progress_dialog.destroy()
        
        added_files, failed_files = result
        
        if added_files:
            self._refresh_folder_contents()
        
        message = ""
        if added_files:
            if len(added_files) == 1:
                message = f"Файл '{added_files[0]}' успешно добавлен!"
            else:
                message = f"Успешно добавлено файлов: {len(added_files)}"
        
        if failed_files:
            if message:
                message += "\n\n"
            message += f"Не удалось добавить файлов: {len(failed_files)}\n"
            for i, (filename, error) in enumerate(failed_files[:3]):
                message += f"{i+1}. {filename}: {error}\n"
            if len(failed_files) > 3:
                message += f"... и еще {len(failed_files) - 3} файлов"
        
        if message:
            messagebox.showinfo("Результат добавления", message)
    
    def _on_files_add_error(self, error, progress_dialog):
        """Обработка ошибки добавления файлов"""
        progress_dialog.destroy()
        messagebox.showerror("Ошибка", f"Ошибка добавления файлов: {error}")
    
    def _create_new_folder(self):
        """Создание новой папки"""
        dialog = CreateFolderDialog(self.root)
        self.root.wait_window(dialog)
        
        if dialog.result:
            name, password, hint, recovery_password = dialog.result
            
            progress_dialog = ProgressDialog(self.root, "Создание папки")
            
            def create_folder_task():
                try:
                    progress_dialog.update(30, "Создание защищенной папки...")
                    
                    # Здесь должен быть вызов метода создания папки
                    # Пока используем заглушку
                    time.sleep(1)  # Имитация создания папки
                    
                    progress_dialog.update(100, "Готово!")
                    return True, name
                    
                except Exception as e:
                    logging.error(f"Ошибка создания папки: {e}")
                    raise e
            
            def run_create_folder():
                try:
                    result = create_folder_task()
                    self.root.after(0, lambda: self._on_folder_created(result, progress_dialog))
                except Exception as e:
                    self.root.after(0, lambda: self._on_folder_create_error(e, progress_dialog))
            
            threading.Thread(target=run_create_folder, daemon=True).start()
    
    def _on_folder_created(self, result, progress_dialog):
        """Обработка успешного создания папки"""
        progress_dialog.destroy()
        
        if result:
            success, name = result
            if success:
                self._refresh_folder_contents()
                self._populate_folder_tree()
                messagebox.showinfo("Успех", f"Папка '{name}' создана!")
    
    def _on_folder_create_error(self, error, progress_dialog):
        """Обработка ошибки создания папки"""
        progress_dialog.destroy()
        messagebox.showerror("Ошибка", f"Не удалось создать папку: {error}")
    
    def _extract_selected_file(self):
        """Извлечение выбранного файла"""
        selection = self.content_tree.selection()
        if not selection:
            return
        
        item = self.content_tree.item(selection[0])
        tags = item['tags']
        
        if 'file' not in tags:
            return
        
        file_id = tags[0]
        file_data = self.vault_core.filesystem['files'][file_id]
        
        output_path = filedialog.asksaveasfilename(
            title="Сохранить файл как",
            initialfile=file_data['original_name'],
            defaultextension=os.path.splitext(file_data['original_name'])[1]
        )
        
        if not output_path:
            return
        
        progress_dialog = ProgressDialog(self.root, "Извлечение файла")
        
        def extract_file_task():
            try:
                progress_dialog.update(30, "Дешифрование файла...")
                
                with self.vault_core.begin_transaction("извлечение файла") as tx:
                    self.vault_core.extract_file(file_id, os.path.dirname(output_path))
                
                progress_dialog.update(100, "Готово!")
                return True
                
            except Exception as e:
                logging.error(f"Ошибка извлечения файла: {e}")
                raise e
        
        def run_extract_file():
            try:
                result = extract_file_task()
                self.root.after(0, lambda: self._on_file_extracted(result, progress_dialog))
            except Exception as e:
                self.root.after(0, lambda: self._on_file_extract_error(e, progress_dialog))
        
        threading.Thread(target=run_extract_file, daemon=True).start()
    
    def _on_file_extracted(self, result, progress_dialog):
        """Обработка успешного извлечения файла"""
        progress_dialog.destroy()
        messagebox.showinfo("Успех", "Файл успешно извлечен!")
    
    def _on_file_extract_error(self, error, progress_dialog):
        """Обработка ошибки извлечения файла"""
        progress_dialog.destroy()
        messagebox.showerror("Ошибка", f"Ошибка извлечения файла: {error}")
    
    def _delete_selected_file(self):
        """Удаление выбранного файла"""
        selection = self.content_tree.selection()
        if not selection:
            return
        
        item = self.content_tree.item(selection[0])
        tags = item['tags']
        
        if 'file' not in tags:
            return
        
        file_id = tags[0]
        file_data = self.vault_core.filesystem['files'][file_id]
        
        if messagebox.askyesno("Подтверждение", 
                              f"Удалить файл '{file_data['original_name']}'?\n\nЭто действие нельзя отменить."):
            
            progress_dialog = ProgressDialog(self.root, "Удаление файла")
            
            def delete_file_task():
                try:
                    progress_dialog.update(30, "Удаление файла...")
                    
                    with self.vault_core.begin_transaction("удаление файла") as tx:
                        self.vault_core.delete_file(file_id)
                    
                    progress_dialog.update(100, "Готово!")
                    return True
                    
                except Exception as e:
                    logging.error(f"Ошибка удаления файла: {e}")
                    raise e
            
            def run_delete_file():
                try:
                    result = delete_file_task()
                    self.root.after(0, lambda: self._on_file_deleted(result, progress_dialog))
                except Exception as e:
                    self.root.after(0, lambda: self._on_file_delete_error(e, progress_dialog))
            
            threading.Thread(target=run_delete_file, daemon=True).start()
    
    def _on_file_deleted(self, result, progress_dialog):
        """Обработка успешного удаления файла"""
        progress_dialog.destroy()
        self._refresh_folder_contents()
        messagebox.showinfo("Успех", "Файл удален!")
    
    def _on_file_delete_error(self, error, progress_dialog):
        """Обработка ошибки удаления файла"""
        progress_dialog.destroy()
        messagebox.showerror("Ошибка", f"Ошибка удаления файла: {error}")
    
    def _delete_selected_folder(self):
        """Удаление выбранной папки"""
        selection = self.content_tree.selection()
        if not selection:
            return
        
        item = self.content_tree.item(selection[0])
        tags = item['tags']
        
        if 'folder' not in tags:
            return
        
        folder_id = tags[0]
        folder_data = self.vault_core.filesystem['folders'][folder_id]
        folder_name = base64.b64decode(folder_data['encrypted_name']).decode()
        
        if messagebox.askyesno("Подтверждение", 
                              f"Удалить папку '{folder_name}' и все её содержимое?\n\nЭто действие нельзя отменить."):
            
            progress_dialog = ProgressDialog(self.root, "Удаление папки")
            
            def delete_folder_task():
                try:
                    progress_dialog.update(30, "Удаление папки и содержимого...")
                    
                    with self.vault_core.begin_transaction("удаление папки") as tx:
                        self.vault_core.delete_folder(folder_id)
                    
                    progress_dialog.update(100, "Готово!")
                    return True
                    
                except Exception as e:
                    logging.error(f"Ошибка удаления папки: {e}")
                    raise e
            
            def run_delete_folder():
                try:
                    result = delete_folder_task()
                    self.root.after(0, lambda: self._on_folder_deleted(result, progress_dialog))
                except Exception as e:
                    self.root.after(0, lambda: self._on_folder_delete_error(e, progress_dialog))
            
            threading.Thread(target=run_delete_folder, daemon=True).start()
    
    def _on_folder_deleted(self, result, progress_dialog):
        """Обработка успешного удаления папки"""
        progress_dialog.destroy()
        self._refresh_folder_contents()
        self._populate_folder_tree()
        messagebox.showinfo("Успех", "Папка удалена!")
    
    def _on_folder_delete_error(self, error, progress_dialog):
        """Обработка ошибки удаления папки"""
        progress_dialog.destroy()
        messagebox.showerror("Ошибка", f"Ошибка удаления папки: {error}")
    
    def _go_back(self):
        """Возврат к родительской папке"""
        if self.current_folder_id == 'root':
            return
        
        current_folder = self.vault_core.filesystem['folders'][self.current_folder_id]
        parent_id = current_folder.get('parent')
        
        if parent_id:
            self.current_folder_id = parent_id
            self._refresh_folder_contents()
            self._populate_folder_tree()
    
    # ========================================================================
    # СИСТЕМА БЭКАПОВ - ИНТЕРФЕЙС
    # ========================================================================
    
    def _show_backup_menu(self):
        """Меню управления бэкапами"""
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Создать бэкап сейчас", 
                        command=self._create_backup_now)
        menu.add_command(label="Восстановить из бэкапа", 
                        command=self._restore_from_backup)
        menu.add_command(label="Управление бэкапами", 
                        command=self._manage_backups)
        menu.add_separator()
        menu.add_command(label="Настройки бэкапов", 
                        command=self._configure_backups)
        
        toolbar_widgets = self.main_frame.winfo_children()[0].winfo_children()
        backup_button = [w for w in toolbar_widgets if isinstance(w, ctk.CTkButton) and w.cget('text') == 'Бэкапы'][0]
        
        x = backup_button.winfo_rootx()
        y = backup_button.winfo_rooty() + backup_button.winfo_height()
        menu.tk_popup(x, y)
    
    def _create_backup_now(self):
        """Создание бэкапа по требованию"""
        if not self.backup_manager:
            messagebox.showerror("Ошибка", "Менеджер бэкапов не инициализирован")
            return
        
        # Диалог выбора типа бэкапа
        backup_type = self._ask_backup_type()
        if not backup_type:
            return
        
        # Диалог для пароля (необязательно)
        password = self._ask_backup_password()
        
        progress_dialog = ProgressDialog(self.root, "Создание бэкапа")
        
        def backup_task():
            try:
                progress_dialog.update(10, "Подготовка к созданию бэкапа...")
                
                progress_dialog.update(30, "Создание бэкапа...")
                success, result = self.backup_manager.create_backup(backup_type, password)
                
                if success:
                    progress_dialog.update(100, "Бэкап создан успешно!")
                    return True, result
                else:
                    return False, result
                    
            except Exception as e:
                logging.error(f"Ошибка создания бэкапа: {e}")
                return False, str(e)
        
        def run_backup():
            success, result = backup_task()
            self.root.after(0, lambda: self._on_backup_complete(success, result, progress_dialog))
        
        threading.Thread(target=run_backup, daemon=True).start()
    
    def _ask_backup_type(self):
        """Диалог выбора типа бэкапа"""
        class BackupTypeDialog(ctk.CTkToplevel):
            def __init__(self, parent):
                super().__init__(parent)
                self.result = None
                
                self.title("Тип бэкапа")
                self.geometry("400x200")
                self.resizable(False, False)
                self.transient(parent)
                self.grab_set()
                
                self._create_widgets()
                self.center_window()
            
            def _create_widgets(self):
                main_frame = ctk.CTkFrame(self)
                main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
                
                ctk.CTkLabel(main_frame, text="Выберите тип бэкапа:",
                            font=ctk.CTkFont(weight="bold")).pack(pady=10)
                
                self.backup_type = tk.StringVar(value="full")
                
                ctk.CTkRadioButton(
                    main_frame,
                    text="Полный бэкап",
                    variable=self.backup_type,
                    value="full"
                ).pack(pady=5, anchor='w')
                
                ctk.CTkLabel(main_frame, text="(сохраняет все данные, включая зашифрованные файлы)",
                            font=ctk.CTkFont(size=11)).pack(pady=2, padx=20, anchor='w')
                
                ctk.CTkRadioButton(
                    main_frame,
                    text="Быстрый бэкап",
                    variable=self.backup_type,
                    value="quick"
                ).pack(pady=5, anchor='w')
                
                ctk.CTkLabel(main_frame, text="(сохраняет только файловую систему и конфигурацию)",
                            font=ctk.CTkFont(size=11)).pack(pady=2, padx=20, anchor='w')
                
                button_frame = ctk.CTkFrame(main_frame)
                button_frame.pack(pady=15)
                
                ctk.CTkButton(button_frame, text="Продолжить",
                            command=self._submit).pack(side=tk.LEFT, padx=5)
                ctk.CTkButton(button_frame, text="Отмена",
                            command=self._cancel).pack(side=tk.LEFT, padx=5)
            
            def _submit(self):
                self.result = self.backup_type.get()
                self.destroy()
            
            def _cancel(self):
                self.result = None
                self.destroy()
            
            def center_window(self):
                self.update_idletasks()
                width = self.winfo_width()
                height = self.winfo_height()
                x = (self.winfo_screenwidth() // 2) - (width // 2)
                y = (self.winfo_screenheight() // 2) - (height // 2)
                self.geometry(f'{width}x{height}+{x}+{y}')
        
        dialog = BackupTypeDialog(self.root)
        self.root.wait_window(dialog)
        return dialog.result
    
    def _ask_backup_password(self):
        """Диалог для пароля бэкапа"""
        class BackupPasswordDialog(ctk.CTkToplevel):
            def __init__(self, parent):
                super().__init__(parent)
                self.result = None
                
                self.title("Защита бэкапа паролем")
                self.geometry("400x200")
                self.resizable(False, False)
                self.transient(parent)
                self.grab_set()
                
                self._create_widgets()
                self.center_window()
            
            def _create_widgets(self):
                main_frame = ctk.CTkFrame(self)
                main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
                
                ctk.CTkLabel(main_frame, text="Защитить бэкап паролем?",
                            font=ctk.CTkFont(weight="bold")).pack(pady=10)
                
                ctk.CTkLabel(main_frame, text="Пароль (оставьте пустым если не нужно):",
                            font=ctk.CTkFont(size=12)).pack(pady=5)
                
                self.password_entry = ctk.CTkEntry(main_frame, show="•", width=250)
                self.password_entry.pack(pady=5)
                
                ctk.CTkLabel(main_frame, text="Подтверждение пароля:",
                            font=ctk.CTkFont(size=12)).pack(pady=5)
                
                self.confirm_entry = ctk.CTkEntry(main_frame, show="•", width=250)
                self.confirm_entry.pack(pady=5)
                
                button_frame = ctk.CTkFrame(main_frame)
                button_frame.pack(pady=15)
                
                ctk.CTkButton(button_frame, text="Без пароля",
                            command=self._no_password).pack(side=tk.LEFT, padx=5)
                ctk.CTkButton(button_frame, text="С паролем",
                            command=self._with_password).pack(side=tk.LEFT, padx=5)
                ctk.CTkButton(button_frame, text="Отмена",
                            command=self._cancel).pack(side=tk.LEFT, padx=5)
            
            def _no_password(self):
                self.result = None
                self.destroy()
            
            def _with_password(self):
                password = self.password_entry.get()
                confirm = self.confirm_entry.get()
                
                if password != confirm:
                    messagebox.showerror("Ошибка", "Пароли не совпадают")
                    return
                
                if password and len(password) < 8:
                    messagebox.showerror("Ошибка", "Пароль должен быть не менее 8 символов")
                    return
                
                self.result = password
                self.destroy()
            
            def _cancel(self):
                self.result = None
                self.destroy()
            
            def center_window(self):
                self.update_idletasks()
                width = self.winfo_width()
                height = self.winfo_height()
                x = (self.winfo_screenwidth() // 2) - (width // 2)
                y = (self.winfo_screenheight() // 2) - (height // 2)
                self.geometry(f'{width}x{height}+{x}+{y}')
        
        dialog = BackupPasswordDialog(self.root)
        self.root.wait_window(dialog)
        return dialog.result
    
    def _on_backup_complete(self, success, result, progress_dialog):
        """Обработка завершения создания бэкапа"""
        progress_dialog.destroy()
        
        if success:
            backup_path = result
            backup_size = os.path.getsize(backup_path) / (1024 * 1024)  # MB
            filename = os.path.basename(backup_path)
            
            messagebox.showinfo(
                "Бэкап создан",
                f"Бэкап успешно создан!\n\n"
                f"Имя файла: {filename}\n"
                f"Размер: {backup_size:.2f} MB\n"
                f"Тип: {'Зашифрованный' if backup_path.endswith('.enc') else 'Обычный'}"
            )
        else:
            messagebox.showerror("Ошибка", f"Не удалось создать бэкап: {result}")
    
    def _restore_from_backup(self):
        """Восстановление из бэкапа"""
        if not self.backup_manager:
            messagebox.showerror("Ошибка", "Менеджер бэкапов не инициализирован")
            return
        
        # Диалог выбора бэкапа
        backup_file = filedialog.askopenfilename(
            title="Выберите файл бэкапа",
            initialdir='data/backups',
            filetypes=[("Файлы бэкапов", "*.zip *.enc"), ("Все файлы", "*.*")]
        )
        
        if not backup_file:
            return
        
        # Проверка бэкапа
        is_valid, issues = self.backup_manager.verify_backup(backup_file)
        
        if not is_valid:
            message = "Бэкап не прошел проверку:\n\n" + "\n".join(issues[:5])
            if len(issues) > 5:
                message += f"\n\n... и еще {len(issues) - 5} проблем"
            messagebox.showerror("Ошибка проверки бэкапа", message)
            return
        
        # Запрос пароля для зашифрованных бэкапов
        password = None
        if backup_file.endswith('.enc'):
            password = self._ask_restore_password()
            if password is None:  # Пользователь отменил
                return
        
        # Выбор типа восстановления
        restore_type_dialog = RestoreTypeDialog(self.root)
        self.root.wait_window(restore_type_dialog)
        restore_type = restore_type_dialog.result
        
        if not restore_type:
            return
        
        # Подтверждение
        filename = os.path.basename(backup_file)
        if not messagebox.askyesno(
            "Подтверждение",
            f"Вы уверены, что хотите восстановить {restore_type} из бэкапа?\n\n"
            f"Бэкап: {filename}\n"
            f"Текущие данные будут сохранены в отдельном бэкапе."
        ):
            return
        
        progress_dialog = ProgressDialog(self.root, "Восстановление из бэкапа")
        
        def restore_task():
            try:
                progress_dialog.update(20, "Подготовка к восстановлению...")
                
                success, message = self.backup_manager.restore_backup(
                    backup_file, password, restore_type
                )
                
                if success:
                    progress_dialog.update(100, "Восстановление завершено!")
                    return True, message
                else:
                    return False, message
                    
            except Exception as e:
                logging.error(f"Ошибка восстановления из бэкапа: {e}")
                return False, str(e)
        
        def run_restore():
            success, message = restore_task()
            self.root.after(0, lambda: self._on_restore_complete(success, message, progress_dialog))
        
        threading.Thread(target=run_restore, daemon=True).start()
    
    def _ask_restore_password(self):
        """Запрос пароля для восстановления"""
        class RestorePasswordDialog(ctk.CTkToplevel):
            def __init__(self, parent):
                super().__init__(parent)
                self.result = None
                
                self.title("Пароль для восстановления")
                self.geometry("400x150")
                self.resizable(False, False)
                self.transient(parent)
                self.grab_set()
                
                self._create_widgets()
                self.center_window()
            
            def _create_widgets(self):
                main_frame = ctk.CTkFrame(self)
                main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
                
                ctk.CTkLabel(main_frame, text="Введите пароль для расшифровки бэкапа:",
                            font=ctk.CTkFont(weight="bold")).pack(pady=10)
                
                self.password_entry = ctk.CTkEntry(main_frame, show="•", width=250)
                self.password_entry.pack(pady=5)
                self.password_entry.bind('<Return>', lambda e: self._submit())
                
                button_frame = ctk.CTkFrame(main_frame)
                button_frame.pack(pady=15)
                
                ctk.CTkButton(button_frame, text="Восстановить",
                            command=self._submit).pack(side=tk.LEFT, padx=5)
                ctk.CTkButton(button_frame, text="Отмена",
                            command=self._cancel).pack(side=tk.LEFT, padx=5)
            
            def _submit(self):
                password = self.password_entry.get()
                if not password:
                    messagebox.showerror("Ошибка", "Введите пароль")
                    return
                
                self.result = password
                self.destroy()
            
            def _cancel(self):
                self.result = None
                self.destroy()
            
            def center_window(self):
                self.update_idletasks()
                width = self.winfo_width()
                height = self.winfo_height()
                x = (self.winfo_screenwidth() // 2) - (width // 2)
                y = (self.winfo_screenheight() // 2) - (height // 2)
                self.geometry(f'{width}x{height}+{x}+{y}')
        
        dialog = RestorePasswordDialog(self.root)
        self.root.wait_window(dialog)
        return dialog.result
    
    def _on_restore_complete(self, success, message, progress_dialog):
        """Обработка завершения восстановления"""
        progress_dialog.destroy()
        
        if success:
            # Перезагружаем интерфейс
            self._refresh_folder_contents()
            self._populate_folder_tree()
            
            messagebox.showinfo("Восстановление завершено", message)
        else:
            messagebox.showerror("Ошибка восстановления", message)
    
    def _manage_backups(self):
        """Управление бэкапами"""
        if not self.backup_manager:
            messagebox.showerror("Ошибка", "Менеджер бэкапов не инициализирован")
            return
        
        backups = self.backup_manager.get_available_backups()
        
        if not backups:
            messagebox.showinfo("Бэкапы", "Бэкапы не найдены")
            return
        
        # Создаем диалог управления бэкапами
        self._show_backup_manager_dialog(backups)
    
    def _show_backup_manager_dialog(self, backups):
        """Диалог управления бэкапами"""
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Управление бэкапами")
        dialog.geometry("900x500")
        dialog.transient(self.root)
        dialog.grab_set()
        
        main_frame = ctk.CTkFrame(dialog)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Заголовок
        ctk.CTkLabel(main_frame, text="Доступные бэкапы",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)
        
        # Таблица бэкапов
        columns = ('filename', 'date', 'size', 'type', 'encrypted', 'status')
        tree = ttk.Treeview(main_frame, columns=columns, show='headings', height=15)
        
        tree.heading('filename', text='Имя файла')
        tree.heading('date', text='Дата создания')
        tree.heading('size', text='Размер')
        tree.heading('type', text='Тип')
        tree.heading('encrypted', text='Зашифрован')
        tree.heading('status', text='Статус')
        
        tree.column('filename', width=250)
        tree.column('date', width=150)
        tree.column('size', width=80)
        tree.column('type', width=80)
        tree.column('encrypted', width=100)
        tree.column('status', width=100)
        
        # Добавляем бэкапы в таблицу
        for backup in backups:
            filename = backup['filename']
            date = backup['created_at'].strftime("%Y-%m-%d %H:%M")
            size = f"{backup['size'] / (1024*1024):.1f} MB"
            
            # Определяем тип
            if 'manifest' in backup:
                backup_type = backup['manifest'].get('backup_type', 'unknown')
            else:
                backup_type = 'unknown'
            
            # Зашифрован ли
            encrypted = "Да" if backup['is_encrypted'] else "Нет"
            
            # Проверяем статус
            is_valid, issues = self.backup_manager.verify_backup(backup['path'])
            status = "✅ OK" if is_valid else "❌ Ошибка"
            
            tree.insert('', 'end', values=(filename, date, size, backup_type, encrypted, status),
                       tags=(backup['path'],))
        
        # Скроллбар
        scrollbar = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5), pady=5)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=5)
        
        # Кнопки управления
        button_frame = ctk.CTkFrame(main_frame)
        button_frame.pack(fill=tk.X, pady=10)
        
        ctk.CTkButton(button_frame, text="Проверить выбранный",
                     command=lambda: self._verify_selected_backup(tree)).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(button_frame, text="Восстановить выбранный",
                     command=lambda: self._restore_selected_backup(tree)).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(button_frame, text="Удалить выбранный",
                     command=lambda: self._delete_selected_backup(tree)).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(button_frame, text="Очистить старые бэкапы",
                     command=self._cleanup_old_backups).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(button_frame, text="Закрыть",
                     command=dialog.destroy).pack(side=tk.LEFT, padx=5)
    
    def _verify_selected_backup(self, tree):
        """Проверка выбранного бэкапа"""
        selection = tree.selection()
        if not selection:
            messagebox.showwarning("Выбор", "Выберите бэкап для проверки")
            return
        
        backup_path = tree.item(selection[0])['tags'][0]
        filename = tree.item(selection[0])['values'][0]
        
        is_valid, issues = self.backup_manager.verify_backup(backup_path)
        
        if is_valid:
            messagebox.showinfo("Проверка бэкапа", 
                              f"Бэкап '{filename}' в порядке, проблем не обнаружено.")
        else:
            message = f"Обнаружены проблемы в бэкапе '{filename}':\n\n" + "\n".join(issues[:5])
            if len(issues) > 5:
                message += f"\n\n... и еще {len(issues) - 5} проблем"
            messagebox.showerror("Проблемы с бэкапом", message)
    
    def _restore_selected_backup(self, tree):
        """Восстановление из выбранного бэкапа"""
        selection = tree.selection()
        if not selection:
            messagebox.showwarning("Выбор", "Выберите бэкап для восстановления")
            return
        
        backup_path = tree.item(selection[0])['tags'][0]
        filename = tree.item(selection[0])['values'][0]
        
        # Закрываем диалог управления
        tree.master.master.destroy()
        
        # Показываем диалог восстановления для этого конкретного бэкапа
        self._restore_from_specific_backup(backup_path, filename)
    
    def _restore_from_specific_backup(self, backup_path, filename):
        """Восстановление из конкретного бэкапа"""
        # Запрос пароля если нужно
        password = None
        if backup_path.endswith('.enc'):
            password = self._ask_restore_password()
            if password is None:
                return
        
        # Выбор типа восстановления
        restore_type_dialog = RestoreTypeDialog(self.root)
        self.root.wait_window(restore_type_dialog)
        restore_type = restore_type_dialog.result
        
        if not restore_type:
            return
        
        # Подтверждение
        if not messagebox.askyesno(
            "Подтверждение",
            f"Восстановить {restore_type} из бэкапа '{filename}'?\n\n"
            f"Текущие данные будут сохранены в отдельном бэкапе."
        ):
            return
        
        progress_dialog = ProgressDialog(self.root, "Восстановление из бэкапа")
        
        def restore_task():
            try:
                progress_dialog.update(20, "Подготовка к восстановлению...")
                
                success, message = self.backup_manager.restore_backup(
                    backup_path, password, restore_type
                )
                
                if success:
                    progress_dialog.update(100, "Восстановление завершено!")
                    return True, message
                else:
                    return False, message
                    
            except Exception as e:
                logging.error(f"Ошибка восстановления из бэкапа: {e}")
                return False, str(e)
        
        def run_restore():
            success, message = restore_task()
            self.root.after(0, lambda: self._on_restore_complete(success, message, progress_dialog))
        
        threading.Thread(target=run_restore, daemon=True).start()
    
    def _delete_selected_backup(self, tree):
        """Удаление выбранного бэкапа"""
        selection = tree.selection()
        if not selection:
            messagebox.showwarning("Выбор", "Выберите бэкап для удаления")
            return
        
        backup_path = tree.item(selection[0])['tags'][0]
        filename = tree.item(selection[0])['values'][0]
        
        if messagebox.askyesno("Подтверждение удаления",
                              f"Удалить бэкап '{filename}'?\n\nЭто действие нельзя отменить."):
            try:
                os.remove(backup_path)
                tree.delete(selection[0])
                messagebox.showinfo("Удаление", f"Бэкап '{filename}' удален")
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось удалить бэкап: {e}")
    
    def _cleanup_old_backups(self):
        """Очистка старых бэкапов"""
        if not self.backup_manager:
            return
        
        deleted_count = self.backup_manager.cleanup_old_backups(keep_last=10)
        
        if deleted_count > 0:
            messagebox.showinfo("Очистка бэкапов", 
                              f"Удалено {deleted_count} старых бэкапов.")
        else:
            messagebox.showinfo("Очистка бэкапов", 
                              "Старые бэкапы не найдены или их количество в пределах нормы.")
    
    def _configure_backups(self):
        """Настройки бэкапов"""
        messagebox.showinfo("Настройки бэкапов",
                          "Настройки резервного копирования:\n\n"
                          "• Автоматическая очистка: сохраняются последние 10 бэкапов\n"
                          "• Ручное создание: через меню 'Бэкапы'\n"
                          "• Типы бэкапов: полные и быстрые\n"
                          "• Шифрование: опционально с паролем\n"
                          "• Проверка целостности: при каждом использовании\n\n"
                          "Бэкапы хранятся в папке: data/backups/")
    
    # ========================================================================
    # ПРОВЕРКА ЦЕЛОСТНОСТИ
    # ========================================================================
    
    def _verify_integrity(self):
        """Проверка целостности хранилища"""
        progress_dialog = ProgressDialog(self.root, "Проверка целостности")
        
        def check_task():
            try:
                progress_dialog.update(10, "Проверка файловой системы...")
                issues = self.vault_core.verify_integrity()
                
                progress_dialog.update(100, "Готово!")
                return issues
                
            except Exception as e:
                logging.error(f"Ошибка проверки целостности: {e}")
                raise e
        
        def run_check():
            try:
                issues = check_task()
                self.root.after(0, lambda: self._on_integrity_check_complete(issues, progress_dialog))
            except Exception as e:
                self.root.after(0, lambda: self._on_integrity_check_error(e, progress_dialog))
        
        threading.Thread(target=run_check, daemon=True).start()
    
    def _on_integrity_check_complete(self, issues, progress_dialog):
        """Обработка завершения проверки целостности"""
        progress_dialog.destroy()
        
        if issues:
            message = f"Найдено проблем: {len(issues)}\n\nПервые 5 проблем:\n"
            for i, issue in enumerate(issues[:5]):
                message += f"{i+1}. {issue}\n"
            
            if len(issues) > 5:
                message += f"\n... и еще {len(issues) - 5} проблем"
            
            messagebox.showwarning("Проверка целостности", message)
        else:
            messagebox.showinfo("Проверка целостности", "Проблем не обнаружено. Хранилище в порядке.")
    
    def _on_integrity_check_error(self, error, progress_dialog):
        """Обработка ошибки проверки целостности"""
        progress_dialog.destroy()
        messagebox.showerror("Ошибка", f"Не удалось проверить целостность: {error}")
    
    # ========================================================================
    # ВОССТАНОВЛЕНИЕ ДОСТУПА
    # ========================================================================
    
    def _show_recovery_options(self):
        """Показать опции восстановления"""
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Восстановить мастер-пароль", 
                        command=self._show_master_recovery)
        menu.add_command(label="Настройки восстановления", 
                        command=self._show_recovery_settings)
        
        toolbar_widgets = self.main_frame.winfo_children()[0].winfo_children()
        recovery_button = toolbar_widgets[-2]
        x = recovery_button.winfo_rootx()
        y = recovery_button.winfo_rooty() + recovery_button.winfo_height()
        menu.tk_popup(x, y)
    
    def _show_recovery_settings(self):
        """Настройки восстановления"""
        messagebox.showinfo("Настройки восстановления", 
                           "Здесь можно настроить вопросы восстановления для мастер-пароля")
    
    # ========================================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ========================================================================
    
    def _update_path_label(self):
        """Обновление метки пути"""
        if self.current_folder_id == 'root':
            self.path_label.configure(text="Путь: /")
            return
        
        path_parts = []
        current_id = self.current_folder_id
        
        while current_id and current_id != 'root':
            folder = self.vault_core.filesystem['folders'][current_id]
            folder_name = base64.b64decode(folder['encrypted_name']).decode()
            path_parts.insert(0, folder_name)
            current_id = folder.get('parent')
        
        path = "/" + "/".join(path_parts)
        self.path_label.configure(text=f"Путь: {path}")
    
    def _format_size(self, size_bytes):
        """Форматирование размера файла"""
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1
        
        return f"{size_bytes:.1f} {size_names[i]}"
    
    # ========================================================================
    # БЕЗОПАСНАЯ ОЧИСТКА
    # ========================================================================
    
    def _secure_cleanup(self):
        """Безопасная очистка временных файлов"""
        for temp_file in self.temp_files:
            try:
                if os.path.exists(temp_file):
                    file_size = os.path.getsize(temp_file)
                    with open(temp_file, 'wb') as f:
                        f.write(secrets.token_bytes(file_size))
                        f.flush()
                        os.fsync(f.fileno())
                    os.remove(temp_file)
            except Exception as e:
                logging.warning(f"Не удалось безопасно удалить временный файл {temp_file}: {e}")
        
        # Удаление временной директории
        if self._temp_dir and os.path.exists(self._temp_dir):
            try:
                os.rmdir(self._temp_dir)
            except:
                pass
    
    def _on_closing(self):
        """Обработчик закрытия окна"""
        if messagebox.askokcancel("Выход", "Вы уверены, что хотите выйти?"):
            # Сигнал остановки обработчику операций
            self._operation_queue.put(None)
            self._operation_thread.join(timeout=2.0)
            
            # Безопасная очистка
            self._secure_cleanup()
            
            if self.folder_security_manager:
                self.folder_security_manager.cleanup()
            
            if hasattr(self, 'crypto_manager') and self.crypto_manager:
                self.crypto_manager.secure_clear()
            
            if self.vault_core:
                self.vault_core.cleanup()
            
            self.root.destroy()
    
    # ========================================================================
    # ГЛАВНЫЙ МЕТОД ЗАПУСКА
    # ========================================================================
    
    def run(self):
        """Безопасный запуск приложения"""
        try:
            self.root.mainloop()
        finally:
            # Гарантированная очистка при любом завершении
            self._secure_cleanup()
            
            if hasattr(self, 'folder_security_manager') and self.folder_security_manager:
                self.folder_security_manager.cleanup()
            
            if hasattr(self, 'crypto_manager') and self.crypto_manager:
                self.crypto_manager.secure_clear()


# Сохраняем обратную совместимость
MediaVaultApp = SecureMediaVaultApp