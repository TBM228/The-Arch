import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox

class FolderPasswordDialog(ctk.CTkToplevel):
    def __init__(self, parent, folder_data, recovery_manager=None):
        super().__init__(parent)
        self.folder_data = folder_data
        self.recovery_manager = recovery_manager
        self.result = None
        
        folder_name = folder_data['name']
        self.title(f"Доступ к папке: {folder_name}")
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
        
        folder_name = self.folder_data['name']
        ctk.CTkLabel(main_frame, text=f"Папка '{folder_name}' защищена паролем", 
                     font=ctk.CTkFont(weight="bold")).pack(pady=5)
        
        # Показываем подсказку
        hint = self.folder_data.get('password_hint', '')
        if hint:
            ctk.CTkLabel(main_frame, text=f"Подсказка: {hint}").pack(pady=5)
        
        ctk.CTkLabel(main_frame, text="Введите пароль папки:").pack(pady=5)
        self.password_entry = ctk.CTkEntry(main_frame, show="•", width=300)
        self.password_entry.pack(pady=5)
        self.password_entry.bind('<Return>', lambda e: self._submit())
        
        # Опция восстановления
        if self.recovery_manager and self.folder_data.get('recovery_key'):
            self.use_recovery = tk.BooleanVar()
            recovery_check = ctk.CTkCheckBox(main_frame, 
                                           text="Использовать восстановление",
                                           variable=self.use_recovery)
            recovery_check.pack(pady=5)
        else:
            self.use_recovery = tk.BooleanVar(value=False)
        
        # Кнопки
        button_frame = ctk.CTkFrame(main_frame)
        button_frame.pack(pady=10)
        
        ctk.CTkButton(button_frame, text="Разблокировать", 
                      command=self._submit).pack(side=tk.LEFT, padx=5)
        
        if self.recovery_manager and self.folder_data.get('recovery_key'):
            ctk.CTkButton(button_frame, text="Восстановить доступ", 
                          command=self._show_recovery).pack(side=tk.LEFT, padx=5)
        
        ctk.CTkButton(button_frame, text="Отмена", 
                      command=self._cancel).pack(side=tk.LEFT, padx=5)
        
        self.password_entry.focus()
    
    def _submit(self):
        """Подтверждение пароля"""
        password = self.password_entry.get()
        
        if not password:
            self._show_error("Введите пароль папки")
            return
        
        self.result = (password, self.use_recovery.get())
        self.destroy()
    
    def _show_recovery(self):
        """Показать диалог восстановления"""
        from recovery_manager import FolderRecoveryDialog
        
        recovery_dialog = FolderRecoveryDialog(self, self.recovery_manager, self.folder_data)
        self.wait_window(recovery_dialog)
        
        if recovery_dialog.result:
            self.result = (recovery_dialog.result, True)
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