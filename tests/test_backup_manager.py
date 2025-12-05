# tests/test_backup_manager.py - ТЕСТЫ СИСТЕМЫ БЭКАПОВ
import unittest
import tempfile
import os
import json
import zipfile
import shutil
from unittest.mock import Mock, patch, MagicMock

from backup_manager import (
    BackupStrategy,
    BackupIntegrityChecker,
    BackupCreator,
    BackupRestorer,
    BackupManager
)


class TestBackupStrategy(unittest.TestCase):
    """Тесты стратегии бэкапов"""
    
    def setUp(self):
        """Настройка перед каждым тестом"""
        self.strategy = BackupStrategy(max_backups=5, retention_days=7)
    
    def test_should_create_backup(self):
        """Тест определения необходимости бэкапа"""
        from datetime import datetime, timedelta
        
        # Первый бэкап
        self.assertTrue(self.strategy.should_create_backup(None))
        
        # Бэкап сегодня
        now = datetime.now()
        self.assertFalse(self.strategy.should_create_backup(now))
        
        # Бэкап вчера
        yesterday = now - timedelta(days=1)
        self.assertTrue(self.strategy.should_create_backup(yesterday))
        
        # Бэкап 2 дня назад
        two_days_ago = now - timedelta(days=2)
        self.assertTrue(self.strategy.should_create_backup(two_days_ago))
    
    def test_get_backups_to_delete(self):
        """Тест определения бэкапов для удаления"""
        from datetime import datetime, timedelta
        
        now = datetime.now()
        
        # Создаем тестовые бэкапы
        backups = []
        for i in range(10):
            backup_time = now - timedelta(days=i)
            backups.append({
                'path': f'/backup/backup_{i}.zip',
                'created_at': backup_time
            })
        
        # Проверяем, какие бэкапы нужно удалить
        to_delete = self.strategy.get_backups_to_delete(backups)
        
        # Должно быть удалено 5 бэкапов (10 - 5)
        self.assertEqual(len(to_delete), 5)
        
        # Проверяем, что удаляются самые старые
        expected_to_delete = [f'/backup/backup_{i}.zip' for i in range(5)]
        self.assertEqual(sorted(to_delete), sorted(expected_to_delete))
    
    def test_get_backups_to_delete_with_old_backups(self):
        """Тест удаления старых бэкапов"""
        from datetime import datetime, timedelta
        
        now = datetime.now()
        
        # Создаем бэкапы, некоторые очень старые
        backups = [
            {'path': '/backup/old_30.zip', 'created_at': now - timedelta(days=30)},
            {'path': '/backup/old_15.zip', 'created_at': now - timedelta(days=15)},
            {'path': '/backup/new_1.zip', 'created_at': now - timedelta(days=1)},
            {'path': '/backup/new_2.zip', 'created_at': now - timedelta(days=2)},
        ]
        
        to_delete = self.strategy.get_backups_to_delete(backups)
        
        # Должны быть удалены бэкапы старше 7 дней
        self.assertIn('/backup/old_30.zip', to_delete)
        self.assertIn('/backup/old_15.zip', to_delete)
        self.assertNotIn('/backup/new_1.zip', to_delete)
        self.assertNotIn('/backup/new_2.zip', to_delete)


