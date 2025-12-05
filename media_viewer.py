import tkinter as tk
from tkinter import ttk
import customtkinter as ctk
import os
import tempfile
import threading
import logging
from queue import Queue
from PIL import Image, ImageTk, ImageOps

class MediaViewer(ctk.CTkToplevel):
    def __init__(self, parent, file_path, file_type):
        super().__init__(parent)
        self.file_path = file_path
        self.file_type = file_type
        
        # Оптимизации для больших изображений
        self._image_queue = Queue(maxsize=2)
        self._current_scale = 1.0
        self._min_scale = 0.1
        self._max_scale = 5.0
        self._scale_step = 0.1
        
        self._setup_optimized_viewer()
        self._load_media_async()
    
    def _setup_optimized_viewer(self):
        """Оптимизированная настройка просмотрщика"""
        self.title(f"Media Vault - {os.path.basename(self.file_path)}")
        self.geometry("1000x700")
        
        # Используем double buffering для плавности
        self.configure(bg='#2b2b2b')
        
        # Главный контейнер
        self.main_container = ctk.CTkFrame(self)
        self.main_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Панель инструментов
        self._create_toolbar()
        
        # Область просмотра с lazy loading
        self._create_viewer_area()
    
    def _create_toolbar(self):
        """Создание панели инструментов"""
        toolbar = ctk.CTkFrame(self.main_container)
        toolbar.pack(fill=tk.X, padx=5, pady=5)
        
        ctk.CTkButton(toolbar, text="Закрыть", 
                     command=self.destroy).pack(side=tk.RIGHT, padx=5)
    
    def _create_viewer_area(self):
        """Создание области просмотра"""
        self.viewer_frame = ctk.CTkFrame(self.main_container)
        self.viewer_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Индикатор загрузки
        self.loading_label = ctk.CTkLabel(
            self.viewer_frame, 
            text="Загрузка...", 
            font=ctk.CTkFont(size=16)
        )
        self.loading_label.pack(expand=True)
    
    def _load_media_async(self):
        """Асинхронная загрузка медиа"""
        def load_task():
            try:
                start_time = threading.current_thread().ident
                
                if self.file_type == 'image':
                    # Загружаем изображение в отдельном потоке
                    image = Image.open(self.file_path)
                    
                    # Создаем preview для быстрого отображения
                    preview_size = (800, 600)
                    preview_image = ImageOps.contain(image, preview_size)
                    
                    # Отправляем в основной поток
                    self.after(0, lambda: self._display_image_preview(preview_image, image))
                    
                elif self.file_type == 'text':
                    # Для текста загружаем сразу
                    with open(self.file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    self.after(0, lambda: self._display_text_content(content))
                    
                else:
                    self.after(0, self._show_unsupported)
                    
            except Exception as e:
                logging.error(f"Ошибка загрузки медиа: {e}")
                self.after(0, lambda: self._show_error(f"Ошибка загрузки: {e}"))
        
        threading.Thread(target=load_task, daemon=True).start()
    
    def _display_image_preview(self, preview_image, full_image):
        """Быстрое отображение preview изображения"""
        # Убираем индикатор загрузки
        self.loading_label.destroy()
        
        self.current_image = full_image
        self.preview_image = preview_image
        
        # Создаем холст для изображения с скроллбаром
        self._create_image_canvas()
        
        # Отображаем preview
        self._display_current_image()
        
        # Загружаем полноразмерное изображение в фоне
        self._load_full_image_async()
    
    def _create_image_canvas(self):
        """Создание холста для изображения"""
        # Фрейм для холста и скроллбаров
        canvas_frame = ctk.CTkFrame(self.viewer_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        
        # Холст для изображения
        self.canvas = tk.Canvas(canvas_frame, bg='#2b2b2b', highlightthickness=0)
        
        # Скроллбары
        v_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        h_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        
        self.canvas.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        
        # Размещаем элементы
        self.canvas.grid(row=0, column=0, sticky='nsew')
        v_scrollbar.grid(row=0, column=1, sticky='ns')
        h_scrollbar.grid(row=1, column=0, sticky='ew')
        
        canvas_frame.grid_rowconfigure(0, weight=1)
        canvas_frame.grid_columnconfigure(0, weight=1)
        
        # Привязываем события мыши для масштабирования
        self.canvas.bind('<MouseWheel>', self._on_mousewheel)
        self.canvas.bind('<Button-4>', self._on_mousewheel)  # Linux
        self.canvas.bind('<Button-5>', self._on_mousewheel)  # Linux
    
    def _display_current_image(self):
        """Отображение текущего изображения"""
        if not hasattr(self, 'canvas') or not self.current_image:
            return
        
        # Очищаем холст
        self.canvas.delete("all")
        
        # Получаем размеры холста
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        
        if canvas_width <= 1 or canvas_height <= 1:
            self.after(100, self._display_current_image)
            return
        
        # Масштабируем изображение
        img = self.current_image
        if self._current_scale != 1.0:
            new_width = int(img.width * self._current_scale)
            new_height = int(img.height * self._current_scale)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Создаем PhotoImage
        self.photo_image = ImageTk.PhotoImage(img)
        
        # Отображаем изображение
        self.canvas.create_image(
            canvas_width // 2, 
            canvas_height // 2, 
            image=self.photo_image, 
            anchor=tk.CENTER
        )
        
        # Обновляем область прокрутки
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
    
    def _on_mousewheel(self, event):
        """Обработчик колесика мыши для масштабирования"""
        if event.delta > 0 or event.num == 4:
            # Увеличиваем масштаб
            self._current_scale = min(self._max_scale, self._current_scale + self._scale_step)
        else:
            # Уменьшаем масштаб
            self._current_scale = max(self._min_scale, self._current_scale - self._scale_step)
        
        self._display_current_image()
    
    def _load_full_image_async(self):
        """Асинхронная загрузка полноразмерного изображения"""
        # В этой реализации изображение уже загружено
        # В реальной реализации здесь может быть дополнительная обработка
        pass
    
    def _display_text_content(self, content):
        """Отображение текстового содержимого"""
        # Убираем индикатор загрузки
        self.loading_label.destroy()
        
        text_frame = ctk.CTkFrame(self.viewer_frame)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Добавляем скроллбар
        text_scroll = ctk.CTkScrollbar(text_frame)
        text_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.text_widget = tk.Text(
            text_frame, 
            wrap=tk.WORD, 
            yscrollcommand=text_scroll.set,
            font=("Arial", 12),
            bg='#2b2b2b',
            fg='white',
            insertbackground='white',
            padx=10,
            pady=10
        )
        self.text_widget.pack(fill=tk.BOTH, expand=True)
        text_scroll.configure(command=self.text_widget.yview)
        
        self.text_widget.insert(tk.END, content)
        self.text_widget.config(state=tk.DISABLED)
    
    def _show_unsupported(self):
        """Сообщение о неподдерживаемом формате"""
        self.loading_label.destroy()
        ctk.CTkLabel(self.viewer_frame, 
                    text=f"Формат файла не поддерживается встроенным просмотрщиком\n\nИспользуется системное приложение для файлов типа: {self.file_type}",
                    font=ctk.CTkFont(size=14)).pack(expand=True)
    
    def _show_error(self, message):
        """Показать сообщение об ошибке"""
        self.loading_label.destroy()
        ctk.CTkLabel(self.viewer_frame, text=message, 
                    text_color="red", font=ctk.CTkFont(size=12)).pack(expand=True)

class ViewerManager:
    """Менеджер для работы с встроенным просмотрщиком"""
    
    @staticmethod
    def view_file(parent, file_path, file_type):
        """Открыть файл во встроенном просмотрщике"""
        actual_type = ViewerManager._detect_file_type(file_path, file_type)
        
        if actual_type in ['image', 'text']:
            viewer = MediaViewer(parent, file_path, actual_type)
            return viewer
        else:
            # Для остальных типов используем системные приложения
            try:
                os.startfile(file_path)  # Windows
            except AttributeError:
                # Для Linux/Mac
                import subprocess
                try:
                    subprocess.run(['xdg-open', file_path])  # Linux
                except FileNotFoundError:
                    try:
                        subprocess.run(['open', file_path])  # Mac
                    except FileNotFoundError:
                        logging.error("Не удалось открыть файл системным приложением")
            return None
    
    @staticmethod
    def _detect_file_type(file_path, general_type):
        """Точное определение типа файла"""
        ext = os.path.splitext(file_path)[1].lower()
        
        if general_type == 'image':
            return 'image'
        elif general_type == 'document':
            if ext in ['.txt', '.log', '.csv', '.md', '.json', '.xml', '.html', '.htm']:
                return 'text'
            else:
                return 'document'
        else:
            return general_type