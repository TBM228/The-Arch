# auth.py - УЛУЧШЕННАЯ ЗАЩИТА ВОССТАНОВЛЕНИЯ
import re
import os
import json
import bcrypt
import base64
import logging
import hashlib
import secrets
import time
import threading
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend


class RecoveryProtection:
    """Защита механизма восстановления"""
    
    def __init__(self):
        self.failed_attempts = {}
        self.max_attempts = 3
        self.lockout_time = 600  # 10 минут
        self.base_delay = 1
        self._lock = threading.RLock()
    
    def record_attempt(self, user_id):
        """Запись попытки восстановления"""
        with self._lock:
            if user_id not in self.failed_attempts:
                self.failed_attempts[user_id] = []
            
            self.failed_attempts[user_id].append(time.time())
            
            # Ограничиваем историю
            if len(self.failed_attempts[user_id]) > self.max_attempts * 2:
                self.failed_attempts[user_id] = self.failed_attempts[user_id][-self.max_attempts:]
    
    def is_locked_out(self, user_id):
        """Проверка блокировки"""
        with self._lock:
            if user_id not in self.failed_attempts:
                return False
            
            attempts = self.failed_attempts[user_id]
            recent_attempts = [t for t in attempts if time.time() - t < self.lockout_time]
            
            if len(recent_attempts) >= self.max_attempts:
                return True
            
            return False
    
    def get_remaining_time(self, user_id):
        """Оставшееся время блокировки"""
        with self._lock:
            if user_id not in self.failed_attempts:
                return 0
            
            attempts = self.failed_attempts[user_id]
            if not attempts:
                return 0
            
            oldest_recent_attempt = min(attempts)
            elapsed = time.time() - oldest_recent_attempt
            remaining = self.lockout_time - elapsed
            
            return max(0, int(remaining))
    
    def clear_attempts(self, user_id):
        """Очистка истории попыток"""
        with self._lock:
            if user_id in self.failed_attempts:
                del self.failed_attempts[user_id]


