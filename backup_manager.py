# backup_manager.py - СИСТЕМА БЭКАПОВ И ВОССТАНОВЛЕНИЯ
import os
import json
import shutil
import logging
import threading
import hashlib
import tempfile
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from cryptography.fernet import Fernet

from securestring import SecureString


class BackupStrategy:
    """Стратегия резервного копирования"""
    
    def __init__(self, max_backups: int = 10, retention_days: int = 30):
        self.max_backups = max_backups
        self.retention_days = retention_days
        self._lock = threading.RLock()
    
    def should_create_backup(self, last_backup_time: Optional[datetime]) -> bool:
        """Определение необходимости создания бэкапа"""
        if last_backup_time is None:
            return True
        
        # Минимум 1 бэкап в день
        time_since_last = datetime.now() - last_backup_time
        return time_since_last >= timedelta(days=1)
    
    def get_backups_to_delete(self, backups: List[Dict]) -> List[str]:
        """Определение бэкапов для удаления"""
        with self._lock:
            if len(backups) <= self.max_backups:
                return []
            
            # Сортируем по дате создания (старые сначала)
            sorted_backups = sorted(backups, key=lambda x: x['created_at'])
            
            # Удаляем старые сверх лимита
            to_delete = []
            for i in range(len(sorted_backups) - self.max_backups):
                to_delete.append(sorted_backups[i]['path'])
            
            # Также удаляем бэкапы старше retention_days
            cutoff_date = datetime.now() - timedelta(days=self.retention_days)
            for backup in sorted_backups:
                if backup['created_at'] < cutoff_date:
                    to_delete.append(backup['path'])
            
            return list(set(to_delete))
    
    def get_recommended_backup_time(self) -> datetime:
        """Рекомендуемое время для следующего бэкапа"""
        return datetime.now() + timedelta(hours=6)  # Каждые 6 часов


class BackupIntegrityChecker:
    """Проверка целостности бэкапов"""
    
    @staticmethod
    def calculate_backup_hash(backup_path: str) -> str:
        """Вычисление хэша бэкапа"""
        sha256_hash = hashlib.sha256()
        
        with open(backup_path, 'rb') as f:
            # Читаем файл по частям для экономии памяти
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        
        return sha256_hash.hexdigest()
    
    @staticmethod
    def verify_backup_integrity(backup_path: str, expected_hash: str) -> bool:
        """Проверка целостности бэкапа"""
        if not os.path.exists(backup_path):
            return False
        
        actual_hash = BackupIntegrityChecker.calculate_backup_hash(backup_path)
        return actual_hash == expected_hash
    
    @staticmethod
    def check_backup_structure(backup_path: str) -> List[str]:
        """Проверка структуры бэкапа"""
        issues = []
        
        try:
            with zipfile.ZipFile(backup_path, 'r') as zip_ref:
                # Проверяем обязательные файлы
                required_files = [
                    'manifest.json',
                    'filesystem.json.enc',
                    'vault_config.json'
                ]
                
                for required_file in required_files:
                    if required_file not in zip_ref.namelist():
                        issues.append(f"Отсутствует обязательный файл: {required_file}")
                
                # Проверяем целостность архива
                bad_files = zip_ref.testzip()
                if bad_files:
                    issues.append(f"Поврежденные файлы в архиве: {bad_files}")
        
        except (zipfile.BadZipFile, zipfile.LargeZipFile) as e:
            issues.append(f"Архив поврежден: {e}")
        
        return issues


