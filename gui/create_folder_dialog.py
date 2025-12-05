import customtkinter as ctk
import tkinter as tk
import re

class CreateFolderDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.result = None
        
        self.title("Создать новую папку")
        self.geometry("500x400")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        
        self._create_widgets()
        self.center_window()
    
    def _create_widgets(self):
        """Создание виджетов"""
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        ctk.CTkLabel(main_frame, text="Создать защищенную папку", 
                     font=ctk.CTkFont(weight="bold")).pack(pady=5)
        
        # Имя папки
        ctk.CTkLabel(main_frame, text="Имя папки:").pack(pady=5)
        self.name_entry = ctk.CTkEntry(main_frame, width=300)
        self.name_entry.pack(pady=5)
        
        # Пароль папки
        ctk.CTkLabel(main_frame, text="Пароль папки:").pack(pady=5)
        self.password_entry = ctk.CTkEntry(main_frame, show="•", width=300)
        self.password_entry.pack(pady=5)
        
        # Подтверждение пароля
        ctk.CTkLabel(main_frame, text="Подтверждение пароля:").pack(pady=5)
        self.confirm_password_entry = ctk.CTkEntry(main_frame, show="•", width=300)
        self.confirm_password_entry.pack(pady=5)
        
        # Подсказка к паролю
        ctk.CTkLabel(main_frame, text="Подсказка к паролю (необязательно):").pack(pady=5)
        self.hint_entry = ctk.CTkEntry(main_frame, width=300)
        self.hint_entry.pack(pady=5)
        
        # Пароль восстановления
        ctk.CTkLabel(main_frame, text="Пароль восстановления:").pack(pady=5)
        ctk.CTkLabel(main_frame, text="(для восстановления доступа если забудете пароль)", 
                     font=ctk.CTkFont(size=12)).pack()
        self.recovery_entry = ctk.CTkEntry(main_frame, show="•", width=300)
        self.recovery_entry.pack(pady=5)
        
        # Подтверждение пароля восстановления
        ctk.CTkLabel(main_frame, text="Подтверждение пароля восстановления:").pack(pady=5)
        self.confirm_recovery_entry = ctk.CTkEntry(main_frame, show="•", width=300)
        self.confirm_recovery_entry.pack(pady=5)
        
        # Кнопки
        button_frame = ctk.CTkFrame(main_frame)
        button_frame.pack(pady=15)
        
        ctk.CTkButton(button_frame, text="Создать", 
                      command=self._create).pack(side=tk.LEFT, padx=5)
        ctk.CTkButton(button_frame, text="Отмена", 
                      command=self._cancel).pack(side=tk.LEFT, padx=5)
        
        self.name_entry.focus()
    
    def _validate_password(self, password):
        """Валидация пароля"""
        if len(password) < 8:
            return "Пароль должен содержать минимум 8 символов"
        
        if not re.search(r'[A-Z]', password):
            return "Пароль должен содержать хотя бы одну заглавную букву"
        
        if not re.search(r'[a-z]', password):
            return "Пароль должен содержать хотя бы одну строчную букву"
        
        if not re.search(r'\d', password):
            return "Пароль должен содержать хотя бы одну цифру"
        
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            return "Пароль должен содержать хотя бы один специальный символ"
        
        if not re.match(r'^[A-Za-z0-9!@#$%^&*(),.?":{}|<>]+$', password):
            return "Пароль должен содержать только латинские буквы, цифры и специальные символы"
        
        return None
    
    def _create(self):
        """Создание папки"""
        name = self.name_entry.get().strip()
        password = self.password_entry.get()
        confirm_password = self.confirm_password_entry.get()
        hint = self.hint_entry.get().strip()
        recovery_password = self.recovery_entry.get()
        confirm_recovery = self.confirm_recovery_entry.get()
        
        if not name:
            self._show_error("Введите имя папки")
            return
        
        if not password:
            self._show_error("Введите пароль папки")
            return
        
        if password != confirm_password:
            self._show_error("Пароли не совпадают")
            return
        
        # Валидация пароля
        password_error = self._validate_password(password)
        if password_error:
            self._show_error(password_error)
            return
        
        if recovery_password:
            if recovery_password != confirm_recovery:
                self._show_error("Пароли восстановления не совпадают")
                return
            
            # Валидация пароля восстановления
            recovery_error = self._validate_password(recovery_password)
            if recovery_error:
                self._show_error(f"Пароль восстановления: {recovery_error}")
                return
        
        self.result = (name, password, hint, recovery_password if recovery_password else None)
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