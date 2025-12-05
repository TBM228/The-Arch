# vault_core.py - ТРАНЗАКЦИОННАЯ МОДЕЛЬ
import os
import json
import base64
import shutil
import logging
import threading
import tempfile
import secrets
import time
import hashlib
from datetime import datetime
from collections import OrderedDict
from functools import lru_cache
from threading import RLock
from queue import Queue


class VaultTransaction:
    """Транзакция для атомарных операций"""
    
    def __init__(self, vault_core, description=""):
        self.vault = vault_core
        self.description = description
        self.operations = []
        self._state = 'initialized'
        self._lock = threading.RLock()
        self._backup_files = []
        self._rollback_data = {}
    
    def add_file(self, file_path, folder_id='root', progress_callback=None):
        """Добавление файла в транзакцию"""
        with self._lock:
            if self._state != 'initialized':
                raise RuntimeError("Транзакция уже выполнена")
            
            operation_id = f"add_file_{secrets.token_hex(8)}"
            self.operations.append({
                'id': operation_id,
                'type': 'add_file',
                'file_path': file_path,
                'folder_id': folder_id,
                'progress_callback': progress_callback
            })
            return operation_id
    
    def create_folder(self, name, parent_id='root', password=None, hint=None, recovery_password=None):
        """Создание папки в транзакции"""
        with self._lock:
            if self._state != 'initialized':
                raise RuntimeError("Транзакция уже выполнена")
            
            operation_id = f"create_folder_{secrets.token_hex(8)}"
            self.operations.append({
                'id': operation_id,
                'type': 'create_folder',
                'name': name,
                'parent_id': parent_id,
                'password': password,
                'hint': hint,
                'recovery_password': recovery_password
            })
            return operation_id
    
    def delete_file(self, file_id):
        """Удаление файла в транзакции"""
        with self._lock:
            if self._state != 'initialized':
                raise RuntimeError("Транзакция уже выполнена")
            
            operation_id = f"delete_file_{secrets.token_hex(8)}"
            self.operations.append({
                'id': operation_id,
                'type': 'delete_file',
                'file_id': file_id
            })
            return operation_id
    
    def commit(self):
        """Выполнение транзакции"""
        with self._lock:
            if self._state != 'initialized':
                raise RuntimeError(f"Транзакция в состоянии {self._state}")
            
            self._state = 'executing'
            results = {}
            
            try:
                # Создаем резервную копию файловой системы
                self._create_backup()
                
                # Выполняем операции
                for op in self.operations:
                    try:
                        result = self._execute_operation(op)
                        results[op['id']] = result
                    except Exception as e:
                        logging.error(f"Ошибка в операции {op['id']}: {e}")
                        self._state = 'rolling_back'
                        self._rollback()
                        self._state = 'failed'
                        raise TransactionError(f"Транзакция прервана: {e}")
                
                self._state = 'committed'
                logging.info(f"Транзакция '{self.description}' успешно выполнена")
                return results
                
            except Exception as e:
                self._state = 'failed'
                raise
    
    def _execute_operation(self, operation):
        """Выполнение отдельной операции"""
        op_type = operation['type']
        
        if op_type == 'add_file':
            return self.vault._transactional_add_file(
                operation['file_path'],
                operation['folder_id'],
                operation['progress_callback']
            )
        elif op_type == 'create_folder':
            return self.vault._transactional_create_folder(
                operation['name'],
                operation['parent_id'],
                operation['password'],
                operation['hint'],
                operation['recovery_password']
            )
        elif op_type == 'delete_file':
            return self.vault._transactional_delete_file(operation['file_id'])
        else:
            raise ValueError(f"Неизвестный тип операции: {op_type}")
    
    def _create_backup(self):
        """Создание резервной копии для отката"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            backup_name = f"transaction_backup_{timestamp}_{secrets.token_hex(4)}.json.enc"
            backup_path = os.path.join('data/backups', backup_name)
            
            os.makedirs('data/backups', exist_ok=True)
            
            # Шифруем резервную копию
            data = json.dumps(self.vault.filesystem, ensure_ascii=False).encode()
            encrypted_data = self.vault.crypto.encrypt_with_master_key(data)
            
            with open(backup_path, 'wb') as f:
                f.write(encrypted_data)
            
            self._backup_files.append(backup_path)
            logging.debug(f"Создана резервная копия: {backup_path}")
            
        except Exception as e:
            logging.error(f"Ошибка создания резервной копии: {e}")
            raise
    
    def _rollback(self):
        """Откат транзакции"""
        logging.warning(f"Откат транзакции '{self.description}'")
        
        try:
            # Восстанавливаем из последней резервной копии
            if self._backup_files:
                latest_backup = self._backup_files[-1]
                self.vault._restore_from_backup(latest_backup)
            
            # Очищаем резервные копии
            for backup in self._backup_files:
                try:
                    os.remove(backup)
                except:
                    pass
            
        except Exception as e:
            logging.error(f"Ошибка при откате транзакции: {e}")
    
    def __enter__(self):
        """Контекстный менеджер"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Автоматический коммит или откат"""
        if exc_type is None:
            self.commit()
        else:
            if self._state == 'executing':
                try:
                    self._rollback()
                except Exception as e:
                    logging.error(f"Ошибка при автоматическом откате: {e}")
            self._state = 'failed'


