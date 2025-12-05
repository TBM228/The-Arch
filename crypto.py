# crypto.py - БЕЗОПАСНОЕ ХРАНЕНИЕ КЛЮЧЕЙ
import os
import base64
import hashlib
import logging
import secrets
import tempfile
import threading
from typing import Optional, Callable
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend

# Импортируем нашу безопасную реализацию
from securestring import SecureString, SecureTempFile


class SecureKeyContainer:
    """Безопасный контейнер для хранения ключей в памяти"""
    
    def __init__(self, key_data):
        self._lock = threading.RLock()
        self._secure_key = None
        self._key_usage_count = 0
        self._max_usage_before_rekey = 100
        self._last_used = None
        self._load_key(key_data)
    
    def _load_key(self, key_data):
        """Загрузка ключа в защищенный контейнер"""
        with self._lock:
            if self._secure_key:
                self._secure_key.secure_clear()
            
            # Используем SecureString для хранения
            self._secure_key = SecureString(key_data)
            self._key_usage_count = 0
            self._last_used = None
    
    def retrieve(self) -> bytes:
        """Временное получение ключа с отслеживанием использования"""
        with self._lock:
            if not self._secure_key:
                raise ValueError("Ключ не загружен или был очищен")
            
            # Увеличиваем счетчик использования
            self._key_usage_count += 1
            self._last_used = threading.get_ident()
            
            # Возвращаем данные
            return self._secure_key.retrieve()
    
    def needs_rekeying(self) -> bool:
        """Проверка необходимости ротации ключа"""
        with self._lock:
            return self._key_usage_count >= self._max_usage_before_rekey
    
    def secure_clear(self):
        """Безопасная очистка ключа из памяти"""
        with self._lock:
            if self._secure_key:
                self._secure_key.secure_clear()
                self._secure_key = None
            self._key_usage_count = 0
            self._last_used = None
    
    def __del__(self):
        """Автоматическая очистка при удалении"""
        self.secure_clear()


