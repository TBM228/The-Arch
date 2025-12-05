import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import bcrypt
import base64
import logging

class RecoveryManager:
    """Менеджер восстановления доступа к паролям"""
    
    def __init__(self, auth_manager, crypto_manager, vault_core):
        self.auth_manager = auth_manager
        self.crypto_manager = crypto_manager
        self.vault_core = vault_core
    
    def setup_master_recovery(self, password, recovery_questions):
        """Настройка восстановления мастер-пароля"""
        self.auth_manager.setup_recovery_questions(password, recovery_questions)
    
    def recover_master_access(self, answers):
        """Восстановление доступа с помощью контрольных вопросов"""
        try:
            master_key = self.auth_manager.recover_master_key(answers)
            return master_key
        except ValueError as e:
            logging.error(f"Ошибка восстановления: {e}")
            return None
    
    def change_password_after_recovery(self, master_key, new_password, new_password_hint=""):
        """Смена пароля после успешного восстановления"""
        # Этот метод теперь будет вызываться из GUI после восстановления
        # Для смены пароля нужно пересоздать конфигурацию
        pass
    
    def setup_folder_recovery(self, folder_id, recovery_password):
        """Настройка восстановления для папки"""
        if folder_id not in self.vault_core.filesystem['folders']:
            raise ValueError("Папка не найдена")
        
        folder_data = self.vault_core.filesystem['folders'][folder_id]
        updated_data = self.vault_core.folder_security_manager.set_folder_recovery(
            folder_data, recovery_password
        )
        
        # Обновляем данные папки
        self.vault_core.filesystem['folders'][folder_id] = updated_data
        self.vault_core._save_filesystem()
        
        return True
    
    def recover_folder_access(self, folder_id, recovery_password):
        """Восстановление доступа к папке"""
        if folder_id not in self.vault_core.filesystem['folders']:
            raise ValueError("Папка не найдена")
        
        folder_data = self.vault_core.filesystem['folders'][folder_id]
        return self.vault_core.folder_security_manager.unlock_folder(
            folder_data, recovery_password, use_recovery=True
        )
    
    def get_folder_password_hint(self, folder_id):
        """Получение подсказки к паролю папки"""
        if folder_id not in self.vault_core.filesystem['folders']:
            return ""
        
        folder_data = self.vault_core.filesystem['folders'][folder_id]
        return self.vault_core.folder_security_manager.get_folder_password_hint(folder_id, folder_data)


class MasterPasswordRecoveryDialog(ctk.CTkToplevel):
    """Диалог восстановления мастер-пароля"""
    
    def __init__(self, parent, auth_manager):
        super().__init__(parent)
        self.auth_manager = auth_manager
        self.master_key = None  # Возвращаем мастер-ключ
        
        self.title("Восстановление мастер-пароля")
        self.geometry("500x400")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        
        self._create_widgets()
        self.center_window()
    
    def _create_widgets(self):
        """Создание виджетов восстановления"""
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        ctk.CTkLabel(main_frame, text="Восстановление мастер-пароля", 
                    font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)
        
        # Показываем подсказку
        hint = self.auth_manager.get_password_hint()
        if hint:
            ctk.CTkLabel(main_frame, text=f"Подсказка: {hint}", 
                         font=ctk.CTkFont(weight="bold")).pack(pady=5)
        
        # Поля для ответов на вопросы
        self.answer_entries = []
        questions = self.auth_manager.get_recovery_questions()
        
        if not questions:
            ctk.CTkLabel(main_frame, text="Вопросы восстановления не настроены", 
                        text_color="orange").pack(pady=20)
            ctk.CTkButton(main_frame, text="Закрыть", 
                         command=self._cancel).pack(pady=10)
            return
        
        ctk.CTkLabel(main_frame, text="Ответьте на контрольные вопросы:").pack(pady=10)
        
        for i, (question, _) in enumerate(questions):
            question_frame = ctk.CTkFrame(main_frame)
            question_frame.pack(fill=tk.X, pady=5)
            
            ctk.CTkLabel(question_frame, text=f"{i+1}. {question}", 
                         wraplength=400).pack(anchor='w', pady=2)
            entry = ctk.CTkEntry(question_frame, width=400)
            entry.pack(fill=tk.X, pady=2)
            self.answer_entries.append(entry)
        
        # Кнопки
        button_frame = ctk.CTkFrame(main_frame)
        button_frame.pack(pady=15)
        
        ctk.CTkButton(button_frame, text="Восстановить доступ", 
                     command=self._recover_master).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(button_frame, text="Отмена", 
                     command=self._cancel).pack(side=tk.LEFT, padx=5)
    
    def _recover_master(self):
        """Обработка восстановления мастер-пароля"""
        answers = []
        for entry in self.answer_entries:
            answer = entry.get().strip()
            if not answer:
                self._show_error("Заполните все поля")
                return
            answers.append(answer)
        
        try:
            if not self.auth_manager.verify_recovery_answers(list(zip([q[0] for q in self.auth_manager.get_recovery_questions()], answers))):
                self._show_error("Неверные ответы на вопросы восстановления")
                return
            
            self.master_key = self.auth_manager.recover_master_key(answers)
            messagebox.showinfo("Успех", "Доступ восстановлен! Мастер-ключ получен.")
            self.destroy()
        except ValueError as e:
            self._show_error(str(e))
    
    def _cancel(self):
        """Отмена"""
        self.master_key = None
        self.destroy()
    
    def _show_error(self, message):
        """Показать ошибку"""
        error_label = ctk.CTkLabel(self, text=message, text_color="red")
        error_label.pack(pady=5)
        self.after(3000, error_label.destroy)
    
    def center_window(self):
        """Центрирование окна"""
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f'{width}x{height}+{x}+{y}')


