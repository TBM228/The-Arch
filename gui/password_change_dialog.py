import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox

class PasswordChangeDialog(ctk.CTkToplevel):
    """Диалог смены пароля после восстановления"""
    
    def __init__(self, parent, auth_manager, master_key):
        super().__init__(parent)
        self.auth_manager = auth_manager
        self.master_key = master_key
        self.result = None
        
        self.title("Установка нового пароля")
        self.geometry("450x350")
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
        
        # Информация о требованиях к паролю
        requirements = """Требования к паролю:
• Минимум 8 символов
• Заглавные и строчные буквы
• Хотя бы одна цифра  
• Хотя бы один специальный символ
• Только латинские буквы"""
        
        ctk.CTkLabel(main_frame, text=requirements, 
                     font=ctk.CTkFont(size=11), justify=tk.LEFT).pack(pady=10)
        
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
            validation = self.auth_manager._validate_password_strength(new_password)
            if not validation['valid']:
                self._show_error(validation['message'])
                return
            
            # В реальной реализации здесь будет вызов метода смены пароля
            # который использует self.master_key для перешифровки
            self.result = (new_password, hint, self.master_key)
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