class SecureCryptoManager:
    def __init__(self, master_key):
        # Безопасный контейнер для мастер-ключа
        self._master_key_container = SecureKeyContainer(master_key)
        self._active_keys = {}  # {key_id: SecureKeyContainer}
        self._chunk_size = 64 * 1024
        self._kdf_iterations = 300000
        self._key_lock = threading.RLock()
        
        # Очистка мастер-ключа из входных данных
        if isinstance(master_key, (bytes, bytearray)):
            self._secure_erase(master_key)
    
    def __del__(self):
        """Гарантируем очистку при удалении"""
        self.secure_clear()
    
    def _secure_erase(self, data):
        """Безопасное затирание данных в памяти"""
        if isinstance(data, (bytes, bytearray)):
            mutable = bytearray(data)
            for i in range(len(mutable)):
                mutable[i] = secrets.randbits(8)
        elif isinstance(data, str):
            # Для строк используем SecureString
            secure_str = SecureString(data)
            secure_str.secure_clear()
    
    def secure_clear(self):
        """Безопасная очистка всех ключей из памяти"""
        if hasattr(self, '_master_key_container'):
            self._master_key_container.secure_clear()
        
        with self._key_lock:
            for key_container in self._active_keys.values():
                key_container.secure_clear()
            self._active_keys.clear()
    
    def _get_master_key(self) -> bytes:
        """Получение мастер-ключа с ротацией при необходимости"""
        if self._master_key_container.needs_rekeying():
            logging.warning("Мастер-ключ использовался слишком много раз, требуется реинициализация")
            raise SecurityError("Требуется повторная аутентификация")
        
        return self._master_key_container.retrieve()
    
    def encrypt_data(self, data, key_id=None):
        """Шифрование данных с безопасной обработкой"""
        encryption_key = None
        encrypted_result = None
        
        try:
            if key_id and key_id in self._active_keys:
                with self._key_lock:
                    encryption_key = self._active_keys[key_id].retrieve()
            else:
                encryption_key = self._get_master_key()
            
            fernet = Fernet(encryption_key)
            encrypted_result = fernet.encrypt(data)
            return encrypted_result
            
        finally:
            # Очищаем временные ключи из памяти
            if encryption_key and not key_id:
                self._secure_erase(encryption_key)
    
    def decrypt_data(self, encrypted_data, key_id=None):
        """Дешифрование данных с безопасной обработкой"""
        decryption_key = None
        decrypted_result = None
        
        try:
            if key_id and key_id in self._active_keys:
                with self._key_lock:
                    decryption_key = self._active_keys[key_id].retrieve()
            else:
                decryption_key = self._get_master_key()
            
            fernet = Fernet(decryption_key)
            decrypted_result = fernet.decrypt(encrypted_data)
            return decrypted_result
            
        finally:
            # Очищаем временные ключи из памяти
            if decryption_key and not key_id:
                self._secure_erase(decryption_key)
    
    def encrypt_file(self, file_path, folder_key=None, progress_callback: Optional[Callable] = None):
        """Безопасное шифрование файла"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Файл не найден: {file_path}")
        
        file_size = os.path.getsize(file_path)
        
        if file_size > 10 * 1024 * 1024:
            return self.encrypt_large_file(file_path, folder_key, progress_callback)
        
        file_key = Fernet.generate_key()
        file_fernet = Fernet(file_key)
        
        try:
            with open(file_path, 'rb') as f:
                file_data = f.read()
            
            encrypted_data = file_fernet.encrypt(file_data)
            
            # Шифруем ключ файла
            if folder_key:
                folder_fernet = Fernet(folder_key)
                encrypted_file_key = folder_fernet.encrypt(file_key)
            else:
                encrypted_file_key = self.encrypt_data(file_key)
            
            # Создаем безопасное имя файла
            file_id = secrets.token_hex(16)
            vault_filename = f"data/encrypted_files/{file_id}.myarc"
            
            # Создаем директорию если нужно
            os.makedirs(os.path.dirname(vault_filename), exist_ok=True)
            
            # Используем безопасный временный файл
            with SecureTempFile(prefix='enc_', suffix='.myarc', 
                              directory=os.path.dirname(vault_filename)) as temp_file:
                temp_file.write_secure(
                    len(encrypted_file_key).to_bytes(4, 'big') + 
                    encrypted_file_key + 
                    encrypted_data
                )
                
                # Атомарная замена с блокировкой
                import time
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        if os.path.exists(vault_filename):
                            os.replace(temp_file.path, vault_filename)
                        else:
                            os.rename(temp_file.path, vault_filename)
                        temp_file.path = None  # Предотвращаем удаление
                        break
                    except PermissionError:
                        if attempt == max_retries - 1:
                            raise
                        time.sleep(0.1 * (attempt + 1))
            
            if progress_callback:
                progress_callback(100)
            
            return vault_filename, file_id
            
        except Exception as e:
            # Безопасная очистка при ошибке
            if 'vault_filename' in locals() and os.path.exists(vault_filename):
                self._secure_delete_file(vault_filename)
            raise e
        finally:
            # Затирание временных данных
            self._secure_erase(file_key)
            if 'file_data' in locals():
                self._secure_erase(file_data)
    
    def encrypt_large_file(self, file_path, folder_key=None, progress_callback: Optional[Callable] = None):
        """Безопасное шифрование больших файлов"""
        file_key = Fernet.generate_key()
        file_fernet = Fernet(file_key)
        
        file_id = secrets.token_hex(16)
        vault_filename = f"data/encrypted_files/{file_id}.myarc"
        
        try:
            # Шифруем ключ файла
            if folder_key:
                folder_fernet = Fernet(folder_key)
                encrypted_file_key = folder_fernet.encrypt(file_key)
            else:
                encrypted_file_key = self.encrypt_data(file_key)
            
            total_size = os.path.getsize(file_path)
            processed = 0
            
            # Создаем директорию если нужно
            os.makedirs(os.path.dirname(vault_filename), exist_ok=True)
            
            with SecureTempFile(prefix='enc_large_', suffix='.myarc',
                              directory=os.path.dirname(vault_filename)) as temp_file:
                
                # Записываем заголовок с ключом
                header = len(encrypted_file_key).to_bytes(4, 'big') + encrypted_file_key
                temp_file.write_secure(header)
                
                # Шифруем файл по частям
                with open(file_path, 'rb') as infile:
                    with open(temp_file.path, 'ab') as outfile:
                        while True:
                            chunk = infile.read(self._chunk_size)
                            if not chunk:
                                break
                            
                            encrypted_chunk = file_fernet.encrypt(chunk)
                            outfile.write(encrypted_chunk)
                            
                            processed += len(chunk)
                            if progress_callback:
                                progress = (processed / total_size) * 100
                                progress_callback(progress)
                
                # Атомарная замена
                if os.path.exists(vault_filename):
                    os.replace(temp_file.path, vault_filename)
                else:
                    os.rename(temp_file.path, vault_filename)
                temp_file.path = None  # Предотвращаем удаление
                        
        except Exception as e:
            if os.path.exists(vault_filename):
                self._secure_delete_file(vault_filename)
            raise e
        finally:
            self._secure_erase(file_key)
        
        return vault_filename, file_id
    
    def _secure_delete_file(self, file_path):
        """Безопасное удаление файла с перезаписью"""
        try:
            if os.path.exists(file_path):
                file_size = os.path.getsize(file_path)
                # Трехкратная перезапись случайными данными
                for _ in range(3):
                    with open(file_path, 'wb') as f:
                        f.write(secrets.token_bytes(file_size))
                        f.flush()
                        os.fsync(f.fileno())
                os.remove(file_path)
        except Exception as e:
            logging.warning(f"Не удалось безопасно удалить файл {file_path}: {e}")
            try:
                os.remove(file_path)
            except:
                pass
    
    def decrypt_file(self, vault_file_path, output_path, folder_key=None, progress_callback: Optional[Callable] = None):
        """Безопасное дешифрование файла"""
        if not os.path.exists(vault_file_path):
            raise FileNotFoundError(f"Зашифрованный файл не найден: {vault_file_path}")
        
        file_size = os.path.getsize(vault_file_path)
        
        if file_size > 10 * 1024 * 1024:
            return self.decrypt_large_file(vault_file_path, output_path, folder_key, progress_callback)
        
        try:
            with open(vault_file_path, 'rb') as f:
                key_length = int.from_bytes(f.read(4), 'big')
                encrypted_file_key = f.read(key_length)
                encrypted_data = f.read()
            
            # Дешифруем ключ файла
            if folder_key:
                folder_fernet = Fernet(folder_key)
                file_key = folder_fernet.decrypt(encrypted_file_key)
            else:
                file_key = self.decrypt_data(encrypted_file_key)
            
            file_fernet = Fernet(file_key)
            decrypted_data = file_fernet.decrypt(encrypted_data)
            
            # Безопасная запись во временный файл
            with SecureTempFile(prefix='dec_', suffix='.tmp', 
                              directory=os.path.dirname(output_path)) as temp_file:
                temp_file.write_secure(decrypted_data)
                
                # Атомарная замена с блокировкой
                import time
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        os.replace(temp_file.path, output_path)
                        temp_file.path = None
                        break
                    except PermissionError:
                        if attempt == max_retries - 1:
                            raise
                        time.sleep(0.1 * (attempt + 1))
                
            if progress_callback:
                progress_callback(100)
                
        except Exception as e:
            # Безопасная очистка при ошибке
            if os.path.exists(output_path):
                self._secure_delete_file(output_path)
            raise e
        finally:
            # Затирание временных данных
            if 'file_key' in locals():
                self._secure_erase(file_key)
            if 'decrypted_data' in locals():
                self._secure_erase(decrypted_data)
    
    def decrypt_large_file(self, vault_file_path, output_path, folder_key=None, progress_callback: Optional[Callable] = None):
        """Безопасное дешифрование больших файлов"""
        total_size = os.path.getsize(vault_file_path)
        processed = 0
        
        try:
            with open(vault_file_path, 'rb') as infile:
                # Читаем зашифрованный ключ
                key_length = int.from_bytes(infile.read(4), 'big')
                encrypted_file_key = infile.read(key_length)
                processed += 4 + key_length
                
                # Дешифруем ключ файла
                if folder_key:
                    folder_fernet = Fernet(folder_key)
                    file_key = folder_fernet.decrypt(encrypted_file_key)
                else:
                    file_key = self.decrypt_data(encrypted_file_key)
                
                file_fernet = Fernet(file_key)
                
                # Безопасный временный файл для вывода
                with SecureTempFile(prefix='dec_large_', suffix='.tmp',
                                  directory=os.path.dirname(output_path)) as temp_file:
                    
                    with open(temp_file.path, 'wb') as outfile:
                        while True:
                            chunk = infile.read(self._chunk_size + 100)
                            if not chunk:
                                break
                            
                            try:
                                decrypted_chunk = file_fernet.decrypt(chunk)
                                outfile.write(decrypted_chunk)
                            except Exception as e:
                                raise ValueError(f"Ошибка дешифрования: {e}")
                            
                            processed += len(chunk)
                            if progress_callback:
                                progress = (processed / total_size) * 100
                                progress_callback(progress)
                    
                    # Атомарная замена
                    os.replace(temp_file.path, output_path)
                    temp_file.path = None
                            
        except Exception as e:
            if os.path.exists(output_path):
                self._secure_delete_file(output_path)
            raise e
        finally:
            if 'file_key' in locals():
                self._secure_erase(file_key)
    
    def generate_key_from_password(self, password, salt=None):
        """Генерация ключа из пароля с защитой"""
        if salt is None:
            salt = secrets.token_bytes(32)
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=self._kdf_iterations,
            backend=default_backend()
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return key, salt
    
    def encrypt_with_master_key(self, data):
        """Шифрование данных мастер-ключом"""
        return self.encrypt_data(data)
    
    def decrypt_with_master_key(self, encrypted_data):
        """Дешифрование данных мастер-ключом"""
        return self.decrypt_data(encrypted_data)
    
    def calculate_file_hash(self, file_path, algorithm='sha256'):
        """Вычисление хэша файла"""
        hash_func = getattr(hashlib, algorithm)()
        
        try:
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    hash_func.update(chunk)
            
            return hash_func.hexdigest()
        except Exception as e:
            logging.error(f"Ошибка вычисления хэша файла {file_path}: {e}")
            return None
    
    def register_key(self, key_id, key_data):
        """Регистрация ключа в безопасном контейнере"""
        with self._key_lock:
            if key_id in self._active_keys:
                self._active_keys[key_id].secure_clear()
            self._active_keys[key_id] = SecureKeyContainer(key_data)
    
    def unregister_key(self, key_id):
        """Удаление ключа с безопасной очисткой"""
        with self._key_lock:
            if key_id in self._active_keys:
                self._active_keys[key_id].secure_clear()
                del self._active_keys[key_id]


class SecurityError(Exception):
    """Ошибка безопасности"""
    pass


# Сохраняем обратную совместимость
CryptoManager = SecureCryptoManager