class BackupCreator:
    """Создание резервных копий"""
    
    def __init__(self, crypto_manager, auth_manager):
        self.crypto = crypto_manager
        self.auth = auth_manager
        self.backup_dir = 'data/backups'
        self._lock = threading.RLock()
        
        # Создаем директорию для бэкапов
        os.makedirs(self.backup_dir, exist_ok=True)
    
    def create_backup(self, vault_core, backup_type: str = 'full', 
                     password: Optional[str] = None) -> Tuple[bool, str]:
        """Создание резервной копии"""
        with self._lock:
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_filename = f"backup_{backup_type}_{timestamp}.zip"
                backup_path = os.path.join(self.backup_dir, backup_filename)
                
                # Создаем временную директорию для бэкапа
                temp_dir = tempfile.mkdtemp(prefix='backup_')
                
                try:
                    # 1. Сохраняем файловую систему
                    self._backup_filesystem(vault_core, temp_dir)
                    
                    # 2. Сохраняем конфигурацию
                    self._backup_configuration(temp_dir)
                    
                    # 3. Сохраняем зашифрованные файлы (для полного бэкапа)
                    if backup_type == 'full':
                        self._backup_encrypted_files(vault_core, temp_dir)
                    
                    # 4. Создаем манифест
                    manifest = self._create_manifest(vault_core, backup_type, timestamp)
                    manifest_path = os.path.join(temp_dir, 'manifest.json')
                    with open(manifest_path, 'w', encoding='utf-8') as f:
                        json.dump(manifest, f, indent=2, ensure_ascii=False)
                    
                    # 5. Создаем зашифрованный архив
                    success = self._create_encrypted_archive(
                        temp_dir, backup_path, manifest, password
                    )
                    
                    if success:
                        # 6. Проверяем целостность созданного бэкапа
                        if not self._verify_new_backup(backup_path, manifest['hash']):
                            raise ValueError("Проверка целостности созданного бэкапа не пройдена")
                        
                        logging.info(f"Создан бэкап: {backup_filename}")
                        return True, backup_path
                    else:
                        return False, ""
                        
                finally:
                    # Очищаем временную директорию
                    self._cleanup_temp_dir(temp_dir)
                    
            except Exception as e:
                logging.error(f"Ошибка создания бэкапа: {e}")
                return False, ""
    
    def _backup_filesystem(self, vault_core, temp_dir: str):
        """Бэкап файловой системы"""
        # Копируем зашифрованную файловую систему
        fs_source = vault_core.filesystem_path
        fs_dest = os.path.join(temp_dir, 'filesystem.json.enc')
        
        if os.path.exists(fs_source):
            shutil.copy2(fs_source, fs_dest)
    
    def _backup_configuration(self, temp_dir: str):
        """Бэкап конфигурации"""
        config_files = ['vault_config.json']
        
        for config_file in config_files:
            source = os.path.join('data', config_file)
            dest = os.path.join(temp_dir, config_file)
            
            if os.path.exists(source):
                shutil.copy2(source, dest)
    
    def _backup_encrypted_files(self, vault_core, temp_dir: str):
        """Бэкап зашифрованных файлов"""
        encrypted_files_dir = 'data/encrypted_files'
        backup_files_dir = os.path.join(temp_dir, 'encrypted_files')
        
        if os.path.exists(encrypted_files_dir):
            os.makedirs(backup_files_dir, exist_ok=True)
            
            # Копируем только файлы .myarc
            for filename in os.listdir(encrypted_files_dir):
                if filename.endswith('.myarc'):
                    source = os.path.join(encrypted_files_dir, filename)
                    dest = os.path.join(backup_files_dir, filename)
                    shutil.copy2(source, dest)
    
    def _create_manifest(self, vault_core, backup_type: str, timestamp: str) -> Dict:
        """Создание манифеста бэкапа"""
        manifest = {
            'version': '2.0',
            'backup_type': backup_type,
            'created_at': datetime.now().isoformat(),
            'timestamp': timestamp,
            'app_version': '1.0.0',
            'content': {}
        }
        
        # Информация о файловой системе
        if 'files' in vault_core.filesystem:
            manifest['content']['file_count'] = len(vault_core.filesystem['files'])
            manifest['content']['folder_count'] = len(vault_core.filesystem['folders'])
        
        # Информация о размере
        total_size = 0
        if os.path.exists('data/encrypted_files'):
            for file in os.listdir('data/encrypted_files'):
                filepath = os.path.join('data/encrypted_files', file)
                if os.path.isfile(filepath):
                    total_size += os.path.getsize(filepath)
        
        manifest['content']['total_size'] = total_size
        
        return manifest
    
    def _create_encrypted_archive(self, temp_dir: str, output_path: str, 
                                 manifest: Dict, password: Optional[str]) -> bool:
        """Создание зашифрованного архива"""
        try:
            # Сначала создаем обычный ZIP архив
            temp_zip = output_path + '.tmp'
            
            with zipfile.ZipFile(temp_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Добавляем все файлы из временной директории
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, temp_dir)
                        zipf.write(file_path, arcname)
            
            # Вычисляем хэш архива
            with open(temp_zip, 'rb') as f:
                archive_data = f.read()
                manifest['hash'] = hashlib.sha256(archive_data).hexdigest()
            
            # Если указан пароль, шифруем архив
            if password:
                # Генерируем ключ из пароля
                salt = os.urandom(32)
                key, _ = self.crypto.generate_key_from_password(password, salt)
                
                # Шифруем архив
                fernet = Fernet(key)
                encrypted_data = fernet.encrypt(archive_data)
                
                # Сохраняем с солью
                with open(output_path, 'wb') as f:
                    f.write(salt)
                    f.write(encrypted_data)
                
                # Удаляем временный файл
                os.remove(temp_zip)
                
            else:
                # Просто переименовываем
                os.rename(temp_zip, output_path)
            
            # Обновляем манифест в архиве (если не зашифрован)
            if not password:
                self._update_manifest_in_zip(output_path, manifest)
            
            return True
            
        except Exception as e:
            logging.error(f"Ошибка создания архива: {e}")
            
            # Очистка при ошибке
            for file in [output_path, output_path + '.tmp']:
                if os.path.exists(file):
                    try:
                        os.remove(file)
                    except:
                        pass
            
            return False
    
    def _update_manifest_in_zip(self, zip_path: str, manifest: Dict):
        """Обновление манифеста в ZIP архиве"""
        try:
            # Создаем временный архив
            temp_zip = zip_path + '.new'
            
            with zipfile.ZipFile(zip_path, 'r') as zip_in:
                with zipfile.ZipFile(temp_zip, 'w', zipfile.ZIP_DEFLATED) as zip_out:
                    # Копируем все файлы, обновляя manifest.json
                    for item in zip_in.infolist():
                        if item.filename == 'manifest.json':
                            # Записываем обновленный манифест
                            manifest_data = json.dumps(manifest, ensure_ascii=False).encode()
                            zip_out.writestr(item, manifest_data)
                        else:
                            # Копируем как есть
                            data = zip_in.read(item.filename)
                            zip_out.writestr(item, data)
            
            # Заменяем старый архив новым
            os.replace(temp_zip, zip_path)
            
        except Exception as e:
            logging.error(f"Ошибка обновления манифеста: {e}")
    
    def _verify_new_backup(self, backup_path: str, expected_hash: str) -> bool:
        """Проверка нового бэкапа"""
        if not os.path.exists(backup_path):
            return False
        
        return BackupIntegrityChecker.verify_backup_integrity(backup_path, expected_hash)
    
    def _cleanup_temp_dir(self, temp_dir: str):
        """Очистка временной директории"""
        try:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
        except Exception as e:
            logging.error(f"Ошибка очистки временной директории: {e}")
    
    def create_incremental_backup(self, vault_core, last_backup_time: datetime, 
                                password: Optional[str] = None) -> Tuple[bool, str]:
        """Создание инкрементального бэкапа"""
        # Реализация инкрементального бэкапа
        # (упрощенная версия - в реальности нужно отслеживать изменения)
        return self.create_backup(vault_core, 'incremental', password)


