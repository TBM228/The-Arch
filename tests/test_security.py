# tests/test_security.py - ТЕСТЫ БЕЗОПАСНОСТИ
import unittest
import tempfile
import os
import json
import base64
from unittest.mock import Mock, patch

from auth import AuthManager
from crypto import CryptoManager
from securestring import SecureString


class TestSecureString(unittest.TestCase):
    """Тесты безопасных строк"""
    
    def test_secure_string_storage(self):
        """Тест хранения строк"""
        test_data = "super_secret_password_123"
        secure_str = SecureString(test_data)
        
        # Проверяем, что данные доступны
        retrieved = secure_str.retrieve_string()
        self.assertEqual(retrieved, test_data)
        
        # Проверяем безопасное удаление
        secure_str.secure_clear()
        self.assertEqual(len(secure_str), 0)
    
    def test_secure_clear_on_del(self):
        """Тест автоматической очистки"""
        test_data = "test_data"
        
        with patch.object(SecureString, 'secure_clear') as mock_clear:
            secure_str = SecureString(test_data)
            del secure_str
            
            # Проверяем, что secure_clear был вызван
            mock_clear.assert_called_once()
    
    def test_secure_string_bytes(self):
        """Тест хранения байтов"""
        test_data = b"binary_data\x00\x01\x02"
        secure_str = SecureString(test_data)
        
        retrieved = secure_str.retrieve()
        self.assertEqual(retrieved, test_data)


class TestCryptoManager(unittest.TestCase):
    """Тесты менеджера шифрования"""
    
    def setUp(self):
        """Настройка перед каждым тестом"""
        self.master_key = b"test_master_key_32_bytes_long!!"
        self.crypto = CryptoManager(self.master_key)
        self.test_data = b"Hello, this is a secret message!"
    
    def tearDown(self):
        """Очистка после каждого теста"""
        self.crypto.secure_clear()
    
    def test_encrypt_decrypt(self):
        """Тест шифрования и дешифрования"""
        # Шифруем
        encrypted = self.crypto.encrypt_data(self.test_data)
        
        # Проверяем, что данные изменились
        self.assertNotEqual(encrypted, self.test_data)
        
        # Дешифруем
        decrypted = self.crypto.decrypt_data(encrypted)
        
        # Проверяем, что получили исходные данные
        self.assertEqual(decrypted, self.test_data)
    
    def test_encrypt_with_different_keys(self):
        """Тест шифрования разными ключами"""
        key1 = b"first_key_32_bytes_long!!!!!!"
        key2 = b"second_key_32_bytes_long!!!"
        
        encrypted_with_key1 = self.crypto.encrypt_data(self.test_data, key1)
        encrypted_with_key2 = self.crypto.encrypt_data(self.test_data, key2)
        
        # Данные, зашифрованные разными ключами, должны быть разными
        self.assertNotEqual(encrypted_with_key1, encrypted_with_key2)
    
    def test_secure_clear(self):
        """Тест безопасной очистки"""
        self.crypto.secure_clear()
        
        # После очистки нельзя использовать криптоменеджер
        with self.assertRaises(Exception):
            self.crypto.encrypt_data(self.test_data)
    
    def test_file_encryption(self):
        """Тест шифрования файла"""
        with tempfile.NamedTemporaryFile(mode='wb', delete=False) as f:
            f.write(self.test_data)
            temp_file = f.name
        
        try:
            # Шифруем файл
            vault_filename, file_id = self.crypto.encrypt_file(temp_file)
            
            # Проверяем, что файл создан
            self.assertTrue(os.path.exists(vault_filename))
            
            # Дешифруем файл
            output_file = temp_file + ".decrypted"
            self.crypto.decrypt_file(vault_filename, output_file)
            
            # Проверяем содержимое
            with open(output_file, 'rb') as f:
                decrypted_data = f.read()
            
            self.assertEqual(decrypted_data, self.test_data)
            
            # Очистка
            os.unlink(vault_filename)
            os.unlink(output_file)
            
        finally:
            os.unlink(temp_file)
    
    def test_large_file_encryption(self):
        """Тест шифрования большого файла"""
        # Создаем большой файл (5 MB)
        large_data = os.urandom(5 * 1024 * 1024)
        
        with tempfile.NamedTemporaryFile(mode='wb', delete=False) as f:
            f.write(large_data)
            temp_file = f.name
        
        try:
            # Шифруем файл
            vault_filename, file_id = self.crypto.encrypt_large_file(temp_file)
            
            # Проверяем, что файл создан
            self.assertTrue(os.path.exists(vault_filename))
            
            # Проверяем размер
            encrypted_size = os.path.getsize(vault_filename)
            self.assertGreater(encrypted_size, len(large_data))
            
            # Дешифруем файл
            output_file = temp_file + ".decrypted"
            self.crypto.decrypt_large_file(vault_filename, output_file)
            
            # Проверяем содержимое
            with open(output_file, 'rb') as f:
                decrypted_data = f.read()
            
            self.assertEqual(decrypted_data, large_data)
            
            # Очистка
            os.unlink(vault_filename)
            os.unlink(output_file)
            
        finally:
            os.unlink(temp_file)


