# tests/test_performance.py - ТЕСТЫ ПРОИЗВОДИТЕЛЬНОСТИ
import unittest
import tempfile
import os
import time
import statistics
import psutil
import gc
from pathlib import Path

from auth import AuthManager
from crypto import CryptoManager
from vault_core import VaultCore
from folder_security import FolderSecurityManager


class PerformanceTest(unittest.TestCase):
    """Тесты производительности"""
    
    def setUp(self):
        """Настройка перед каждым тестом"""
        self.test_dir = tempfile.mkdtemp(prefix='performance_test_')
        
        # Инициализируем менеджеры
        self.auth = AuthManager()
        self.auth.config_path = os.path.join(self.test_dir, 'vault_config.json')
        
        # Создаем мастер-пароль
        self.test_password = "TestPassword123!"
        self.master_key = self.auth.create_master_password(self.test_password, "")
        
        self.crypto = CryptoManager(self.master_key)
        self.folder_security = FolderSecurityManager(self.crypto)
        self.vault = VaultCore(
            self.auth,
            self.crypto,
            self.folder_security
        )
        
        self.vault.filesystem_path = os.path.join(self.test_dir, 'filesystem.json.enc')
        
        # Собираем метрики
        self.performance_metrics = {
            'encryption_times': [],
            'decryption_times': [],
            'file_add_times': [],
            'file_extract_times': [],
            'memory_usage': []
        }
    
    def tearDown(self):
        """Очистка после каждого теста"""
        # Очищаем ресурсы
        self.crypto.secure_clear()
        self.folder_security.cleanup()
        self.vault.cleanup()
        
        # Удаляем тестовую директорию
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    def _measure_memory(self):
        """Измерение использования памяти"""
        process = psutil.Process()
        return process.memory_info().rss / 1024 / 1024  # MB
    
    def test_encryption_performance(self):
        """Тест производительности шифрования"""
        file_sizes = [1, 10, 100]  # KB
        results = {}
        
        for size_kb in file_sizes:
            # Создаем файл заданного размера
            file_size = size_kb * 1024
            test_file = os.path.join(self.test_dir, f'test_{size_kb}kb.bin')
            
            with open(test_file, 'wb') as f:
                f.write(os.urandom(file_size))
            
            # Измеряем время шифрования
            start_time = time.perf_counter()
            vault_filename, file_id = self.crypto.encrypt_file(test_file)
            end_time = time.perf_counter()
            
            encryption_time = end_time - start_time
            
            # Сохраняем результаты
            results[size_kb] = {
                'time': encryption_time,
                'speed': file_size / encryption_time / 1024,  # KB/s
                'memory': self._measure_memory()
            }
            
            # Очистка
            if os.path.exists(vault_filename):
                os.unlink(vault_filename)
        
        # Анализ результатов
        print("\n" + "="*60)
        print("ТЕСТ ПРОИЗВОДИТЕЛЬНОСТИ ШИФРОВАНИЯ")
        print("="*60)
        
        for size_kb, data in results.items():
            print(f"\nРазмер файла: {size_kb} KB")
            print(f"  Время шифрования: {data['time']:.3f} сек")
            print(f"  Скорость: {data['speed']:.1f} KB/сек")
            print(f"  Использование памяти: {data['memory']:.1f} MB")
        
        # Проверяем, что скорость приемлемая
        for size_kb, data in results.items():
            self.assertGreater(data['speed'], 10)  # Минимум 10 KB/сек
    
    def test_concurrent_encryption_performance(self):
        """Тест производительности при конкурентном шифровании"""
        import concurrent.futures
        
        # Создаем несколько файлов
        num_files = 5
        file_size = 100 * 1024  # 100 KB
        
        test_files = []
        for i in range(num_files):
            test_file = os.path.join(self.test_dir, f'concurrent_{i}.bin')
            with open(test_file, 'wb') as f:
                f.write(os.urandom(file_size))
            test_files.append(test_file)
        
        # Функция для шифрования
        def encrypt_file(file_path):
            start = time.perf_counter()
            vault_filename, file_id = self.crypto.encrypt_file(file_path)
            end = time.perf_counter()
            
            # Очистка
            if os.path.exists(vault_filename):
                os.unlink(vault_filename)
            
            return end - start
        
        # Запускаем конкурентное шифрование
        start_total = time.perf_counter()
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(encrypt_file, f) for f in test_files]
            times = [future.result() for future in concurrent.futures.as_completed(futures)]
        
        end_total = time.perf_counter()
        total_time = end_total - start_total
        
        # Анализ результатов
        print("\n" + "="*60)
        print("ТЕСТ КОНКУРЕНТНОГО ШИФРОВАНИЯ")
        print("="*60)
        print(f"Количество файлов: {num_files}")
        print(f"Размер каждого файла: {file_size/1024:.0f} KB")
        print(f"Общее время: {total_time:.3f} сек")
        print(f"Среднее время на файл: {statistics.mean(times):.3f} сек")
        print(f"Максимальное время: {max(times):.3f} сек")
        print(f"Минимальное время: {min(times):.3f} сек")
        
        # Проверяем, что конкурентное выполнение быстрее последовательного
        # (в идеале, но на практике из-за GIL может быть по-разному)
        estimated_sequential = sum(times)
        print(f"Оценка последовательного времени: {estimated_sequential:.3f} сек")
        
        if total_time < estimated_sequential:
            print("✅ Конкурентное выполнение быстрее последовательного")
        else:
            print("⚠️  Конкурентное выполнение не дало ускорения")
    
    def test_memory_usage_growth(self):
        """Тест роста использования памяти"""
        gc.collect()
        initial_memory = self._measure_memory()
        
        memory_readings = [initial_memory]
        
        # Выполняем несколько операций и измеряем память
        for i in range(10):
            # Создаем и шифруем файл
            test_file = os.path.join(self.test_dir, f'memory_test_{i}.bin')
            with open(test_file, 'wb') as f:
                f.write(os.urandom(1024))  # 1 KB
            
            vault_filename, file_id = self.crypto.encrypt_file(test_file)
            
            # Измеряем память
            memory_readings.append(self._measure_memory())
            
            # Очистка
            if os.path.exists(vault_filename):
                os.unlink(vault_filename)
        
        # Анализ роста памяти
        print("\n" + "="*60)
        print("ТЕСТ РОСТА ИСПОЛЬЗОВАНИЯ ПАМЯТИ")
        print("="*60)
        
        print(f"Начальное использование памяти: {initial_memory:.1f} MB")
        print(f"Конечное использование памяти: {memory_readings[-1]:.1f} MB")
        print(f"Максимальное использование: {max(memory_readings):.1f} MB")
        print(f"Минимальное использование: {min(memory_readings):.1f} MB")
        
        # Вычисляем рост памяти
        memory_growth = memory_readings[-1] - initial_memory
        print(f"Рост памяти: {memory_growth:.1f} MB")
        
        # Проверяем, что память не растет бесконечно
        self.assertLess(memory_growth, 50)  # Не более 50 MB роста
        
        # Принудительный сбор мусора и проверка
        gc.collect()
        final_memory = self._measure_memory()
        print(f"Память после сборки мусора: {final_memory:.1f} MB")
        
        # Проверяем, что память освобождается
        self.assertLess(final_memory, initial_memory + 10)  # Не более +10 MB
    
    def test_large_file_performance(self):
        """Тест производительности с большими файлами"""
        large_sizes = [1, 5, 10]  # MB
        
        results = {}
        
        for size_mb in large_sizes:
            # Создаем большой файл
            file_size = size_mb * 1024 * 1024
            test_file = os.path.join(self.test_dir, f'large_{size_mb}mb.bin')
            
            print(f"\nСоздание файла {size_mb} MB...")
            with open(test_file, 'wb') as f:
                # Пишем по частям чтобы не использовать много памяти
                chunk_size = 1024 * 1024  # 1 MB
                for _ in range(size_mb):
                    f.write(os.urandom(chunk_size))
            
            # Измеряем время шифрования
            print(f"Шифрование файла {size_mb} MB...")
            start_time = time.perf_counter()
            vault_filename, file_id = self.crypto.encrypt_large_file(test_file)
            encryption_time = time.perf_counter() - start_time
            
            # Измеряем время дешифрования
            print(f"Дешифрование файла {size_mb} MB...")
            output_file = os.path.join(self.test_dir, f'decrypted_{size_mb}mb.bin')
            
            start_time = time.perf_counter()
            self.crypto.decrypt_large_file(vault_filename, output_file)
            decryption_time = time.perf_counter() - start_time
            
            # Сохраняем результаты
            results[size_mb] = {
                'encryption_time': encryption_time,
                'decryption_time': decryption_time,
                'encryption_speed': file_size / encryption_time / 1024 / 1024,  # MB/s
                'decryption_speed': file_size / decryption_time / 1024 / 1024,  # MB/s
                'memory': self._measure_memory()
            }
            
            # Очистка
            for f in [vault_filename, output_file, test_file]:
                if os.path.exists(f):
                    os.unlink(f)
        
        # Вывод результатов
        print("\n" + "="*60)
        print("ТЕСТ ПРОИЗВОДИТЕЛЬНОСТИ БОЛЬШИХ ФАЙЛОВ")
        print("="*60)
        
        for size_mb, data in results.items():
            print(f"\nРазмер файла: {size_mb} MB")
            print(f"  Время шифрования: {data['encryption_time']:.2f} сек")
            print(f"  Скорость шифрования: {data['encryption_speed']:.2f} MB/сек")
            print(f"  Время дешифрования: {data['decryption_time']:.2f} сек")
            print(f"  Скорость дешифрования: {data['decryption_speed']:.2f} MB/сек")
            print(f"  Использование памяти: {data['memory']:.1f} MB")
        
        # Проверяем минимальную производительность
        for size_mb, data in results.items():
            self.assertGreater(data['encryption_speed'], 0.1)  # Минимум 0.1 MB/сек
            self.assertGreater(data['decryption_speed'], 0.1)  # Минимум 0.1 MB/сек
    
    def test_filesystem_performance(self):
        """Тест производительности файловой системы"""
        num_operations = 100
        operation_times = []
        
        # Тестируем операции с файловой системой
        for i in range(num_operations):
            # Создаем тестовый файл
            test_file = os.path.join(self.test_dir, f'fs_test_{i}.txt')
            with open(test_file, 'w') as f:
                f.write(f"Тестовые данные {i}")
            
            # Измеряем время добавления файла
            start_time = time.perf_counter()
            
            with self.vault.begin_transaction(f"Операция {i}") as tx:
                tx.add_file(test_file)
            
            operation_time = time.perf_counter() - start_time
            operation_times.append(operation_time)
        
        # Анализ результатов
        print("\n" + "="*60)
        print("ТЕСТ ПРОИЗВОДИТЕЛЬНОСТИ ФАЙЛОВОЙ СИСТЕМЫ")
        print("="*60)
        
        print(f"Количество операций: {num_operations}")
        print(f"Общее время: {sum(operation_times):.3f} сек")
        print(f"Среднее время на операцию: {statistics.mean(operation_times):.3f} сек")
        print(f"Максимальное время: {max(operation_times):.3f} сек")
        print(f"Минимальное время: {min(operation_times):.3f} сек")
        print(f"Стандартное отклонение: {statistics.stdev(operation_times):.3f} сек")
        
        # Проверяем, что операции выполняются достаточно быстро
        self.assertLess(statistics.mean(operation_times), 0.5)  # Менее 0.5 сек в среднем
        
        # Проверяем, что нет сильных выбросов
        outliers = [t for t in operation_times if t > statistics.mean(operation_times) + 2 * statistics.stdev(operation_times)]
        self.assertLess(len(outliers), num_operations * 0.05)  # Менее 5% выбросов
    
    def test_backup_performance(self):
        """Тест производительности бэкапов"""
        # Сначала создаем тестовые данные
        num_files = 10
        for i in range(num_files):
            test_file = os.path.join(self.test_dir, f'backup_test_{i}.txt')
            with open(test_file, 'w') as f:
                f.write(f"Данные для бэкапа {i}\n" * 100)
            
            self.vault.add_file(test_file)
        
        # Тестируем создание бэкапа
        from backup_manager import BackupCreator
        
        backup_creator = BackupCreator(self.crypto, self.auth)
        backup_creator.backup_dir = os.path.join(self.test_dir, 'backups')
        
        print("\n" + "="*60)
        print("ТЕСТ ПРОИЗВОДИТЕЛЬНОСТИ БЭКАПОВ")
        print("="*60)
        
        # Тест полного бэкапа
        print("\nПолный бэкап:")
        start_time = time.perf_counter()
        success, backup_path = backup_creator.create_backup(self.vault, 'full')
        full_backup_time = time.perf_counter() - start_time
        
        if success:
            backup_size = os.path.getsize(backup_path) / 1024 / 1024  # MB
            print(f"  Время: {full_backup_time:.2f} сек")
            print(f"  Размер бэкапа: {backup_size:.2f} MB")
            print(f"  Скорость: {backup_size / full_backup_time:.2f} MB/сек")
        else:
            print("  ❌ Ошибка создания бэкапа")
        
        # Проверяем, что бэкап создан за разумное время
        if success:
            self.assertLess(full_backup_time, 30)  # Менее 30 секунд


if __name__ == '__main__':
    # Запуск тестов производительности
    suite = unittest.TestLoader().loadTestsFromTestCase(PerformanceTest)
    runner = unittest.TextTestRunner(verbosity=2)
    
    print("="*60)
    print("ЗАПУСК ТЕСТОВ ПРОИЗВОДИТЕЛЬНОСТИ")
    print("="*60)
    
    result = runner.run(suite)