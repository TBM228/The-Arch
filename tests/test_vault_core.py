# tests/test_vault_core.py - ТЕСТЫ ЯДРА ХРАНИЛИЩА
import unittest
import tempfile
import os
import json
import shutil
from unittest.mock import Mock, patch

from vault_core import VaultCore, VaultTransaction, TransactionError
from auth import AuthManager
from crypto import CryptoManager
from folder_security import FolderSecurityManager


class TestVaultCore(unittest.TestCase):
    """Тесты ядра хранилища"""
    
    def setUp(self):
        """Настройка перед каждым тестом"""
        # Создаем временную директорию для тестов
        self.test_dir = tempfile.mkdtemp(prefix='vault_test_')
        
        # Мокируем менеджеры
        self.auth_mock = Mock(spec=AuthManager)
        self.crypto_mock = Mock(spec=CryptoManager)
        self.folder_security_mock = Mock(spec=FolderSecurityManager)
        
        # Настраиваем моки
        self.master_key = b"test_master_key_32_bytes_long!!"
        self.crypto_mock.master_key = self.master_key
        self.crypto_mock.encrypt_with_master_key.return_value = b"encrypted_data"
        self.crypto_mock.decrypt_with_master_key.return_value = json.dumps({
            'files': {},
            'folders': {
                'root': {
                    'id': 'root',
                    'name': 'Корневая папка',
                    'encrypted_name': '0JrQvtGA0L3QtdC10LLQsNC90Y8g0L/QtdC0',
                    'parent': None,
                    'children': [],
                    'created_at': '2024-01-01T00:00:00',
                    'is_locked': False
                }
            }
        }).encode()
        
        self.crypto_mock.encrypt_file.return_value = ('encrypted_file.mya', 'file_id_123')
        self.crypto_mock.calculate_file_hash.return_value = 'test_hash'
        
        self.folder_security_mock.is_folder_unlocked.return_value = True
        self.folder_security_mock.get_folder_key.return_value = None
        
        # Создаем экземпляр VaultCore
        self.vault = VaultCore(
            self.auth_mock,
            self.crypto_mock,
            self.folder_security_mock
        )
        
        # Используем тестовую директорию
        self.vault.filesystem_path = os.path.join(self.test_dir, 'filesystem.json.enc')
    
    def tearDown(self):
        """Очистка после каждого теста"""
        # Удаляем тестовую директорию
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    def test_initialization(self):
        """Тест инициализации"""
        # Проверяем, что корневая папка создана
        self.assertIn('root', self.vault.filesystem['folders'])
        
        # Проверяем структуру файловой системы
        self.assertIn('files', self.vault.filesystem)
        self.assertIn('folders', self.vault.filesystem)
    
    def test_add_file(self):
        """Тест добавления файла"""
        # Создаем тестовый файл
        test_file = os.path.join(self.test_dir, 'test.txt')
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("Test content")
        
        # Добавляем файл
        file_id = self.vault.add_file(test_file)
        
        # Проверяем, что файл добавлен
        self.assertIn(file_id, self.vault.filesystem['files'])
        
        file_data = self.vault.filesystem['files'][file_id]
        self.assertEqual(file_data['original_name'], 'test.txt')
        self.assertEqual(file_data['folder_id'], 'root')
        
        # Проверяем, что файл добавлен в children корневой папки
        self.assertIn(file_id, self.vault.filesystem['folders']['root']['children'])
    
    def test_add_file_to_folder(self):
        """Тест добавления файла в папку"""
        # Создаем тестовую папку
        folder_id = 'test_folder'
        self.vault.filesystem['folders'][folder_id] = {
            'id': folder_id,
            'name': 'Test Folder',
            'encrypted_name': 'VGVzdCBGb2xkZXI=',  # base64
            'parent': 'root',
            'children': [],
            'created_at': '2024-01-01T00:00:00',
            'is_locked': False
        }
        
        # Создаем тестовый файл
        test_file = os.path.join(self.test_dir, 'test.txt')
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("Test content")
        
        # Добавляем файл в папку
        file_id = self.vault.add_file(test_file, folder_id)
        
        # Проверяем, что файл добавлен в папку
        self.assertIn(file_id, self.vault.filesystem['files'])
        self.assertEqual(self.vault.filesystem['files'][file_id]['folder_id'], folder_id)
        
        # Проверяем, что файл добавлен в children папки
        self.assertIn(file_id, self.vault.filesystem['folders'][folder_id]['children'])
    
    def test_extract_file(self):
        """Тест извлечения файла"""
        # Создаем тестовый файл
        test_file = os.path.join(self.test_dir, 'source.txt')
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("Test content for extraction")
        
        # Мокируем шифрование и дешифрование
        encrypted_file = os.path.join(self.test_dir, 'encrypted.mya')
        with open(encrypted_file, 'wb') as f:
            f.write(b"encrypted_data")
        
        self.crypto_mock.encrypt_file.return_value = (encrypted_file, 'test_file_id')
        self.crypto_mock.decrypt_file.side_effect = lambda src, dst, key: shutil.copy(test_file, dst)
        
        # Добавляем файл
        file_id = self.vault.add_file(test_file)
        
        # Извлекаем файл
        output_dir = os.path.join(self.test_dir, 'output')
        os.makedirs(output_dir, exist_ok=True)
        
        extracted_path = self.vault.extract_file(file_id, output_dir)
        
        # Проверяем, что файл извлечен
        self.assertTrue(os.path.exists(extracted_path))
        
        # Проверяем содержимое
        with open(extracted_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        self.assertEqual(content, "Test content for extraction")
    
    def test_transaction_success(self):
        """Тест успешной транзакции"""
        # Создаем тестовые файлы
        test_files = []
        for i in range(3):
            test_file = os.path.join(self.test_dir, f'test_{i}.txt')
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write(f"Test content {i}")
            test_files.append(test_file)
        
        # Создаем транзакцию
        with self.vault.begin_transaction("test transaction") as tx:
            # Добавляем файлы в транзакцию
            for test_file in test_files:
                tx.add_file(test_file)
        
        # Проверяем, что все файлы добавлены
        self.assertEqual(len(self.vault.filesystem['files']), 3)
        self.assertEqual(len(self.vault.filesystem['folders']['root']['children']), 3)
    
    def test_transaction_rollback(self):
        """Тест отката транзакции"""
        # Сохраняем начальное состояние
        initial_file_count = len(self.vault.filesystem['files'])
        
        # Создаем тестовый файл
        test_file = os.path.join(self.test_dir, 'test.txt')
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("Test content")
        
        try:
            # Создаем транзакцию с ошибкой
            with self.vault.begin_transaction("failing transaction") as tx:
                # Добавляем файл
                tx.add_file(test_file)
                
                # Имитируем ошибку
                raise ValueError("Simulated error")
        
        except TransactionError:
            pass
        
        # Проверяем, что состояние откатилось
        self.assertEqual(len(self.vault.filesystem['files']), initial_file_count)
    
    def test_concurrent_access(self):
        """Тест конкурентного доступа"""
        import threading
        
        # Создаем тестовые файлы
        test_files = []
        for i in range(10):
            test_file = os.path.join(self.test_dir, f'test_{i}.txt')
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write(f"Test content {i}")
            test_files.append(test_file)
        
        # Функция для добавления файлов в потоке
        def add_files(file_list):
            for test_file in file_list:
                try:
                    self.vault.add_file(test_file)
                except Exception as e:
                    print(f"Error in thread: {e}")
        
        # Создаем и запускаем потоки
        threads = []
        chunk_size = 2
        for i in range(0, len(test_files), chunk_size):
            chunk = test_files[i:i + chunk_size]
            thread = threading.Thread(target=add_files, args=(chunk,))
            threads.append(thread)
            thread.start()
        
        # Ждем завершения всех потоков
        for thread in threads:
            thread.join()
        
        # Проверяем, что все файлы добавлены
        self.assertEqual(len(self.vault.filesystem['files']), len(test_files))
    
    def test_filesystem_backup(self):
        """Тест резервного копирования файловой системы"""
        # Создаем тестовый файл
        test_file = os.path.join(self.test_dir, 'test.txt')
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("Test content")
        
        # Добавляем файл
        self.vault.add_file(test_file)
        
        # Сохраняем файловую систему
        self.vault._save_filesystem()
        
        # Проверяем, что файл создан
        self.assertTrue(os.path.exists(self.vault.filesystem_path))
        
        # Проверяем, что создан бэкап
        backup_dir = 'data/backups'
        if os.path.exists(backup_dir):
            backups = [f for f in os.listdir(backup_dir) if f.startswith('filesystem_backup_')]
            self.assertGreater(len(backups), 0)
    
    def test_integrity_check(self):
        """Тест проверки целостности"""
        # Создаем тестовый файл
        test_file = os.path.join(self.test_dir, 'test.txt')
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("Test content")
        
        # Добавляем файл
        file_id = self.vault.add_file(test_file)
        
        # Проверяем целостность
        issues = self.vault.verify_integrity()
        
        # Не должно быть проблем
        self.assertEqual(len(issues), 0)
    
    def test_corrupted_filesystem_recovery(self):
        """Тест восстановления из поврежденной файловой системы"""
        # Сохраняем текущую файловую систему
        self.vault._save_filesystem()
        
        # Создаем поврежденный файл
        with open(self.vault.filesystem_path, 'wb') as f:
            f.write(b"corrupted data")
        
        # Загружаем файловую систему (должна восстановиться)
        self.vault._load_filesystem()
        
        # Проверяем, что файловая система загружена
        self.assertIn('root', self.vault.filesystem['folders'])


class TestVaultTransaction(unittest.TestCase):
    """Тесты транзакций"""
    
    def setUp(self):
        """Настройка перед каждым тестом"""
        self.vault_mock = Mock(spec=VaultCore)
        self.vault_mock.filesystem = {'files': {}, 'folders': {'root': {'children': []}}}
    
    def test_transaction_commit(self):
        """Тест коммита транзакции"""
        transaction = VaultTransaction(self.vault_mock, "test")
        
        # Добавляем операцию
        transaction.add_file("/path/to/file.txt", "root")
        
        # Мокируем выполнение
        self.vault_mock._transactional_add_file.return_value = "file_id_123"
        
        # Коммитим
        results = transaction.commit()
        
        # Проверяем, что операция выполнена
        self.assertIn("add_file_", list(results.keys())[0])
        self.assertEqual(results[list(results.keys())[0]], "file_id_123")
        
        # Проверяем, что состояние транзакции изменилось
        self.assertEqual(transaction._state, 'committed')
    
    def test_transaction_rollback_on_error(self):
        """Тест отката транзакции при ошибке"""
        transaction = VaultTransaction(self.vault_mock, "test")
        
        # Добавляем операцию
        transaction.add_file("/path/to/file.txt", "root")
        
        # Мокируем ошибку
        self.vault_mock._transactional_add_file.side_effect = ValueError("Test error")
        
        # Пытаемся коммитить
        with self.assertRaises(TransactionError):
            transaction.commit()
        
        # Проверяем, что состояние транзакции - failed
        self.assertEqual(transaction._state, 'failed')
    
    def test_transaction_context_manager(self):
        """Тест контекстного менеджера транзакции"""
        with patch.object(VaultTransaction, 'commit') as mock_commit:
            with VaultTransaction(self.vault_mock, "test") as tx:
                tx.add_file("/path/to/file.txt", "root")
            
            # Проверяем, что commit был вызван
            mock_commit.assert_called_once()
    
    def test_transaction_context_manager_with_exception(self):
        """Тест контекстного менеджера с исключением"""
        with patch.object(VaultTransaction, '_rollback') as mock_rollback:
            try:
                with VaultTransaction(self.vault_mock, "test") as tx:
                    tx.add_file("/path/to/file.txt", "root")
                    raise ValueError("Test exception")
            except ValueError:
                pass
            
            # Проверяем, что rollback был вызван
            mock_rollback.assert_called_once()


if __name__ == '__main__':
    unittest.main()