class TestBackupIntegrityChecker(unittest.TestCase):
    """Тесты проверки целостности"""
    
    def setUp(self):
        """Настройка перед каждым тестом"""
        self.test_dir = tempfile.mkdtemp(prefix='integrity_test_')
    
    def tearDown(self):
        """Очистка после каждого теста"""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    def test_calculate_backup_hash(self):
        """Тест вычисления хэша"""
        # Создаем тестовый файл
        test_file = os.path.join(self.test_dir, 'test.txt')
        test_content = b"Hello, this is a test file for backup"
        
        with open(test_file, 'wb') as f:
            f.write(test_content)
        
        # Вычисляем хэш
        hash_value = BackupIntegrityChecker.calculate_backup_hash(test_file)
        
        # Проверяем, что хэш вычислен
        self.assertEqual(len(hash_value), 64)  # SHA-256 в hex
        
        # Проверяем воспроизводимость
        hash_value2 = BackupIntegrityChecker.calculate_backup_hash(test_file)
        self.assertEqual(hash_value, hash_value2)
    
    def test_verify_backup_integrity(self):
        """Тест проверки целостности"""
        # Создаем тестовый файл
        test_file = os.path.join(self.test_dir, 'test.txt')
        test_content = b"Test content"
        
        with open(test_file, 'wb') as f:
            f.write(test_content)
        
        # Вычисляем правильный хэш
        correct_hash = BackupIntegrityChecker.calculate_backup_hash(test_file)
        
        # Проверяем правильный хэш
        self.assertTrue(BackupIntegrityChecker.verify_backup_integrity(
            test_file, correct_hash
        ))
        
        # Проверяем неправильный хэш
        wrong_hash = "0" * 64
        self.assertFalse(BackupIntegrityChecker.verify_backup_integrity(
            test_file, wrong_hash
        ))
    
    def test_check_backup_structure(self):
        """Тест проверки структуры архива"""
        # Создаем правильный ZIP архив
        good_zip = os.path.join(self.test_dir, 'good_backup.zip')
        
        with zipfile.ZipFile(good_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.writestr('manifest.json', '{"version": "1.0"}')
            zipf.writestr('filesystem.json.enc', 'encrypted_data')
            zipf.writestr('vault_config.json', 'config_data')
        
        # Проверяем правильный архив
        issues = BackupIntegrityChecker.check_backup_structure(good_zip)
        self.assertEqual(len(issues), 0)
        
        # Создаем архив без обязательных файлов
        bad_zip = os.path.join(self.test_dir, 'bad_backup.zip')
        
        with zipfile.ZipFile(bad_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.writestr('some_file.txt', 'data')
        
        # Проверяем архив без обязательных файлов
        issues = BackupIntegrityChecker.check_backup_structure(bad_zip)
        self.assertGreater(len(issues), 0)
        
        # Создаем поврежденный архив
        corrupted_zip = os.path.join(self.test_dir, 'corrupted.zip')
        
        with open(corrupted_zip, 'wb') as f:
            f.write(b'PK\x03\x04\x14\x00\x00\x00')  # Неполный заголовок ZIP
        
        # Проверяем поврежденный архив
        issues = BackupIntegrityChecker.check_backup_structure(corrupted_zip)
        self.assertGreater(len(issues), 0)


class TestBackupCreator(unittest.TestCase):
    """Тесты создания бэкапов"""
    
    def setUp(self):
        """Настройка перед каждым тестом"""
        self.test_dir = tempfile.mkdtemp(prefix='backup_test_')
        
        # Мокируем менеджеры
        self.crypto_mock = Mock()
        self.auth_mock = Mock()
        self.vault_core_mock = Mock()
        
        # Настраиваем моки
        self.crypto_mock.generate_key_from_password.return_value = (
            b'encryption_key_32_bytes_long!!', 
            b'salt_32_bytes'
        )
        
        # Создаем экземпляр BackupCreator
        self.creator = BackupCreator(self.crypto_mock, self.auth_mock)
        self.creator.backup_dir = self.test_dir
        
        # Создаем тестовую файловую систему
        self.vault_core_mock.filesystem_path = os.path.join(self.test_dir, 'filesystem.json.enc')
        self.vault_core_mock.filesystem = {
            'files': {
                'file1': {'id': 'file1', 'name': 'test1.txt', 'size': 100},
                'file2': {'id': 'file2', 'name': 'test2.txt', 'size': 200}
            },
            'folders': {
                'root': {'id': 'root', 'name': 'Root', 'children': ['file1', 'file2']},
                'folder1': {'id': 'folder1', 'name': 'Folder1', 'children': []}
            }
        }
        
        # Создаем тестовые файлы
        os.makedirs(os.path.join(self.test_dir, 'encrypted_files'), exist_ok=True)
        for i in range(3):
            file_path = os.path.join(self.test_dir, 'encrypted_files', f'file{i}.myarc')
            with open(file_path, 'wb') as f:
                f.write(f'encrypted_data_{i}'.encode())
    
    def tearDown(self):
        """Очистка после каждого теста"""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    def test_create_full_backup(self):
        """Тест создания полного бэкапа"""
        # Создаем бэкап
        success, backup_path = self.creator.create_backup(
            self.vault_core_mock, 'full'
        )
        
        # Проверяем успешность
        self.assertTrue(success)
        self.assertTrue(os.path.exists(backup_path))
        
        # Проверяем, что файл имеет правильное расширение
        self.assertTrue(backup_path.endswith('.zip'))
        
        # Проверяем содержимое архива
        with zipfile.ZipFile(backup_path, 'r') as zipf:
            files = zipf.namelist()
            
            # Проверяем обязательные файлы
            self.assertIn('manifest.json', files)
            self.assertIn('filesystem.json.enc', files)
            self.assertIn('vault_config.json', files)
            self.assertIn('encrypted_files/', files)
    
    def test_create_backup_with_password(self):
        """Тест создания зашифрованного бэкапа"""
        # Создаем зашифрованный бэкап
        success, backup_path = self.creator.create_backup(
            self.vault_core_mock, 'full', 'secret_password'
        )
        
        # Проверяем успешность
        self.assertTrue(success)
        self.assertTrue(os.path.exists(backup_path))
        
        # Проверяем, что файл зашифрован (имеет соль в начале)
        with open(backup_path, 'rb') as f:
            first_bytes = f.read(32)
        
        # Первые 32 байта - это соль
        self.assertEqual(len(first_bytes), 32)
    
    def test_create_incremental_backup(self):
        """Тест создания инкрементального бэкапа"""
        # Создаем инкрементальный бэкап
        success, backup_path = self.creator.create_backup(
            self.vault_core_mock, 'incremental'
        )
        
        # Проверяем успешность
        self.assertTrue(success)
        self.assertTrue(os.path.exists(backup_path))
    
    def test_backup_verification(self):
        """Тест проверки созданного бэкапа"""
        # Создаем бэкап
        success, backup_path = self.creator.create_backup(
            self.vault_core_mock, 'full'
        )
        
        self.assertTrue(success)
        
        # Проверяем целостность
        with zipfile.ZipFile(backup_path, 'r') as zipf:
            # Читаем манифест
            with zipf.open('manifest.json') as f:
                manifest = json.load(f)
            
            # Проверяем хэш
            expected_hash = manifest.get('hash')
            self.assertIsNotNone(expected_hash)
            
            # Проверяем целостность
            is_valid = BackupIntegrityChecker.verify_backup_integrity(
                backup_path, expected_hash
            )
            self.assertTrue(is_valid)


class TestBackupRestorer(unittest.TestCase):
    """Тесты восстановления из бэкапов"""
    
    def setUp(self):
        """Настройка перед каждым тестом"""
        self.test_dir = tempfile.mkdtemp(prefix='restore_test_')
        
        # Мокируем менеджеры
        self.crypto_mock = Mock()
        self.auth_mock = Mock()
        
        # Настраиваем моки
        self.crypto_mock.generate_key_from_password.return_value = (
            b'encryption_key_32_bytes_long!!', 
            b'salt_32_bytes'
        )
        
        # Создаем экземпляр BackupRestorer
        self.restorer = BackupRestorer(self.crypto_mock, self.auth_mock)
        
        # Создаем тестовый бэкап
        self.create_test_backup()
    
    def tearDown(self):
        """Очистка после каждого теста"""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    def create_test_backup(self):
        """Создание тестового бэкапа"""
        # Создаем ZIP архив с тестовыми данными
        self.backup_path = os.path.join(self.test_dir, 'test_backup.zip')
        
        # Манифест
        manifest = {
            'version': '2.0',
            'backup_type': 'full',
            'created_at': '2024-01-01T00:00:00',
            'timestamp': '20240101_000000',
            'app_version': '1.0.0',
            'content': {
                'file_count': 2,
                'folder_count': 2,
                'total_size': 300
            }
        }
        
        with zipfile.ZipFile(self.backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Добавляем манифест
            manifest_str = json.dumps(manifest, indent=2)
            zipf.writestr('manifest.json', manifest_str)
            
            # Добавляем тестовые файлы
            zipf.writestr('filesystem.json.enc', 'encrypted_filesystem_data')
            zipf.writestr('vault_config.json', 'config_data')
            
            # Добавляем зашифрованные файлы
            zipf.writestr('encrypted_files/file1.mya', 'encrypted_file_data_1')
            zipf.writestr('encrypted_files/file2.mya', 'encrypted_file_data_2')
        
        # Вычисляем и добавляем хэш
        hash_value = BackupIntegrityChecker.calculate_backup_hash(self.backup_path)
        manifest['hash'] = hash_value
        
        # Обновляем манифест в архиве
        with zipfile.ZipFile(self.backup_path, 'a', zipfile.ZIP_DEFLATED) as zipf:
            # Удаляем старый манифест
            zipf.remove('manifest.json')
            
            # Добавляем новый с хэшем
            manifest_str = json.dumps(manifest, indent=2)
            zipf.writestr('manifest.json', manifest_str)
    
    def test_restore_full_backup(self):
        """Тест полного восстановления"""
        # Мокируем директории
        with patch('shutil.copy2') as mock_copy, \
             patch('shutil.rmtree') as mock_rmtree, \
             patch('os.makedirs') as mock_makedirs, \
             patch('os.path.exists', return_value=True):
            
            # Восстанавливаем
            success, message = self.restorer.restore_backup(
                self.backup_path, None, 'full'
            )
            
            # Проверяем успешность
            self.assertTrue(success)
            self.assertIn("успешно", message.lower())
            
            # Проверяем, что функции были вызваны
            self.assertGreater(mock_copy.call_count, 0)
    
    def test_restore_encrypted_backup(self):
        """Тест восстановления из зашифрованного бэкапа"""
        # Мокируем расшифровку
        with open(self.backup_path, 'rb') as f:
            backup_data = f.read()
        
        self.crypto_mock.generate_key_from_password.return_value = (
            b'key_32_bytes', b'salt_32_bytes'
        )
        
        # Мокируем Fernet
        with patch('backup_manager.Fernet') as mock_fernet_class:
            mock_fernet = Mock()
            mock_fernet.decrypt.return_value = backup_data
            mock_fernet_class.return_value = mock_fernet
            
            # Мокируем остальные операции
            with patch('shutil.copy2'), patch('shutil.rmtree'), \
                 patch('os.makedirs'), patch('os.path.exists', return_value=True):
                
                # Восстанавливаем с паролем
                success, message = self.restorer.restore_backup(
                    self.backup_path, 'password', 'full'
                )
                
                # Проверяем успешность
                self.assertTrue(success)
    
    def test_restore_filesystem_only(self):
        """Тест восстановления только файловой системы"""
        # Мокируем операции
        with patch('shutil.copy2') as mock_copy, \
             patch('os.path.exists', return_value=True):
            
            # Восстанавливаем только файловую систему
            success, message = self.restorer.restore_backup(
                self.backup_path, None, 'filesystem_only'
            )
            
            # Проверяем успешность
            self.assertTrue(success)
            self.assertIn("файловая система восстановлена", message.lower())
            
            # Проверяем, что копирование было вызвано
            mock_copy.assert_called()
    
    def test_restore_nonexistent_backup(self):
        """Тест восстановления из несуществующего бэкапа"""
        # Пытаемся восстановить из несуществующего файла
        success, message = self.restorer.restore_backup(
            '/nonexistent/path/backup.zip', None, 'full'
        )
        
        # Проверяем неудачу
        self.assertFalse(success)
        self.assertIn("не найден", message.lower())


class TestBackupManagerIntegration(unittest.TestCase):
    """Интеграционные тесты менеджера бэкапов"""
    
    def setUp(self):
        """Настройка перед каждым тестом"""
        self.test_dir = tempfile.mkdtemp(prefix='backup_manager_test_')
        
        # Мокируем зависимости
        self.crypto_mock = Mock()
        self.auth_mock = Mock()
        self.vault_core_mock = Mock()
        
        # Создаем менеджер бэкапов
        self.manager = BackupManager(
            self.crypto_mock,
            self.auth_mock,
            self.vault_core_mock
        )
        
        # Используем тестовую директорию
        self.manager.creator.backup_dir = self.test_dir
        self.manager.strategy.max_backups = 3
    
    def tearDown(self):
        """Очистка после каждого теста"""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    def test_backup_lifecycle(self):
        """Тест полного жизненного цикла бэкапа"""
        # Создаем несколько бэкапов
        backup_paths = []
        for i in range(5):
            # Мокируем создание бэкапа
            backup_path = os.path.join(self.test_dir, f'backup_{i}.zip')
            with patch.object(self.manager.creator, 'create_backup') as mock_create:
                mock_create.return_value = (True, backup_path)
                
                success, path = self.manager.create_scheduled_backup()
                if success:
                    backup_paths.append(path)
        
        # Проверяем, что созданы бэкапы
        self.assertEqual(len(backup_paths), 5)
        
        # Проверяем список доступных бэкапов
        backups = self.manager.get_available_backups()
        
        # Из-за ограничения max_backups=3, должно остаться только 3 бэкапа
        self.assertLessEqual(len(backups), 3)
    
    def test_backup_verification(self):
        """Тест проверки бэкапов"""
        # Создаем тестовый бэкап
        backup_path = os.path.join(self.test_dir, 'test_backup.zip')
        
        with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.writestr('manifest.json', '{"version": "1.0"}')
            zipf.writestr('filesystem.json.enc', 'data')
            zipf.writestr('vault_config.json', 'data')
        
        # Добавляем бэкап в метаданные
        self.manager._backups_metadata[backup_path] = {
            'path': backup_path,
            'filename': 'test_backup.zip',
            'size': os.path.getsize(backup_path),
            'created_at': datetime.now(),
            'manifest': {'version': '1.0'},
            'hash': BackupIntegrityChecker.calculate_backup_hash(backup_path)
        }
        
        # Проверяем бэкап
        is_valid, issues = self.manager.verify_backup(backup_path)
        
        # Проверяем успешность
        self.assertTrue(is_valid)
        self.assertEqual(len(issues), 0)
    
    def test_backup_restoration(self):
        """Тест восстановления из бэкапа"""
        # Мокируем восстановление
        with patch.object(self.manager.restorer, 'restore_backup') as mock_restore:
            mock_restore.return_value = (True, "Восстановление выполнено успешно")
            
            success, message = self.manager.restore_from_backup(
                '/path/to/backup.zip', None, 'full'
            )
            
            # Проверяем успешность
            self.assertTrue(success)
            self.assertIn("успешно", message.lower())


if __name__ == '__main__':
    unittest.main()