class SecureAuthManager:
    def __init__(self, config_path='data/vault_config.json'):
        self.config_path = config_path
        self.config = self._load_config()
        self._password_regex_cache = None
        self._kdf_iterations = 300000
        self._recovery_protection = RecoveryProtection()
        self._lock = threading.RLock()
        
        self._init_regex_cache()
    
    def _load_config(self):
        """Загрузка конфигурации из файла"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logging.error(f"Ошибка загрузки конфигурации: {e}")
                return {}
        return {}
    
    def _save_config(self):
        """Сохранение конфигурации в файл"""
        with self._lock:
            try:
                os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
                
                # Создаем временный файл для атомарной записи
                temp_path = self.config_path + '.tmp'
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(self.config, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                
                # Атомарная замена
                os.replace(temp_path, self.config_path)
                
            except Exception as e:
                logging.error(f"Ошибка сохранения конфигурации: {e}")
                # Удаляем временный файл при ошибке
                try:
                    os.unlink(temp_path)
                except:
                    pass
                raise
    
    def _init_regex_cache(self):
        """Инициализация кэша компилированных regex"""
        self._password_regex_cache = {
            'length': lambda p: len(p) >= 12,
            'uppercase': re.compile(r'[A-Z]').search,
            'lowercase': re.compile(r'[a-z]').search,
            'digit': re.compile(r'\d').search,
            'special': re.compile(r'[!@#$%^&*(),.?":{}|<>]').search,
            'latin_only': re.compile(r'^[A-Za-z0-9!@#$%^&*(),.?":{}|<>]+$').match,
            'common_patterns': self._check_common_patterns
        }
    
    def _check_common_patterns(self, password):
        """Проверка на распространенные слабые паттерны"""
        common_patterns = [
            r'12345678',
            r'password',
            r'qwerty',
            r'admin',
            r'welcome',
            r'(.)\1{3,}',  # Повторяющиеся символы
            r'(0123|1234|2345|3456|4567|5678|6789|7890)',  # Последовательности
        ]
        
        password_lower = password.lower()
        for pattern in common_patterns:
            if re.search(pattern, password_lower):
                return False
        return True
    
    def is_first_run(self):
        """Проверка первого запуска"""
        return 'master_password_hash' not in self.config
    
    def create_master_password(self, password, password_hint="", recovery_questions=None):
        """Создание мастер-пароля с улучшенной безопасностью"""
        validation_result = self._validate_password_strength(password)
        if not validation_result['valid']:
            raise ValueError(validation_result['message'])
        
        # Генерируем основной мастер-ключ
        master_key = Fernet.generate_key()
        
        # Генерируем 2 ключа-шифровальщика
        master_password_encoder_key = Fernet.generate_key()
        recovery_encoder_key = Fernet.generate_key()
        
        # Шифруем мастер-ключ двумя разными способами
        master_password_fernet = Fernet(master_password_encoder_key)
        recovery_fernet = Fernet(recovery_encoder_key)
        
        encrypted_master_key = master_password_fernet.encrypt(master_key)
        encrypted_recovery_key = recovery_fernet.encrypt(master_key)
        
        # Шифруем ключи-шифровальщика с улучшенной безопасностью
        encrypted_master_password_encoder = self._encrypt_with_password(
            master_password_encoder_key, password
        )
        encrypted_recovery_encoder = self._encrypt_with_questions(
            recovery_encoder_key, recovery_questions or []
        )
        
        # Сохраняем хеш пароля
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        
        # Сохраняем вопросы восстановления с улучшенной безопасностью
        encrypted_recovery_answers = []
        for question, answer in (recovery_questions or []):
            # Добавляем соль для каждого ответа
            answer_salt = secrets.token_bytes(16)
            answer_with_salt = answer.encode() + answer_salt
            answer_hash = bcrypt.hashpw(answer_with_salt, bcrypt.gensalt()).decode()
            encrypted_recovery_answers.append({
                'question': question, 
                'answer_hash': answer_hash,
                'salt': base64.b64encode(answer_salt).decode()
            })
        
        # Сохраняем конфигурацию
        self.config = {
            'master_password_hash': password_hash,
            'encrypted_master_key': base64.b64encode(encrypted_master_key).decode(),
            'encrypted_recovery_key': base64.b64encode(encrypted_recovery_key).decode(),
            'encrypted_master_password_encoder': base64.b64encode(encrypted_master_password_encoder).decode(),
            'encrypted_recovery_encoder': base64.b64encode(encrypted_recovery_encoder).decode(),
            'created_at': self._get_timestamp(),
            'password_hint': password_hint,
            'recovery_questions': encrypted_recovery_answers,
            'security_version': '2.0',
            'user_id': secrets.token_hex(16)  # Уникальный ID пользователя
        }
        
        self._save_config()
        return master_key
    
    def _encrypt_with_password(self, data, password):
        """Улучшенное шифрование с помощью пароля"""
        salt = secrets.token_bytes(32)
        key = self._derive_key_from_password(password, salt)
        fernet = Fernet(key)
        
        encrypted_data = fernet.encrypt(data)
        return salt + encrypted_data
    
    def _encrypt_with_questions(self, data, recovery_questions):
        """Улучшенное шифрование с помощью вопросов восстановления"""
        if not recovery_questions:
            return secrets.token_bytes(32) + b'NO_RECOVERY_SETUP'
        
        # Используем HMAC для создания более надежного ключа
        answers_string = ''.join([answer for _, answer in recovery_questions])
        master_salt = secrets.token_bytes(32)
        
        # Создаем производный ключ из всех ответов
        derived_key = self._derive_strong_recovery_key(answers_string, master_salt)
        fernet = Fernet(derived_key)
        
        encrypted_data = fernet.encrypt(data)
        return master_salt + encrypted_data
    
    def _derive_strong_recovery_key(self, answers_string, salt):
        """Создание усиленного ключа восстановления"""
        # Дополнительный хеш для увеличения энтропии
        answers_hash = hashlib.sha384(answers_string.encode()).digest()
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA512(),
            length=32,
            salt=salt,
            iterations=self._kdf_iterations,
            backend=default_backend()
        )
        key = base64.urlsafe_b64encode(kdf.derive(answers_hash))
        return key
    
    def _derive_key_from_password(self, password, salt):
        """Производный ключ из пароля"""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=self._kdf_iterations,
            backend=default_backend()
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return key
    
    def verify_master_password(self, password):
        """Быстрая проверка мастер-пароля"""
        if self.is_first_run():
            raise RuntimeError("Сначала создайте мастер-пароль")
        
        try:
            stored_hash = self.config['master_password_hash'].encode()
            return bcrypt.checkpw(password.encode(), stored_hash)
        except Exception as e:
            logging.error(f"Ошибка проверки пароля: {e}")
            return False
    
    def get_master_key(self, password):
        """Получение мастер-ключа через пароль"""
        if not self.verify_master_password(password):
            raise ValueError("Неверный мастер-пароль")
        
        try:
            # Дешифруем ключ-шифровальщик с помощью пароля
            encrypted_master_password_encoder = base64.b64decode(
                self.config['encrypted_master_password_encoder']
            )
            
            # Извлекаем соль и зашифрованные данные
            salt = encrypted_master_password_encoder[:32]
            encrypted_data = encrypted_master_password_encoder[32:]
            
            # Восстанавливаем ключ из пароля
            key = self._derive_key_from_password(password, salt)
            fernet = Fernet(key)
            master_password_encoder_key = fernet.decrypt(encrypted_data)
            
            # Дешифруем мастер-ключ
            encrypted_master_key = base64.b64decode(self.config['encrypted_master_key'])
            master_password_fernet = Fernet(master_password_encoder_key)
            master_key = master_password_fernet.decrypt(encrypted_master_key)
            
            return master_key
            
        except Exception as e:
            logging.error(f"Ошибка получения мастер-ключа: {e}")
            # Унифицированное сообщение об ошибке
            raise ValueError("Неверный пароль или повреждены данные")
    
    def recover_master_key(self, answers):
        """Улучшенное восстановление мастер-ключа"""
        user_id = self.config.get('user_id', 'default')
        
        # Проверяем блокировку
        if self._recovery_protection.is_locked_out(user_id):
            remaining_time = self._recovery_protection.get_remaining_time(user_id)
            raise PermissionError(f"Восстановление заблокировано. Попробуйте через {remaining_time} секунд")
        
        start_time = time.time()
        
        try:
            encrypted_recovery_encoder = base64.b64decode(
                self.config['encrypted_recovery_encoder']
            )
            
            if b'NO_RECOVERY_SETUP' in encrypted_recovery_encoder:
                self._recovery_protection.record_attempt(user_id)
                raise ValueError("Восстановление через вопросы не настроено")
            
            salt = encrypted_recovery_encoder[:32]
            encrypted_data = encrypted_recovery_encoder[32:]
            
            # Создаем усиленный ключ из ответов
            answers_string = ''.join(answers)
            key = self._derive_strong_recovery_key(answers_string, salt)
            fernet = Fernet(key)
            recovery_encoder_key = fernet.decrypt(encrypted_data)
            
            # Дешифруем мастер-ключ
            encrypted_recovery_key = base64.b64decode(self.config['encrypted_recovery_key'])
            recovery_fernet = Fernet(recovery_encoder_key)
            master_key = recovery_fernet.decrypt(encrypted_recovery_key)
            
            # Успешное восстановление - очищаем счетчик
            self._recovery_protection.clear_attempts(user_id)
            return master_key
            
        except Exception as e:
            self._recovery_protection.record_attempt(user_id)
            
            # Добавляем задержку для защиты от перебора
            elapsed_time = time.time() - start_time
            min_delay = 1.0
            if elapsed_time < min_delay:
                time.sleep(min_delay - elapsed_time)
            
            logging.error(f"Ошибка восстановления мастер-ключа: {e}")
            raise ValueError("Неверные ответы на вопросы или восстановление не настроено")
    
    def change_master_password(self, old_password, new_password, new_password_hint=""):
        """Смена мастер-пароля"""
        # Получаем текущий мастер-ключ через старый пароль
        master_key = self.get_master_key(old_password)
        
        # Генерируем новый ключ-шифровальщик для пароля
        new_master_password_encoder_key = Fernet.generate_key()
        new_master_password_fernet = Fernet(new_master_password_encoder_key)
        
        # Перешифровываем мастер-ключ новым способом
        new_encrypted_master_key = new_master_password_fernet.encrypt(master_key)
        
        # Шифруем новый ключ-шифровальщик новым паролем
        encrypted_new_master_password_encoder = self._encrypt_with_password(
            new_master_password_encoder_key, new_password
        )
        
        # Обновляем хеш пароля
        new_password_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
        
        # Обновляем конфигурацию
        self.config.update({
            'master_password_hash': new_password_hash,
            'encrypted_master_key': base64.b64encode(new_encrypted_master_key).decode(),
            'encrypted_master_password_encoder': base64.b64encode(encrypted_new_master_password_encoder).decode(),
            'password_hint': new_password_hint,
            'last_password_change': self._get_timestamp()
        })
        
        self._save_config()
        return master_key
    
    def setup_recovery_questions(self, password, recovery_questions):
        """Настройка/обновление вопросов восстановления"""
        # Получаем мастер-ключ для перешифровки
        master_key = self.get_master_key(password)
        
        # Генерируем новый ключ-шифровальщик для восстановления
        new_recovery_encoder_key = Fernet.generate_key()
        new_recovery_fernet = Fernet(new_recovery_encoder_key)
        
        # Перешифровываем мастер-ключ новым способом
        new_encrypted_recovery_key = new_recovery_fernet.encrypt(master_key)
        
        # Шифруем новый ключ-шифровальщик ответами на вопросы
        encrypted_new_recovery_encoder = self._encrypt_with_questions(
            new_recovery_encoder_key, recovery_questions
        )
        
        # Сохраняем вопросы восстановления с улучшенной безопасностью
        encrypted_recovery_answers = []
        for question, answer in recovery_questions:
            answer_salt = secrets.token_bytes(16)
            answer_with_salt = answer.encode() + answer_salt
            answer_hash = bcrypt.hashpw(answer_with_salt, bcrypt.gensalt()).decode()
            encrypted_recovery_answers.append({
                'question': question, 
                'answer_hash': answer_hash,
                'salt': base64.b64encode(answer_salt).decode()
            })
        
        # Обновляем конфигурацию
        self.config.update({
            'encrypted_recovery_key': base64.b64encode(new_encrypted_recovery_key).decode(),
            'encrypted_recovery_encoder': base64.b64encode(encrypted_new_recovery_encoder).decode(),
            'recovery_questions': encrypted_recovery_answers,
            'recovery_setup_date': self._get_timestamp()
        })
        
        self._save_config()
    
    def _validate_password_strength(self, password):
        """Улучшенная проверка сложности пароля"""
        if len(password) < 12:
            return {'valid': False, 'message': "Пароль должен содержать минимум 12 символов"}
        
        # Проверка энтропии
        entropy = self._calculate_password_entropy(password)
        if entropy < 3.5:
            return {'valid': False, 'message': "Пароль недостаточно сложный"}
        
        checks = [
            (self._password_regex_cache['uppercase'], "Пароль должен содержать хотя бы одну заглавную букву"),
            (self._password_regex_cache['lowercase'], "Пароль должен содержать хотя бы одну строчную букву"),
            (self._password_regex_cache['digit'], "Пароль должен содержать хотя бы одну цифру"),
            (self._password_regex_cache['special'], "Пароль должен содержать хотя бы один специальный символ"),
            (self._password_regex_cache['latin_only'], "Пароль должен содержать только латинские буквы, цифры и специальные символы"),
            (self._password_regex_cache['common_patterns'], "Пароль слишком простой или содержит распространенные паттерны")
        ]
        
        for check_func, error_msg in checks:
            if not check_func(password):
                return {'valid': False, 'message': error_msg}
        
        return {'valid': True, 'message': "Пароль надежен"}
    
    def _calculate_password_entropy(self, password):
        """Вычисление энтропии пароля"""
        char_sets = 0
        if re.search(r'[a-z]', password):
            char_sets += 26
        if re.search(r'[A-Z]', password):
            char_sets += 26
        if re.search(r'\d', password):
            char_sets += 10
        if re.search(r'[^a-zA-Z0-9]', password):
            char_sets += 32
        
        entropy = len(password) * (char_sets.bit_length() if char_sets > 0 else 1)
        return entropy / 10
    
    def get_password_hint(self):
        """Получение подсказки к паролю"""
        return self.config.get('password_hint', '')
    
    def get_recovery_questions(self):
        """Получение вопросов восстановления"""
        questions = []
        for q in self.config.get('recovery_questions', []):
            questions.append((q['question'], ''))  # Не возвращаем ответы
        return questions
    
    def verify_recovery_answers(self, answers):
        """Проверка ответов на вопросы восстановления с улучшенной безопасностью"""
        stored_questions = self.config.get('recovery_questions', [])
        if len(answers) != len(stored_questions):
            return False
        
        user_id = self.config.get('user_id', 'default')
        
        # Проверяем блокировку
        if self._recovery_protection.is_locked_out(user_id):
            return False
        
        start_time = time.time()
        result = True
        
        try:
            for i, (question, answer) in enumerate(answers):
                try:
                    stored_data = stored_questions[i]
                    stored_answer_hash = stored_data['answer_hash'].encode()
                    answer_salt = base64.b64decode(stored_data['salt'])
                    
                    # Проверяем с учетом соли
                    answer_with_salt = answer.lower().encode() + answer_salt
                    if not bcrypt.checkpw(answer_with_salt, stored_answer_hash):
                        result = False
                        break
                except Exception as e:
                    logging.error(f"Ошибка проверки ответа на вопрос: {e}")
                    result = False
                    break
            
            if not result:
                self._recovery_protection.record_attempt(user_id)
            
            # Добавляем постоянную задержку для защиты от timing attacks
            elapsed_time = time.time() - start_time
            constant_delay = 0.5
            if elapsed_time < constant_delay:
                time.sleep(constant_delay - elapsed_time)
            
            return result
            
        except Exception as e:
            self._recovery_protection.record_attempt(user_id)
            return False
    
    def get_recovery_status(self):
        """Получение статуса восстановления"""
        user_id = self.config.get('user_id', 'default')
        
        return {
            'is_locked_out': self._recovery_protection.is_locked_out(user_id),
            'remaining_time': self._recovery_protection.get_remaining_time(user_id),
            'recovery_configured': len(self.config.get('recovery_questions', [])) > 0
        }
    
    def _get_timestamp(self):
        """Получение текущего времени"""
        from datetime import datetime
        return datetime.now().isoformat()

# Сохраняем обратную совместимость
AuthManager = SecureAuthManager