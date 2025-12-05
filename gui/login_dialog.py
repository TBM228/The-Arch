import customtkinter as ctk
import tkinter as tk

class LoginDialog(ctk.CTkToplevel):
    def __init__(self, parent, auth_manager):
        super().__init__(parent)
        self.auth_manager = auth_manager
        self.result = None
        
        self.title("Media Vault - Вход")
        self.geometry("400x200")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        
        self._create_widgets()
        self.center_window()
    
    def _create_widgets(self):
        """Создание виджетов"""
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        ctk.CTkLabel(main_frame, text="Вход в Media Vault", 
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)
        
        ctk.CTkLabel(main_frame, text="Мастер-пароль:").pack(pady=5)
        self.password_entry = ctk.CTkEntry(main_frame, show="•", width=250)
        self.password_entry.pack(pady=5)
        self.password_entry.bind('<Return>', lambda e: self._login())
        
        # Кнопки
        button_frame = ctk.CTkFrame(main_frame)
        button_frame.pack(pady=15)
        
        ctk.CTkButton(button_frame, text="Войти", 
                      command=self._login).pack(side=tk.LEFT, padx=10)
        ctk.CTkButton(button_frame, text="Отмена", 
                      command=self._cancel).pack(side=tk.LEFT, padx=10)
        
        self.password_entry.focus()
    
    def _login(self):
        """Обработка входа"""
        password = self.password_entry.get()
        
        if not password:
            self._show_error("Введите пароль")
            return
        
        try:
            if self.auth_manager.verify_master_password(password):
                self.result = password
                self.destroy()
            else:
                self._show_error("Неверный пароль")
        except Exception as e:
            self._show_error(f"Ошибка: {e}")
    
    def _cancel(self):
        """Отмена входа"""
        self.result = None
        self.destroy()
    
    def _show_error(self, message):
        """Показать ошибку"""
        error_label = ctk.CTkLabel(self, text=message, text_color="red")
        error_label.pack(pady=5)
        self.after(3000, error_label.destroy)  # Автоматическое удаление через 3 секунды
    
    def center_window(self):
        """Центрирование окна"""
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f'{width}x{height}+{x}+{y}')