class TestAuthManager(unittest.TestCase):
    """Тесты менеджера аутентификации"""
    
    def setUp(self):
        """Настройка перед каждым тестом"""
        self.auth = AuthManager()
        self.test_password = "TestPassword123!"
        self.test_hint = "My favorite color"
        
        # Используем временный файл конфигурации
        self.temp_config = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        self.auth.config_path = self.temp_config.name
    
    def tearDown(self):
        """Очистка после каждого теста"""
        if os.path.exists(self.temp_config.name):
            os.unlink(self.temp_config.name)
    
    def test_first_run_detection(self):
        """Тест определения первого запуска"""
        self.assertTrue(self.auth.is_first_run())
    
    def test_create_master_password(self):
        """Тест создания мастер-пароля"""
        master_key = self.auth.create_master_password(
            self.test_password,
            self.test_hint
        )
        
        # Проверяем, что конфигурация создана
        self.assertFalse(self.auth.is_first_run())
        
        # Проверяем, что ключ возвращен
        self.assertIsNotNone(master_key)
        self.assertEqual(len(master_key), 44)  # Длина Fernet ключа в base64
    
    def test_verify_master_password(self):
        """Тест проверки пароля"""
        # Создаем пароль
        self.auth.create_master_password(self.test_password, self.test_hint)
        
        # Проверяем правильный пароль
        self.assertTrue(self.auth.verify_master_password(self.test_password))
        
        # Проверяем неправильный пароль
        self.assertFalse(self.auth.verify_master_password("WrongPassword123!"))
    
    def test_get_master_key(self):
        """Тест получения мастер-ключа"""
        # Создаем пароль
        created_key = self.auth.create_master_password(self.test_password, self.test_hint)
        
        # Получаем ключ
        retrieved_key = self.auth.get_master_key(self.test_password)
        
        # Проверяем, что ключи совпадают
        self.assertEqual(created_key, retrieved_key)
    
    def test_password_validation(self):
        """Тест валидации пароля"""
        # Слишком короткий пароль
        result = self.auth._validate_password_strength("Short1!")
        self.assertFalse(result['valid'])
        
        # Пароль без цифр
        result = self.auth._validate_password_strength("NoDigitsHere!")
        self.assertFalse(result['valid'])
        
        # Пароль без заглавных букв
        result = self.auth._validate_password_strength("nocapital123!")
        self.assertFalse(result['valid'])
        
        # Хороший пароль
        good_password = "GoodPassword123!"
        result = self.auth._validate_password_strength(good_password)
        self.assertTrue(result['valid'])
    
    def test_recovery_questions(self):
        """Тест вопросов восстановления"""
        # Создаем пароль
        self.auth.create_master_password(self.test_password, self.test_hint)
        
        # Настраиваем вопросы восстановления
        recovery_questions = [
            ("Ваш любимый цвет?", "синий"),
            ("Имя первого питомца?", "барсик"),
            ("Девичья фамилия матери?", "иванова")
        ]
        
        self.auth.setup_recovery_questions(self.test_password, recovery_questions)
        
        # Проверяем ответы
        answers = ["синий", "барсик", "иванова"]
        self.assertTrue(self.auth.verify_recovery_answers(
            list(zip([q[0] for q in recovery_questions], answers))
        ))
        
        # Проверяем неверные ответы
        wrong_answers = ["красный", "мурзик", "петрова"]
        self.assertFalse(self.auth.verify_recovery_answers(
            list(zip([q[0] for q in recovery_questions], wrong_answers))
        ))
    
    def test_change_master_password(self):
        """Тест смены пароля"""
        # Создаем первоначальный пароль
        old_key = self.auth.create_master_password(self.test_password, self.test_hint)
        
        # Меняем пароль
        new_password = "NewPassword456!"
        new_key = self.auth.change_master_password(self.test_password, new_password, "Новая подсказка")
        
        # Проверяем, что ключ остался тем же
        self.assertEqual(old_key, new_key)
        
        # Проверяем, что старый пароль не работает
        self.assertFalse(self.auth.verify_master_password(self.test_password))
        
        # Проверяем, что новый пароль работает
        self.assertTrue(self.auth.verify_master_password(new_password))


class TestRateLimiting(unittest.TestCase):
    """Тесты rate limiting"""
    
    def test_recovery_protection(self):
        """Тест защиты восстановления"""
        from auth import RecoveryProtection
        
        protection = RecoveryProtection()
        user_id = "test_user"
        
        # Первые 2 попытки должны проходить
        protection.record_attempt(user_id)
        self.assertFalse(protection.is_locked_out(user_id))
        
        protection.record_attempt(user_id)
        self.assertFalse(protection.is_locked_out(user_id))
        
        # 3-я попытка должна заблокировать
        protection.record_attempt(user_id)
        self.assertTrue(protection.is_locked_out(user_id))
        
        # Проверяем оставшееся время
        remaining = protection.get_remaining_time(user_id)
        self.assertGreater(remaining, 0)
        self.assertLessEqual(remaining, 600)  # Максимум 10 минут


if __name__ == '__main__':
    unittest.main()