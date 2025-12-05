import os
import bcrypt
import base64
import time
import re
import logging
import threading
import hashlib
from threading import Timer
from typing import Dict, Optional
from cryptography.fernet import Fernet

# Используем нашу реализацию SecureString
from securestring import SecureString


class SecureFolderSecurityManager:
    def __init__(self, crypto_manager):
        self.crypto = crypto_manager
        self.unlocked_folders: Dict[str, dict] = {}
        self.auto_lock_timers: Dict[str, threading.Timer] = {}
        self.auto_lock_timeout = 30 * 60
        
        # Защита от brute-force атак
        self.failed_attempts: Dict[str, list] = {}
        self.max_attempts = 5
        self.lockout_time = 300
        self.base_delay = 2
        
        # Безопасный кэш
        self._password_cache: Dict[str, tuple] = {}
        self._cache_ttl = 60
        self._cache_lock = threading.RLock()
        
        # Блокировка для потокобезопасности
        self._lock = threading.RLock()
        
        self._init_regex_cache()
    
    def _init_regex_cache(self):
        """Инициализация кэша regex"""
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
        """Проверка на слабые паттерны"""
        common_patterns = [
            r'12345678',
            r'password',
            r'qwerty',
            r'admin',
            r'welcome',
            r'(.)\1{3,}',
            r'(0123|1234|2345|3456|4567|5678|6789|7890)',
        ]
        
        password_lower = password.lower()
        for pattern in common_patterns:
            if re.search(pattern, password_lower):
                return False
        return True
    
    def _validate_folder_password(self, password):
        """Улучшенная валидация пароля"""
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
    
    def _apply_rate_limiting(self, folder_id):
        """Rate limiting с прогрессивной задержкой"""
        with self._lock:
            if folder_id not in self.failed_attempts:
                return 0
            
            attempts = self.failed_attempts[folder_id]
            recent_attempts = [t for t in attempts if time.time() - t < self.lockout_time]
            
            if len(recent_attempts) >= 3:
                delay = min(self.base_delay * (2 ** (len(recent_attempts) - 3)), 30)
                time.sleep(delay)
                return delay
            
            return 0
    
    def unlock_folder(self, folder_data, folder_password, use_recovery=False):
        """Разблокировка папки с улучшенной защитой"""
        folder_id = folder_data['id']
        
        # Применяем rate limiting
        self._apply_rate_limiting(folder_id)
        
        # Проверяем блокировку
        if self._is_folder_locked_out(folder_id):
            remaining_time = self._get_remaining_lockout_time(folder_id)
            raise PermissionError(f"Папка временно заблокирована. Попробуйте через {remaining_time} сек.")
        
        start_time = time.time()
        success = False
        
        try:
            if use_recovery:
                success = self.recover_folder_access(folder_data, folder_password)
            else:
                success = self._secure_password_check(folder_data, folder_password)
            
            if success:
                # Сбрасываем счетчик неудачных попыток
                with self._lock:
                    if folder_id in self.failed_attempts:
                        del self.failed_attempts[folder_id]
                
                # Безопасная разблокировка
                encrypted_folder_key = base64.b64decode(folder_data['encrypted_folder_key'])
                folder_key = self.crypto.decrypt_with_master_key(encrypted_folder_key)
                
                # Безопасное хранение ключа
                secure_key = SecureString(folder_key)
                
                with self._lock:
                    self.unlocked_folders[folder_id] = {
                        'key': secure_key,
                        'unlock_time': time.time(),
                        'name': folder_data['name'],
                        'recovered': use_recovery
                    }
                
                self._set_auto_lock_timer(folder_id)
                return True
            else:
                self._record_failed_attempt(folder_id)
                return False
                
        finally:
            execution_time = time.time() - start_time
            if execution_time > 1.0:
                logging.warning(f"Медленная разблокировка папки {folder_id[:8]}...: {execution_time:.2f} сек.")
    
    def _secure_password_check(self, folder_data, password):
        """Constant-time проверка пароля"""
        try:
            # Используем constant-time сравнение
            input_hash = bcrypt.hashpw(password.encode(), folder_data['password_hash'].encode())
            stored_hash = folder_data['password_hash'].encode()
            
            return self._constant_time_compare(input_hash, stored_hash)
        except Exception:
            return False
    
    def _constant_time_compare(self, a, b):
        """Constant-time сравнение"""
        if len(a) != len(b):
            return False
        
        result = 0
        for x, y in zip(a, b):
            result |= x ^ y
        return result == 0
    
    def get_folder_key(self, folder_id):
        """Безопасное получение ключа папки"""
        if not self.is_folder_unlocked(folder_id):
            raise PermissionError(f"Папка {folder_id} заблокирована")
        
        self._set_auto_lock_timer(folder_id)
        
        with self._lock:
            secure_key = self.unlocked_folders[folder_id]['key']
            return secure_key.retrieve()
    
    def lock_folder(self, folder_id):
        """Безопасная блокировка папки"""
        with self._lock:
            if folder_id in self.unlocked_folders:
                # Безопасное удаление ключа
                secure_key = self.unlocked_folders[folder_id]['key']
                secure_key.secure_clear()
                del self.unlocked_folders[folder_id]
        
        if folder_id in self.auto_lock_timers:
            self.auto_lock_timers[folder_id].cancel()
            with self._lock:
                if folder_id in self.auto_lock_timers:
                    del self.auto_lock_timers[folder_id]
    
    def cleanup(self):
        """Безопасная очистка ресурсов"""
        with self._lock:
            for timer in self.auto_lock_timers.values():
                timer.cancel()
            self.auto_lock_timers.clear()
            
            # Безопасное удаление всех ключей
            for folder_id in list(self.unlocked_folders.keys()):
                self.lock_folder(folder_id)
            
            self.failed_attempts.clear()
            self._password_cache.clear()

    # Остальные методы остаются без изменений для совместимости
    def _is_folder_locked_out(self, folder_id):
        with self._lock:
            if folder_id not in self.failed_attempts:
                return False
            
            attempts = self.failed_attempts[folder_id]
            recent_attempts = [t for t in attempts if time.time() - t < self.lockout_time]
            self.failed_attempts[folder_id] = recent_attempts
            
            return len(recent_attempts) >= self.max_attempts
    
    def _record_failed_attempt(self, folder_id):
        with self._lock:
            if folder_id not in self.failed_attempts:
                self.failed_attempts[folder_id] = []
            
            self.failed_attempts[folder_id].append(time.time())
            
            if len(self.failed_attempts[folder_id]) > self.max_attempts * 2:
                self.failed_attempts[folder_id] = self.failed_attempts[folder_id][-self.max_attempts:]
    
    def _get_remaining_lockout_time(self, folder_id):
        with self._lock:
            if folder_id not in self.failed_attempts:
                return 0
            
            attempts = self.failed_attempts[folder_id]
            if not attempts:
                return 0
            
            oldest_recent_attempt = min(attempts)
            elapsed = time.time() - oldest_recent_attempt
            remaining = self.lockout_time - elapsed
            
            return max(0, int(remaining))
    
    def is_folder_unlocked(self, folder_id):
        with self._lock:
            return folder_id in self.unlocked_folders
    
    def _set_auto_lock_timer(self, folder_id):
        with self._lock:
            if folder_id in self.auto_lock_timers:
                self.auto_lock_timers[folder_id].cancel()
        
        timer = Timer(self.auto_lock_timeout, self.lock_folder, [folder_id])
        timer.daemon = True
        timer.start()
        
        with self._lock:
            self.auto_lock_timers[folder_id] = timer
    
    def _generate_folder_id(self):
        return os.urandom(8).hex()
    
    def _get_timestamp(self):
        from datetime import datetime
        return datetime.now().isoformat()

# Сохраняем обратную совместимость
FolderSecurityManager = SecureFolderSecurityManager