class BackupRestorer:
    """Восстановление из резервной копии"""
    
    def __init__(self, crypto_manager, auth_manager):
        self.crypto = crypto_manager
        self.auth = auth_manager
    
    def restore_backup(self, backup_path: str, password: Optional[str] = None, 
                      restore_type: str = 'full') -> Tuple[bool, str]:
        """Восстановление из бэкапа"""
        try:
            # 1. Проверяем бэкап
            if not os.path.exists(backup_path):
                return False, "Файл бэкапа не найден"
            
            # 2. Расшифровываем архив если нужно
            if password:
                archive_data = self._decrypt_backup(backup_path, password)
                if archive_data is None:
                    return False, "Неверный пароль или архив поврежден"
            else:
                with open(backup_path, 'rb') as f:
                    archive_data = f.read()
            
            # 3. Извлекаем архив
            temp_dir = tempfile.mkdtemp(prefix='restore_')
            
            try:
                # Создаем временный файл архива
                temp_zip = os.path.join(temp_dir, 'backup.zip')
                with open(temp_zip, 'wb') as f:
                    f.write(archive_data)
                
                # Извлекаем архив
                with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
                
                # 4. Проверяем манифест
                manifest_path = os.path.join(temp_dir, 'manifest.json')
                if not os.path.exists(manifest_path):
                    return False, "Манифест не найден"
                
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)
                
                # 5. Восстанавливаем данные
                if restore_type == 'full':
                    success, message = self._full_restore(temp_dir, manifest)
                elif restore_type == 'filesystem_only':
                    success, message = self._filesystem_restore(temp_dir, manifest)
                else:
                    return False, f"Неизвестный тип восстановления: {restore_type}"
                
                return success, message
                
            finally:
                self._cleanup_temp_dir(temp_dir)
                
        except Exception as e:
            logging.error(f"Ошибка восстановления из бэкапа: {e}")
            return False, f"Ошибка восстановления: {e}"
    
    def _decrypt_backup(self, backup_path: str, password: str) -> Optional[bytes]:
        """Расшифровка бэкапа"""
        try:
            with open(backup_path, 'rb') as f:
                # Читаем соль
                salt = f.read(32)
                encrypted_data = f.read()
            
            # Генерируем ключ из пароля
            key, _ = self.crypto.generate_key_from_password(password, salt)
            
            # Расшифровываем
            fernet = Fernet(key)
            return fernet.decrypt(encrypted_data)
            
        except Exception as e:
            logging.error(f"Ошибка расшифровки бэкапа: {e}")
            return None
    
    def _full_restore(self, temp_dir: str, manifest: Dict) -> Tuple[bool, str]:
        """Полное восстановление"""
        try:
            # 1. Создаем бэкап текущих данных
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            current_backup_dir = os.path.join('data/backups', f'pre_restore_{timestamp}')
            os.makedirs(current_backup_dir, exist_ok=True)
            
            # Копируем текущие данные
            for item in ['vault_config.json', 'filesystem.json.enc']:
                source = os.path.join('data', item)
                if os.path.exists(source):
                    shutil.copy2(source, os.path.join(current_backup_dir, item))
            
            # 2. Восстанавливаем конфигурацию
            config_source = os.path.join(temp_dir, 'vault_config.json')
            config_dest = os.path.join('data', 'vault_config.json')
            
            if os.path.exists(config_source):
                shutil.copy2(config_source, config_dest)
            else:
                return False, "Конфигурация не найдена в бэкапе"
            
            # 3. Восстанавливаем файловую систему
            fs_source = os.path.join(temp_dir, 'filesystem.json.enc')
            fs_dest = os.path.join('data', 'filesystem.json.enc')
            
            if os.path.exists(fs_source):
                shutil.copy2(fs_source, fs_dest)
            else:
                return False, "Файловая система не найдена в бэкапе"
            
            # 4. Восстанавливаем зашифрованные файлы
            encrypted_source = os.path.join(temp_dir, 'encrypted_files')
            encrypted_dest = 'data/encrypted_files'
            
            if os.path.exists(encrypted_source):
                # Очищаем текущую директорию
                if os.path.exists(encrypted_dest):
                    shutil.rmtree(encrypted_dest)
                
                # Копируем файлы из бэкапа
                shutil.copytree(encrypted_source, encrypted_dest)
            
            return True, f"Восстановление выполнено успешно. Текущие данные сохранены в {current_backup_dir}"
            
        except Exception as e:
            logging.error(f"Ошибка полного восстановления: {e}")
            return False, f"Ошибка восстановления: {e}"
    
    def _filesystem_restore(self, temp_dir: str, manifest: Dict) -> Tuple[bool, str]:
        """Восстановление только файловой системы"""
        try:
            # Восстанавливаем только файловую систему
            fs_source = os.path.join(temp_dir, 'filesystem.json.enc')
            fs_dest = os.path.join('data', 'filesystem.json.enc')
            
            if os.path.exists(fs_source):
                # Создаем бэкап текущей файловой системы
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = os.path.join('data/backups', f'fs_backup_{timestamp}.enc')
                
                if os.path.exists(fs_dest):
                    shutil.copy2(fs_dest, backup_path)
                
                # Восстанавливаем
                shutil.copy2(fs_source, fs_dest)
                
                return True, f"Файловая система восстановлена. Предыдущая сохранена как {backup_path}"
            else:
                return False, "Файловая система не найдена в бэкапе"
                
        except Exception as e:
            logging.error(f"Ошибка восстановления файловой системы: {e}")
            return False, f"Ошибка восстановления: {e}"
    
    def _cleanup_temp_dir(self, temp_dir: str):
        """Очистка временной директории"""
        try:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
        except Exception as e:
            logging.error(f"Ошибка очистки временной директории: {e}")