class TransactionError(Exception):
    """Ошибка транзакции"""
    pass


class SecureVaultCore:
    def __init__(self, auth_manager, crypto_manager, folder_security_manager):
        self.auth = auth_manager
        self.crypto = crypto_manager
        self.folder_security_manager = folder_security_manager
        self.filesystem_path = 'data/filesystem.json.enc'
        self.filesystem = {}
        self.current_folder_id = 'root'
        
        # Кэш для часто используемых данных
        self._folder_cache = OrderedDict()
        self._cache_max_size = 100
        
        # Улучшенная блокировка
        self._filesystem_lock = RLock()
        self._transaction_lock = threading.Lock()
        self._file_locks = {}  # file_id -> lock
        self._folder_locks = {}  # folder_id -> lock
        
        # Очередь операций
        self._operation_queue = Queue()
        self._operation_worker = threading.Thread(
            target=self._process_operations,
            daemon=True
        )
        self._operation_worker.start()
        
        self._load_filesystem()
    
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
                    result_queue.put(('error', e))
                finally:
                    self._operation_queue.task_done()
                    
            except Exception as e:
                logging.error(f"Ошибка в обработчике операций: {e}")
    
    def _queue_operation(self, func, *args, **kwargs):
        """Добавление операции в очередь"""
        result_queue = Queue()
        self._operation_queue.put((func, args, kwargs, result_queue))
        
        result_type, result = result_queue.get()
        if result_type == 'error':
            raise result
        return result
    
    def _get_file_lock(self, file_id):
        """Получение блокировки для файла"""
        with self._filesystem_lock:
            if file_id not in self._file_locks:
                self._file_locks[file_id] = threading.RLock()
            return self._file_locks[file_id]
    
    def _get_folder_lock(self, folder_id):
        """Получение блокировки для папки"""
        with self._filesystem_lock:
            if folder_id not in self._folder_locks:
                self._folder_locks[folder_id] = threading.RLock()
            return self._folder_locks[folder_id]
    
    def _atomic_file_operation(self, filepath, operation_callback, mode='rb'):
        """Атомарные файловые операции с защитой от race conditions"""
        dirname = os.path.dirname(filepath)
        basename = os.path.basename(filepath)
        
        # Создаем временный файл в той же директории
        fd, temp_path = tempfile.mkstemp(prefix=f".{basename}.tmp", dir=dirname)
        
        try:
            with os.fdopen(fd, 'wb' if 'b' in mode else 'w') as temp_file:
                result = operation_callback(temp_file)
            
            # Многократные попытки атомарной замены
            max_attempts = 5
            for attempt in range(max_attempts):
                try:
                    os.replace(temp_path, filepath)
                    break
                except PermissionError:
                    if attempt == max_attempts - 1:
                        raise
                    time.sleep(0.1 * (attempt + 1))
            
            return result
            
        except Exception:
            # Очистка при ошибке
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise
        finally:
            # Гарантируем удаление временного файла
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
    
    def _save_filesystem(self):
        """Безопасное сохранение файловой системы с контрольной суммой"""
        with self._filesystem_lock:
            try:
                def write_operation(temp_file):
                    # Добавляем контрольную сумму
                    data = json.dumps(self.filesystem, ensure_ascii=False).encode()
                    checksum = hashlib.sha256(data).digest()
                    
                    # Сохраняем с контрольной суммой
                    payload = {
                        'data': base64.b64encode(data).decode(),
                        'checksum': base64.b64encode(checksum).decode(),
                        'timestamp': datetime.now().isoformat(),
                        'version': '2.0'
                    }
                    
                    payload_data = json.dumps(payload, ensure_ascii=False).encode()
                    encrypted_data = self.crypto.encrypt_with_master_key(payload_data)
                    temp_file.write(encrypted_data)
                
                os.makedirs(os.path.dirname(self.filesystem_path), exist_ok=True)
                self._atomic_file_operation(self.filesystem_path, write_operation, 'wb')
                
                # Создаем резервную копию
                self._create_filesystem_backup()
                
                # Очищаем кэш после сохранения
                self._folder_cache.clear()
                if hasattr(self, 'get_folder_contents_cached'):
                    self.get_folder_contents_cached.cache_clear()
                    
            except Exception as e:
                logging.error(f"Ошибка сохранения файловой системы: {e}")
                raise e
    
    def _create_filesystem_backup(self):
        """Создание резервной копии файловой системы"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"filesystem_backup_{timestamp}.json.enc"
            backup_path = os.path.join('data/backups', backup_name)
            
            os.makedirs('data/backups', exist_ok=True)
            
            # Копируем файл
            if os.path.exists(self.filesystem_path):
                shutil.copy2(self.filesystem_path, backup_path)
                logging.debug(f"Создана резервная копия файловой системы: {backup_path}")
            
            # Очищаем старые бэкапы (оставляем последние 10)
            backups = []
            for f in os.listdir('data/backups'):
                if f.startswith('filesystem_backup_'):
                    full_path = os.path.join('data/backups', f)
                    backups.append((os.path.getmtime(full_path), full_path))
            
            backups.sort(reverse=True)
            for _, backup in backups[10:]:
                try:
                    os.remove(backup)
                except:
                    pass
                    
        except Exception as e:
            logging.error(f"Ошибка создания резервной копии: {e}")
    
    def _restore_from_backup(self, backup_path):
        """Восстановление из резервной копии"""
        try:
            if not os.path.exists(backup_path):
                raise FileNotFoundError(f"Резервная копия не найдена: {backup_path}")
            
            # Читаем зашифрованные данные
            with open(backup_path, 'rb') as f:
                encrypted_data = f.read()
            
            # Дешифруем
            decrypted_data = self.crypto.decrypt_with_master_key(encrypted_data)
            payload = json.loads(decrypted_data.decode())
            
            # Проверяем контрольную сумму
            data = base64.b64decode(payload['data'])
            expected_checksum = base64.b64decode(payload['checksum'])
            actual_checksum = hashlib.sha256(data).digest()
            
            if actual_checksum != expected_checksum:
                raise ValueError("Контрольная сумма не совпадает, данные повреждены")
            
            # Восстанавливаем файловую систему
            self.filesystem = json.loads(data.decode())
            self._save_filesystem()
            
            logging.info(f"Файловая система восстановлена из {backup_path}")
            
        except Exception as e:
            logging.error(f"Ошибка восстановления из резервной копии: {e}")
            raise
    
    def _load_filesystem(self):
        """Безопасная загрузка файловой системы с проверкой целостности"""
        if not os.path.exists(self.filesystem_path):
            self._create_default_filesystem()
            return
        
        try:
            file_size = os.path.getsize(self.filesystem_path)
            if file_size == 0:
                logging.warning("Файл файловой системы пуст")
                self._create_default_filesystem()
                return
            
            def read_operation(temp_file):
                encrypted_data = temp_file.read()
                if len(encrypted_data) == 0:
                    raise ValueError("Файл пуст")
                return encrypted_data
            
            encrypted_data = self._atomic_file_operation(self.filesystem_path, read_operation, 'rb')
            decrypted_data = self.crypto.decrypt_with_master_key(encrypted_data)
            
            try:
                payload = json.loads(decrypted_data.decode())
                
                # Проверяем версию формата
                if payload.get('version') != '2.0':
                    raise ValueError("Несовместимая версия файловой системы")
                
                # Проверяем контрольную сумму
                data = base64.b64decode(payload['data'])
                expected_checksum = base64.b64decode(payload['checksum'])
                actual_checksum = hashlib.sha256(data).digest()
                
                if actual_checksum != expected_checksum:
                    raise ValueError("Контрольная сумма не совпадает")
                
                self.filesystem = json.loads(data.decode())
                
            except json.JSONDecodeError:
                # Старый формат (без контрольной суммы)
                self.filesystem = json.loads(decrypted_data.decode())
            
            self._validate_filesystem_integrity()
            self._optimize_filesystem_structure()
            
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logging.error(f"Ошибка загрузки файловой системы: {e}")
            self._backup_corrupted_filesystem()
            
            # Пробуем восстановить из последнего бэкапа
            try:
                backups = []
                for f in os.listdir('data/backups'):
                    if f.startswith('filesystem_backup_'):
                        full_path = os.path.join('data/backups', f)
                        backups.append((os.path.getmtime(full_path), full_path))
                
                if backups:
                    backups.sort(reverse=True)
                    latest_backup = backups[0][1]
                    self._restore_from_backup(latest_backup)
                else:
                    self._create_default_filesystem()
            except:
                self._create_default_filesystem()
        except Exception as e:
            logging.error(f"Критическая ошибка загрузки файловой системы: {e}")
            self._create_default_filesystem()
    
    def begin_transaction(self, description=""):
        """Начало новой транзакции"""
        return VaultTransaction(self, description)
    
    def _transactional_add_file(self, file_path, folder_id='root', progress_callback=None):
        """Добавление файла в рамках транзакции"""
        with self._get_folder_lock(folder_id):
            if folder_id != 'root' and not self.folder_security_manager.is_folder_unlocked(folder_id):
                raise PermissionError("Папка должна быть разблокирована для добавления файлов")
            
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"Файл не найден: {file_path}")
            
            folder_key = None
            if folder_id != 'root':
                folder_key = self.folder_security_manager.get_folder_key(folder_id)
            
            try:
                file_size = os.path.getsize(file_path)
                if file_size > 10 * 1024 * 1024:
                    vault_filename, file_id = self.crypto.encrypt_large_file(
                        file_path, folder_key, progress_callback
                    )
                else:
                    vault_filename, file_id = self.crypto.encrypt_file(file_path, folder_key, progress_callback)
                
                # Безопасное добавление записи в файловую систему
                with self._filesystem_lock:
                    self.filesystem.setdefault('files', {})
                    self.filesystem['files'][file_id] = {
                        'id': file_id,
                        'original_name': os.path.basename(file_path),
                        'encrypted_name': base64.b64encode(os.path.basename(file_path).encode()).decode(),
                        'vault_filename': vault_filename,
                        'folder_id': folder_id,
                        'size': file_size,
                        'added_at': self._get_timestamp(),
                        'file_type': self._get_file_type(file_path),
                        'hash': self.crypto.calculate_file_hash(file_path)
                    }
                    
                    if folder_id in self.filesystem.get('folders', {}):
                        self.filesystem['folders'][folder_id]['children'].append(file_id)
                
                return file_id
                
            except Exception as e:
                if 'vault_filename' in locals() and os.path.exists(vault_filename):
                    self.crypto._secure_delete(vault_filename)
                raise e
    
    def add_file(self, file_path, folder_id='root', progress_callback=None):
        """Безопасное добавление файла в хранилище"""
        return self._queue_operation(
            self._transactional_add_file,
            file_path,
            folder_id,
            progress_callback
        )
    
    def extract_file(self, file_id, output_dir):
        """Безопасное извлечение файла"""
        return self._queue_operation(
            self._transactional_extract_file,
            file_id,
            output_dir
        )
    
    def _transactional_extract_file(self, file_id, output_dir):
        """Извлечение файла в рамках транзакции"""
        with self._get_file_lock(file_id):
            if file_id not in self.filesystem.get('files', {}):
                raise FileNotFoundError(f"Файл с ID {file_id} не найден")
            
            file_data = self.filesystem['files'][file_id]
            folder_id = file_data['folder_id']
            
            if folder_id != 'root' and not self.folder_security_manager.is_folder_unlocked(folder_id):
                raise PermissionError("Папка должна быть разблокирована для извлечения файлов")
            
            folder_key = None
            if folder_id != 'root':
                folder_key = self.folder_security_manager.get_folder_key(folder_id)
            
            vault_path = file_data['vault_filename']
            output_path = os.path.join(output_dir, file_data['original_name'])
            
            if not os.path.exists(vault_path):
                raise FileNotFoundError(f"Зашифрованный файл не найден: {vault_path}")
            
            temp_output = self.crypto._create_secure_temp_file()
            
            try:
                self.crypto.decrypt_file(vault_path, temp_output, folder_key)
                
                extracted_hash = self.crypto.calculate_file_hash(temp_output)
                if extracted_hash != file_data['hash']:
                    raise ValueError("Целостность файла нарушена: хэши не совпадают")
                
                os.replace(temp_output, output_path)
                temp_output = None
                
                return output_path
                
            finally:
                if temp_output and os.path.exists(temp_output):
                    self.crypto._secure_delete(temp_output)
    
    def _validate_filesystem_integrity(self):
        """Расширенная проверка целостности файловой системы"""
        required_keys = ['files', 'folders']
        for key in required_keys:
            if key not in self.filesystem:
                self.filesystem[key] = {}
        
        # Проверяем ссылочную целостность
        for file_id, file_data in self.filesystem['files'].items():
            folder_id = file_data.get('folder_id')
            if folder_id and folder_id not in self.filesystem['folders']:
                logging.warning(f"Файл {file_id} ссылается на несуществующую папку {folder_id}")
                file_data['folder_id'] = 'root'
        
        for folder_id, folder_data in self.filesystem['folders'].items():
            for child_id in list(folder_data.get('children', [])):
                if (child_id not in self.filesystem['files'] and 
                    child_id not in self.filesystem['folders']):
                    logging.warning(f"Папка {folder_id} содержит несуществующий элемент {child_id}")
                    folder_data['children'].remove(child_id)
    
    def _create_default_filesystem(self):
        """Создание файловой системы по умолчанию"""
        self.filesystem = {
            'files': {},
            'folders': {
                'root': {
                    'id': 'root',
                    'name': 'Корневая папка',
                    'encrypted_name': base64.b64encode('Корневая папка'.encode()).decode(),
                    'parent': None,
                    'children': [],
                    'created_at': self._get_timestamp(),
                    'is_locked': False
                }
            },
            'version': '2.0',
            'created_at': self._get_timestamp()
        }
        self._save_filesystem()
    
    def _backup_corrupted_filesystem(self):
        """Резервное копирование поврежденной файловой системы"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            corrupted_name = f"corrupted_filesystem_{timestamp}.bak"
            corrupted_path = os.path.join('data/backups', corrupted_name)
            
            os.makedirs('data/backups', exist_ok=True)
            
            if os.path.exists(self.filesystem_path):
                shutil.copy2(self.filesystem_path, corrupted_path)
                logging.warning(f"Поврежденная файловая система сохранена как: {corrupted_path}")
        except Exception as e:
            logging.error(f"Не удалось сохранить поврежденную файловую систему: {e}")
    
    def _get_timestamp(self):
        """Получение текущего времени"""
        return datetime.now().isoformat()
    
    def _get_file_type(self, file_path):
        """Определение типа файла"""
        import mimetypes
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type:
            if mime_type.startswith('image/'):
                return 'image'
            elif mime_type.startswith('video/'):
                return 'video'
            elif mime_type.startswith('audio/'):
                return 'audio'
            elif mime_type in ['application/pdf', 'application/msword', 
                             'application/vnd.openxmlformats-officedocument.wordprocessingml.document']:
                return 'document'
        
        ext = os.path.splitext(file_path)[1].lower()
        if ext in ['.txt', '.log', '.md', '.json', '.xml', '.html', '.htm']:
            return 'text'
        elif ext in ['.zip', '.rar', '.7z', '.tar', '.gz']:
            return 'archive'
        else:
            return 'binary'
    
    def cleanup(self):
        """Очистка ресурсов"""
        # Сигнал остановки обработчику операций
        self._operation_queue.put(None)
        self._operation_worker.join(timeout=5.0)
        
        # Очистка блокировок
        with self._filesystem_lock:
            self._file_locks.clear()
            self._folder_locks.clear()
    
    def verify_integrity(self):
        """Проверка целостности хранилища"""
        issues = []
        
        with self._filesystem_lock:
            # Проверяем файлы
            for file_id, file_data in self.filesystem.get('files', {}).items():
                vault_path = file_data.get('vault_filename')
                if not vault_path or not os.path.exists(vault_path):
                    issues.append(f"Файл {file_id}: зашифрованный файл не найден")
                    continue
                
                # Проверяем хэш
                try:
                    temp_file = self.crypto._create_secure_temp_file()
                    self.crypto.decrypt_file(vault_path, temp_file, None)
                    
                    current_hash = self.crypto.calculate_file_hash(temp_file)
                    if current_hash != file_data.get('hash'):
                        issues.append(f"Файл {file_id}: хэш не совпадает")
                    
                    # Очистка временного файла
                    if os.path.exists(temp_file):
                        self.crypto._secure_delete(temp_file)
                        
                except Exception as e:
                    issues.append(f"Файл {file_id}: ошибка проверки: {e}")
            
            # Проверяем папки
            for folder_id, folder_data in self.filesystem.get('folders', {}).items():
                if folder_id != 'root' and not folder_data.get('parent'):
                    issues.append(f"Папка {folder_id}: отсутствует родительская папка")
        
        return issues

# Сохраняем обратную совместимость  
VaultCore = SecureVaultCore