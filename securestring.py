# securestring.py
import os
import sys
import ctypes
import secrets
import threading
from typing import Union

class SecureString:
    """
    Безопасное хранение строк и байтов в памяти с автоматическим затиранием
    """
    
    def __init__(self, data: Union[str, bytes, bytearray]):
        self._lock = threading.RLock()
        self._length = 0
        self._data_buffer = None
        
        if data is None:
            raise ValueError("Data cannot be None")
        
        try:
            if isinstance(data, str):
                encoded_data = data.encode('utf-8')
                self._length = len(encoded_data)
                self._data_buffer = ctypes.create_string_buffer(encoded_data)
            elif isinstance(data, (bytes, bytearray)):
                self._length = len(data)
                self._data_buffer = ctypes.create_string_buffer(bytes(data))
            else:
                raise TypeError("Data must be str, bytes or bytearray")
        except Exception as e:
            # В случае ошибки немедленно затираем любые частичные данные
            self.secure_clear()
            raise e
    
    def retrieve(self) -> bytes:
        """Временное получение данных как bytes"""
        with self._lock:
            if self._data_buffer is None:
                raise ValueError("Data has been cleared")
            return self._data_buffer.raw[:self._length]
    
    def retrieve_string(self) -> str:
        """Временное получение данных как строки"""
        with self._lock:
            if self._data_buffer is None:
                raise ValueError("Data has been cleared")
            return self._data_buffer.raw[:self._length].decode('utf-8', errors='replace')
    
    def secure_clear(self):
        """Безопасное затирание данных из памяти"""
        with self._lock:
            if self._data_buffer is not None:
                # Многократная перезапись случайными данными
                for _ in range(3):
                    try:
                        random_data = secrets.token_bytes(self._length)
                        ctypes.memmove(self._data_buffer, random_data, self._length)
                    except (ValueError, TypeError, BufferError):
                        break
                
                # Финальное обнуление
                try:
                    ctypes.memset(self._data_buffer, 0, self._length)
                except (ValueError, TypeError, BufferError):
                    pass
                
                self._length = 0
                self._data_buffer = None
    
    def __del__(self):
        """Автоматическое затирание при уничтожении объекта"""
        self.secure_clear()
    
    def __len__(self):
        """Длина данных"""
        return self._length
    
    def __repr__(self):
        """Безопасное представление (не показывает данные)"""
        return f"SecureString(length={self._length}, cleared={self._data_buffer is None})"
    
    def __bool__(self):
        """Проверка наличия данных"""
        return self._data_buffer is not None and self._length > 0


class SecureTempFile:
    """
    Безопасная работа с временными файлами
    """
    
    def __init__(self, suffix='.tmp', prefix='secure_', directory=None):
        self.path = None
        self._suffix = suffix
        self._prefix = prefix
        self._directory = directory
        
        # Создаем файл сразу
        self._create_secure_file()
    
    def _create_secure_file(self):
        """Создание безопасного временного файла"""
        import tempfile
        
        if self._directory:
            os.makedirs(self._directory, exist_ok=True)
        
        fd, self.path = tempfile.mkstemp(
            suffix=self._suffix,
            prefix=self._prefix,
            dir=self._directory
        )
        
        # Закрываем дескриптор, файл будет переоткрываться по необходимости
        os.close(fd)
    
    def write_secure(self, data):
        """Безопасная запись данных с немедленной синхронизацией"""
        if not self.path:
            raise ValueError("File has been securely deleted")
        
        try:
            with open(self.path, 'wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            self.secure_delete()
            raise e
    
    def read_secure(self):
        """Безопасное чтение данных"""
        if not self.path:
            raise ValueError("File has been securely deleted")
        
        try:
            with open(self.path, 'rb') as f:
                return f.read()
        except Exception as e:
            raise e
    
    def secure_delete(self):
        """Безопасное удаление файла с перезаписью"""
        if self.path and os.path.exists(self.path):
            try:
                # Получаем размер файла
                file_size = os.path.getsize(self.path)
                
                # Многократная перезапись случайными данными
                for _ in range(3):
                    try:
                        with open(self.path, 'wb') as f:
                            f.write(secrets.token_bytes(file_size))
                            f.flush()
                            os.fsync(f.fileno())
                    except (OSError, IOError):
                        break
                
                # Финальное удаление
                os.unlink(self.path)
                
            except Exception as e:
                # В крайнем случае пытаемся просто удалить
                try:
                    os.unlink(self.path)
                except:
                    pass
            finally:
                self.path = None
    
    def __del__(self):
        """Автоматическое безопасное удаление при уничтожении"""
        self.secure_delete()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.secure_delete()