class BackupScheduler:
    """Планировщик бэкапов"""
    
    def __init__(self, backup_manager):
        self.backup_manager = backup_manager
        self._scheduler_thread = None
        self._is_running = False
        self._backup_interval = 6 * 3600  # 6 часов
        self._last_backup_time = None
    
    def start(self):
        """Запуск планировщика"""
        if self._is_running:
            return
        
        self._is_running = True
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._scheduler_thread.start()
        logging.info("Планировщик бэкапов запущен")
    
    def stop(self):
        """Остановка планировщика"""
        self._is_running = False
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            self._scheduler_thread.join(timeout=2.0)
        logging.info("Планировщик бэкапов остановлен")
    
    def _scheduler_loop(self):
        """Цикл планировщика"""
        while self._is_running:
            try:
                # Проверяем необходимость бэкапа
                if self._should_create_backup():
                    logging.info("Планировщик: создание запланированного бэкапа")
                    # Здесь можно вызвать создание бэкапа
                    # self.backup_manager.create_backup(...)
                
                # Ждем до следующей проверки
                time.sleep(3600)  # Проверяем каждый час
                
            except Exception as e:
                logging.error(f"Ошибка в планировщике бэкапов: {e}")
                time.sleep(600)  # Ждем 10 минут при ошибке
    
    def _should_create_backup(self) -> bool:
        """Определение необходимости создания бэкапа"""
        if self._last_backup_time is None:
            return True
        
        time_since_last = datetime.now() - self._last_backup_time
        return time_since_last.total_seconds() >= self._backup_interval
    
    def force_backup(self):
        """Принудительное создание бэкапа"""
        self._last_backup_time = None