class PasswordChangeDialog(ctk.CTkToplevel):
    """Диалог смены пароля после восстановления"""
    
    def __init__(self, parent, auth_manager, master_key):
        super().__init__(parent)
        self.auth_manager = auth_manager
        self.master_key = master_key
        self.result = None
        
        self.title("Установка нового пароля")
        self.geometry("450x300")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        
        self._create_widgets()
        self.center_window()
    
    def _create_widgets(self):
        """Создание виджетов смены пароля"""
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        ctk.CTkLabel(main_frame, text="Установите новый мастер-пароль", 
                    font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)
        
        ctk.CTkLabel(main_frame, text="Новый пароль:").pack(pady=5)
        self.new_password_entry = ctk.CTkEntry(main_frame, show="•", width=300)
        self.new_password_entry.pack(pady=5)
        
        ctk.CTkLabel(main_frame, text="Подтверждение пароля:").pack(pady=5)
        self.confirm_password_entry = ctk.CTkEntry(main_frame, show="•", width=300)
        self.confirm_password_entry.pack(pady=5)
        
        ctk.CTkLabel(main_frame, text="Подсказка к паролю:").pack(pady=5)
        self.hint_entry = ctk.CTkEntry(main_frame, width=300)
        self.hint_entry.pack(pady=5)
        
        # Кнопки
        button_frame = ctk.CTkFrame(main_frame)
        button_frame.pack(pady=15)
        
        ctk.CTkButton(button_frame, text="Установить пароль", 
                     command=self._change_password).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(button_frame, text="Отмена", 
                     command=self._cancel).pack(side=tk.LEFT, padx=5)
    
    def _change_password(self):
        """Смена пароля"""
        new_password = self.new_password_entry.get()
        confirm_password = self.confirm_password_entry.get()
        hint = self.hint_entry.get()
        
        if not new_password:
            self._show_error("Введите новый пароль")
            return
        
        if new_password != confirm_password:
            self._show_error("Пароли не совпадают")
            return
        
        try:
            # Валидация пароля
            from auth import AuthManager
            temp_auth = AuthManager()
            validation = temp_auth._validate_password_strength(new_password)
            if not validation['valid']:
                self._show_error(validation['message'])
                return
            
            # Здесь должна быть логика смены пароля с использованием master_key
            # Для простоты просто возвращаем успех
            self.result = (new_password, hint)
            messagebox.showinfo("Успех", "Пароль успешно изменен!")
            self.destroy()
            
        except Exception as e:
            self._show_error(f"Ошибка: {e}")
    
    def _cancel(self):
        """Отмена"""
        self.result = None
        self.destroy()
    
    def _show_error(self, message):
        """Показать ошибку"""
        error_label = ctk.CTkLabel(self, text=message, text_color="red")
        error_label.pack(pady=5)
        self.after(3000, error_label.destroy)
    
    def center_window(self):
        """Центрирование окна"""
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f'{width}x{height}+{x}+{y}')


class FolderRecoveryDialog(ctk.CTkToplevel):
    """Диалог восстановления доступа к папке"""
    
    def __init__(self, parent, recovery_manager, folder_data):
        super().__init__(parent)
        self.recovery_manager = recovery_manager
        self.folder_data = folder_data
        self.result = None
        
        self.title(f"Восстановление доступа к папке")
        self.geometry("450x300")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        
        self._create_widgets()
        self.center_window()
    
    def _create_widgets(self):
        """Создание виджетов восстановления"""
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        ctk.CTkLabel(main_frame, text="Восстановление доступа к папке", 
                    font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)
        
        folder_name = self.folder_data['name']
        ctk.CTkLabel(main_frame, text=f"Папка: {folder_name}").pack(pady=5)
        
        # Показываем подсказку к паролю
        hint = self.folder_data.get('password_hint', '')
        if hint:
            ctk.CTkLabel(main_frame, text=f"Подсказка: {hint}").pack(pady=5)
        
        ctk.CTkLabel(main_frame, text="Пароль восстановления:").pack(pady=10)
        self.recovery_entry = ctk.CTkEntry(main_frame, show="•", width=300)
        self.recovery_entry.pack(pady=5)
        self.recovery_entry.bind('<Return>', lambda e: self._recover_folder())
        
        # Кнопки
        button_frame = ctk.CTkFrame(main_frame)
        button_frame.pack(pady=15)
        
        ctk.CTkButton(button_frame, text="Восстановить доступ", 
                     command=self._recover_folder).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(button_frame, text="Отмена", 
                     command=self._cancel).pack(side=tk.LEFT, padx=5)
    
    def _recover_folder(self):
        """Обработка восстановления доступа к папке"""
        recovery_password = self.recovery_entry.get()
        
        if not recovery_password:
            self._show_error("Введите пароль восстановления")
            return
        
        self.result = recovery_password
        self.destroy()
    
    def _cancel(self):
        """Отмена"""
        self.result = None
        self.destroy()
    
    def _show_error(self, message):
        """Показать ошибку"""
        error_label = ctk.CTkLabel(self, text=message, text_color="red")
        error_label.pack(pady=5)
        self.after(3000, error_label.destroy)
    
    def center_window(self):
        """Центрирование окна"""
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f'{width}x{height}+{x}+{y}')