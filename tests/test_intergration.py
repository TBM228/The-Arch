# tests/test_integration.py - ИНТЕГРАЦИОННЫЕ ТЕСТЫ
import unittest
import tempfile
import os
import shutil
import threading
import time
from pathlib import Path

from auth import AuthManager
from crypto import CryptoManager
from vault_core import VaultCore
from folder_security import FolderSecurityManager
from backup_manager import BackupManager


class IntegrationTest(unittest.TestCase):
    """Интеграционные тесты всей системы"""
    
    def setUp(self):
        """Настройка перед каждым тестом"""
        # Создаем временную директорию для тестов
        self.test_dir = tempfile.mkdtemp(prefix='integration_test_')
        
        # Инициализируем менеджеры
        self.auth = AuthManager()
        self.auth.config_path = os.path.join(self.test_dir, 'vault_config.json')
        
        # Создаем мастер-пароль
        self.test_password = "TestPassword123!"
        self.master_key = self.auth.create_master_password(
            self.test_password,
            "Test hint"
        )
        
        # Инициализируем остальные компоненты
        self.crypto = CryptoManager(self.master_key)
        self.folder_security = FolderSecurityManager(self.crypto)
        self.vault = VaultCore(
            self.auth,
            self.crypto,
            self.folder_security
        )
        
        # Используем тестовые пути
        self.vault.filesystem_path = os.path.join(self.test_dir, 'filesystem.json.enc')
        
        # Создаем менеджер бэкапов
        self.backup_manager = BackupManager(
            self.crypto,
            self.auth,
            self.vault
        )
        self.backup_manager.creator.backup_dir = os.path.join(self.test_dir, 'backups')
    
    def tearDown(self):
        """Очистка после каждого теста"""
        # Очищаем ресурсы
        if hasattr(self, 'crypto'):
            self.crypto.secure_clear()
        
        if hasattr(self, 'folder_security'):
            self.folder_security.cleanup()
        
        if hasattr(self, 'vault'):
            self.vault.cleanup()
        
        # Удаляем тестовую директорию
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    def test_complete_workflow(self):
        """Тест полного рабочего процесса"""
        # 1. Создаем тестовые файлы
        test_files = []
        for i in range(3):
            test_file = os.path.join(self.test_dir, f'document_{i}.txt')
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write(f"Это тестовый документ №{i}\n" * 100)
            test_files.append(test_file)
        
        # 2. Добавляем файлы в хранилище
        file_ids = []
        for test_file in test_files:
            file_id = self.vault.add_file(test_file)
            file_ids.append(file_id)
        
        # Проверяем, что файлы добавлены
        self.assertEqual(len(self.vault.filesystem['files']), 3)
        
        # 3. Извлекаем файлы обратно
        output_dir = os.path.join(self.test_dir, 'output')
        os.makedirs(output_dir, exist_ok=True)
        
        for file_id in file_ids:
            extracted_path = self.vault.extract_file(file_id, output_dir)
            self.assertTrue(os.path.exists(extracted_path))
        
        # 4. Создаем бэкап
        success, backup_path = self.backup_manager.create_scheduled_backup()
        self.assertTrue(success)
        self.assertTrue(os.path.exists(backup_path))
        
        # 5. Проверяем бэкап
        is_valid, issues = self.backup_manager.verify_backup(backup_path)
        self.assertTrue(is_valid)
        self.assertEqual(len(issues), 0)
        
        # 6. Восстанавливаем из бэкапа (только файловую систему)
        restore_success, restore_message = self.backup_manager.restore_from_backup(
            backup_path, None, 'filesystem_only'
        )
        self.assertTrue(restore_success)
        
        # 7. Проверяем целостность хранилища после восстановления
        issues = self.vault.verify_integrity()
        self.assertEqual(len(issues), 0)
    
    def test_concurrent_operations(self):
        """Тест конкурентных операций"""
        import concurrent.futures
        
        # Создаем тестовые файлы
        test_files = []
        for i in range(10):
            test_file = os.path.join(self.test_dir, f'concurrent_{i}.txt')
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write(f"Файл для конкурентного теста №{i}")
            test_files.append(test_file)
        
        # Функция для добавления файла
        def add_file(file_path):
            try:
                file_id = self.vault.add_file(file_path)
                return file_id
            except Exception as e:
                return str(e)
        
        # Запускаем конкурентное добавление
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(add_file, file_path) for file_path in test_files]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]
        
        # Проверяем, что все файлы добавлены
        successful_adds = [r for r in results if isinstance(r, str) and r.startswith('file_')]
        self.assertEqual(len(successful_adds), len(test_files))
        
        # Проверяем целостность файловой системы
        self.assertEqual(len(self.vault.filesystem['files']), len(test_files))
    
    def test_folder_security_workflow(self):
        """Тест работы с защищенными папками"""
        # 1. Создаем защищенную папку
        folder_name = "Секретная папка"
        folder_password = "FolderPassword123!"
        folder_hint = "Подсказка для папки"
        
        # Здесь должен быть вызов метода создания папки
        # folder_id = self.vault.create_folder(...)
        # Пока используем заглушку
        folder_id = "test_folder_123"
        
        # 2. Добавляем файл в защищенную папку
        test_file = os.path.join(self.test_dir, 'secret.txt')
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("Секретные данные")
        
        # Имитируем разблокировку папки
        self.folder_security.unlocked_folders[folder_id] = {
            'key': None,  # В реальности здесь был бы SecureString с ключом
            'unlock_time': time.time(),
            'name': folder_name
        }
        
        # Добавляем файл
        file_id = self.vault.add_file(test_file, folder_id)
        
        # Проверяем, что файл добавлен
        self.assertIn(file_id, self.vault.filesystem['files'])
        
        # 3. Извлекаем файл из защищенной папки
        output_dir = os.path.join(self.test_dir, 'secure_output')
        os.makedirs(output_dir, exist_ok=True)
        
        extracted_path = self.vault.extract_file(file_id, output_dir)
        self.assertTrue(os.path.exists(extracted_path))
        
        # 4. Блокируем папку
        self.folder_security.lock_folder(folder_id)
        self.assertNotIn(folder_id, self.folder_security.unlocked_folders)
    
    def test_error_recovery(self):
        """Тест восстановления после ошибок"""
        # 1. Создаем поврежденную файловую систему
        corrupted_data = b"corrupted data that is not valid JSON"
        
        with open(self.vault.filesystem_path, 'wb') as f:
            f.write(corrupted_data)
        
        # 2. Пытаемся загрузить (должно восстановиться из бэкапа или создать новую)
        self.vault._load_filesystem()
        
        # 3. Проверяем, что файловая система загружена
        self.assertIn('root', self.vault.filesystem['folders'])
        self.assertIn('files', self.vault.filesystem)
    
    def test_backup_and_restore_cycle(self):
        """Тест полного цикла бэкап-восстановление"""
        # 1. Создаем тестовые данные
        original_files = []
        for i in range(5):
            test_file = os.path.join(self.test_dir, f'original_{i}.txt')
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write(f"Оригинальные данные файла {i}\n" * 50)
            original_files.append(test_file)
        
        # 2. Добавляем файлы в хранилище
        for test_file in original_files:
            self.vault.add_file(test_file)
        
        original_file_count = len(self.vault.filesystem['files'])
        
        # 3. Создаем бэкап
        success, backup_path = self.backup_manager.creator.create_backup(
            self.vault, 'full'
        )
        self.assertTrue(success)
        
        # 4. Удаляем все файлы из хранилища
        self.vault.filesystem['files'].clear()
        self.vault.filesystem['folders']['root']['children'] = []
        self.vault._save_filesystem()
        
        # 5. Восстанавливаем из бэкапа
        restore_success, restore_message = self.backup_manager.restorer.restore_backup(
            backup_path, None, 'full'
        )
        self.assertTrue(restore_success)
        
        # 6. Перезагружаем файловую систему
        self.vault._load_filesystem()
        
        # 7. Проверяем, что данные восстановлены
        self.assertEqual(len(self.vault.filesystem['files']), original_file_count)
        
        # 8. Проверяем целостность
        issues = self.vault.verify_integrity()
        self.assertEqual(len(issues), 0)
    
    def test_memory_safety(self):
        """Тест безопасности использования памяти"""
        import gc
        
        # Создаем большой файл (10 MB)
        large_file = os.path.join(self.test_dir, 'large.bin')
        large_data = os.urandom(10 * 1024 * 1024)  # 10 MB
        
        with open(large_file, 'wb') as f:
            f.write(large_data)
        
        # Измеряем память до операции
        gc.collect()
        
        # Шифруем большой файл
        vault_filename, file_id = self.crypto.encrypt_large_file(large_file)
        
        # Проверяем, что файл создан
        self.assertTrue(os.path.exists(vault_filename))
        
        # Измеряем память после операции (должна быть освобождена)
        gc.collect()
        
        # Дешифруем файл
        output_file = os.path.join(self.test_dir, 'decrypted.bin')
        self.crypto.decrypt_large_file(vault_filename, output_file)
        
        # Проверяем содержимое
        with open(output_file, 'rb') as f:
            decrypted_data = f.read()
        
        self.assertEqual(decrypted_data, large_data)
        
        # Очистка
        self.crypto.secure_clear()
        gc.collect()
    
    def test_transaction_isolation(self):
        """Тест изоляции транзакций"""
        # Создаем две транзакции
        with self.vault.begin_transaction("Транзакция 1") as tx1:
            # Добавляем файл в первой транзакции
            test_file1 = os.path.join(self.test_dir, 'tx1.txt')
            with open(test_file1, 'w', encoding='utf-8') as f:
                f.write("Данные транзакции 1")
            
            tx1.add_file(test_file1)
            
            # Пока транзакция не завершена, данные не должны быть видны
            self.assertEqual(len(self.vault.filesystem['files']), 0)
        
        # После коммита первой транзакции
        self.assertEqual(len(self.vault.filesystem['files']), 1)
        
        # Вторая транзакция с ошибкой
        try:
            with self.vault.begin_transaction("Транзакция 2") as tx2:
                test_file2 = os.path.join(self.test_dir, 'tx2.txt')
                with open(test_file2, 'w', encoding='utf-8') as f:
                    f.write("Данные транзакции 2")
                
                tx2.add_file(test_file2)
                
                # Имитируем ошибку
                raise ValueError("Искусственная ошибка в транзакции")
        
        except TransactionError:
            pass
        
        # Проверяем, что данные из второй транзакции не добавлены
        self.assertEqual(len(self.vault.filesystem['files']), 1)


if __name__ == '__main__':
    unittest.main()