class BackupManager:
    """Главный менеджер бэкапов"""
    
    def __init__(self, crypto_manager, auth_manager, vault_core):
        self.crypto = crypto_manager
        self.auth = auth_manager
        self.vault_core = vault_core
        
        self.strategy = BackupStrategy()
        self.creator = BackupCreator(crypto_manager, auth_manager)
        self.restorer = BackupRestorer(crypto_manager, auth_manager)
        self.integrity_checker = BackupIntegrityChecker()
        self.scheduler = BackupScheduler(self)
        
        self._backups_metadata = {}
        self._load_backups_metadata()
    
    def _load_backups_metadata(self):
        """Загрузка метаданных бэкапов"""
        backups_dir = 'data/backups'
        if not os.path.exists(backups_dir):
            return
        
        for filename in os.listdir(backups_dir):
            if filename.endswith('.zip'):
                backup_path = os.path.join(backups_dir, filename)
                metadata = self._extract_backup_metadata(backup_path)
                if metadata:
                    self._backups_metadata[backup_path] = metadata
    
    def _extract_backup_metadata(self, backup_path: str) -> Optional[Dict]:
        """Извлечение метаданных из бэкапа"""
        try:
            # Пытаемся прочитать манифест без полного распаковки
            with zipfile.ZipFile(backup_path, 'r') as zip_ref:
                if 'manifest.json' in zip_ref.namelist():
                    with zip_ref.open('manifest.json') as f:
                        manifest = json.load(f)
                    
                    file_stats = os.stat(backup_path)
                    
                    return {
                        'path': backup_path,
                        'filename': os.path.basename(backup_path),
                        'size': file_stats.st_size,
                        'created_at': datetime.fromtimestamp(file_stats.st_mtime),
                        'manifest': manifest,
                        'hash': self.integrity_checker.calculate_backup_hash(backup_path)
                    }
        except:
            return None
    
    def get_available_backups(self) -> List[Dict]:
        """Получение списка доступных бэкапов"""
        backups = list(self._backups_metadata.values())
        return sorted(backups, key=lambda x: x['created_at'], reverse=True)
    
    def create_scheduled_backup(self, password: Optional[str] = None) -> Tuple[bool, str]:
        """Создание запланированного бэкапа"""
        # Определяем тип бэкапа
        backups = self.get_available_backups()
        backup_type = 'full' if len(backups) % 7 == 0 else 'incremental'  # Полный бэкап раз в неделю
        
        success, backup_path = self.creator.create_backup(
            self.vault_core, backup_type, password
        )
        
        if success and backup_path:
            # Обновляем метаданные
            metadata = self._extract_backup_metadata(backup_path)
            if metadata:
                self._backups_metadata[backup_path] = metadata
            
            # Очищаем старые бэкапы
            self._cleanup_old_backups()
        
        return success, backup_path if success else ""
    
    def _cleanup_old_backups(self):
        """Очистка старых бэкапов"""
        backups = self.get_available_backups()
        to_delete = self.strategy.get_backups_to_delete(backups)
        
        for backup_path in to_delete:
            try:
                os.remove(backup_path)
                if backup_path in self._backups_metadata:
                    del self._backups_metadata[backup_path]
                logging.info(f"Удален старый бэкап: {backup_path}")
            except Exception as e:
                logging.error(f"Ошибка удаления бэкапа {backup_path}: {e}")
    
    def verify_backup(self, backup_path: str) -> Tuple[bool, List[str]]:
        """Проверка бэкапа"""
        if backup_path not in self._backups_metadata:
            return False, ["Бэкап не найден в метаданных"]
        
        metadata = self._backups_metadata[backup_path]
        
        # Проверяем целостность
        if not self.integrity_checker.verify_backup_integrity(
            backup_path, metadata['hash']
        ):
            return False, ["Хэш бэкапа не совпадает"]
        
        # Проверяем структуру
        issues = self.integrity_checker.check_backup_structure(backup_path)
        
        return len(issues) == 0, issues
    
    def restore_from_backup(self, backup_path: str, password: Optional[str] = None,
                          restore_type: str = 'full') -> Tuple[bool, str]:
        """Восстановление из бэкапа"""
        # Сначала проверяем бэкап
        is_valid, issues = self.verify_backup(backup_path)
        if not is_valid:
            return False, f"Бэкап не прошел проверку: {', '.join(issues)}"
        
        # Выполняем восстановление
        return self.restorer.restore_backup(backup_path, password, restore_type)
    
    def get_backup_info(self, backup_path: str) -> Optional[Dict]:
        """Получение информации о бэкапе"""
        return self._backups_metadata.get(backup_path)
    
    def start_scheduler(self):
        """Запуск планировщика"""
        self.scheduler.start()
    
    def stop_scheduler(self):
        """Остановка планировщика"""
        self.scheduler.stop()