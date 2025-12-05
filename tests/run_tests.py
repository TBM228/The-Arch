#!/usr/bin/env python3
# tests/run_tests.py - ЗАПУСК ВСЕХ ТЕСТОВ
import unittest
import sys
import os
import logging
from datetime import datetime

# Добавляем родительскую директорию в путь для импорта
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestRunner:
    """Запуск всех тестов"""
    
    def __init__(self):
        self.test_results = {}
        self.total_tests = 0
        self.passed_tests = 0
        self.failed_tests = 0
        
        # Настройка логирования
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger('TestRunner')
    
    def discover_tests(self):
        """Поиск всех тестов"""
        test_loader = unittest.TestLoader()
        
        # Находим все тестовые модули
        test_modules = []
        test_dir = os.path.dirname(os.path.abspath(__file__))
        
        for file in os.listdir(test_dir):
            if file.startswith('test_') and file.endswith('.py'):
                module_name = file[:-3]  # Убираем .py
                test_modules.append(f'tests.{module_name}')
        
        self.logger.info(f"Найдено тестовых модулей: {len(test_modules)}")
        
        # Загружаем тесты из каждого модуля
        test_suites = []
        for module_name in test_modules:
            try:
                suite = test_loader.loadTestsFromName(module_name)
                test_suites.append(suite)
                self.logger.info(f"  Загружен: {module_name}")
            except Exception as e:
                self.logger.error(f"  Ошибка загрузки {module_name}: {e}")
        
        return unittest.TestSuite(test_suites)
    
    def run_all_tests(self):
        """Запуск всех тестов"""
        self.logger.info("=" * 60)
        self.logger.info("ЗАПУСК ТЕСТОВ MEDIA VAULT")
        self.logger.info("=" * 60)
        
        # Обнаруживаем тесты
        test_suite = self.discover_tests()
        
        # Запускаем тесты
        runner = unittest.TextTestRunner(
            verbosity=2,
            failfast=False,
            buffer=False
        )
        
        # Собираем результаты
        result = runner.run(test_suite)
        
        # Анализируем результаты
        self.total_tests = result.testsRun
        self.failed_tests = len(result.failures) + len(result.errors)
        self.passed_tests = self.total_tests - self.failed_tests
        
        # Сохраняем детальные результаты
        self._save_detailed_results(result)
        
        # Выводим сводку
        self._print_summary(result)
        
        return result.wasSuccessful()
    
    def _save_detailed_results(self, result):
        """Сохранение детальных результатов"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = f'test_report_{timestamp}.txt'
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("=" * 60 + "\n")
            f.write("ОТЧЕТ О ТЕСТИРОВАНИИ MEDIA VAULT\n")
            f.write("=" * 60 + "\n\n")
            
            f.write(f"Дата и время: {datetime.now().isoformat()}\n")
            f.write(f"Всего тестов: {result.testsRun}\n")
            f.write(f"Пройдено: {self.passed_tests}\n")
            f.write(f"Провалено: {self.failed_tests}\n\n")
            
            if result.failures:
                f.write("ПРОВАЛЕННЫЕ ТЕСТЫ:\n")
                f.write("-" * 40 + "\n")
                for test, traceback in result.failures:
                    f.write(f"\n{test}\n")
                    f.write(f"{traceback}\n")
            
            if result.errors:
                f.write("\nТЕСТЫ С ОШИБКАМИ:\n")
                f.write("-" * 40 + "\n")
                for test, traceback in result.errors:
                    f.write(f"\n{test}\n")
                    f.write(f"{traceback}\n")
            
            if result.skipped:
                f.write("\nПРОПУЩЕННЫЕ ТЕСТЫ:\n")
                f.write("-" * 40 + "\n")
                for test, reason in result.skipped:
                    f.write(f"\n{test}: {reason}\n")
        
        self.logger.info(f"Детальный отчет сохранен в {report_file}")
    
    def _print_summary(self, result):
        """Вывод сводки результатов"""
        self.logger.info("=" * 60)
        self.logger.info("РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ")
        self.logger.info("=" * 60)
        
        # Статистика
        self.logger.info(f"Всего тестов: {self.total_tests}")
        self.logger.info(f"Пройдено: {self.passed_tests}")
        self.logger.info(f"Провалено: {self.failed_tests}")
        
        if result.errors:
            self.logger.info(f"Ошибок: {len(result.errors)}")
        
        if result.failures:
            self.logger.info(f"Провалов: {len(result.failures)}")
        
        if result.skipped:
            self.logger.info(f"Пропущено: {len(result.skipped)}")
        
        # Процент успешных тестов
        if self.total_tests > 0:
            success_rate = (self.passed_tests / self.total_tests) * 100
            self.logger.info(f"Успешность: {success_rate:.1f}%")
        
        # Итог
        self.logger.info("-" * 40)
        if result.wasSuccessful():
            self.logger.info("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО")
        else:
            self.logger.info("❌ НЕКОТОРЫЕ ТЕСТЫ ПРОВАЛЕНЫ")
        self.logger.info("=" * 60)
    
    def run_security_tests(self):
        """Запуск только тестов безопасности"""
        self.logger.info("Запуск тестов безопасности...")
        
        test_loader = unittest.TestLoader()
        security_suite = test_loader.loadTestsFromName('tests.test_security')
        
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(security_suite)
        
        return result.wasSuccessful()
    
    def run_performance_tests(self):
        """Запуск тестов производительности"""
        self.logger.info("Запуск тестов производительности...")
        
        # Здесь можно добавить специализированные тесты производительности
        self.logger.info("Тесты производительности еще не реализованы")
        return True
    
    def generate_coverage_report(self):
        """Генерация отчета о покрытии тестами"""
        try:
            import coverage
            
            self.logger.info("Генерация отчета о покрытии...")
            
            cov = coverage.Coverage(
                source=['auth', 'crypto', 'vault_core', 'backup_manager'],
                omit=['*/tests/*', '*/__pycache__/*']
            )
            
            cov.start()
            
            # Запускаем тесты
            self.run_all_tests()
            
            cov.stop()
            cov.save()
            
            # Генерируем отчеты
            cov.report(show_missing=True)
            cov.html_report(directory='coverage_report')
            
            self.logger.info("Отчет о покрытии сохранен в coverage_report/")
            
        except ImportError:
            self.logger.warning("coverage не установлен. Установите: pip install coverage")


def main():
    """Главная функция"""
    runner = TestRunner()
    
    # Парсим аргументы командной строки
    import argparse
    parser = argparse.ArgumentParser(description='Запуск тестов Media Vault')
    parser.add_argument('--security-only', action='store_true', 
                       help='Запустить только тесты безопасности')
    parser.add_argument('--performance-only', action='store_true',
                       help='Запустить только тесты производительности')
    parser.add_argument('--coverage', action='store_true',
                       help='Сгенерировать отчет о покрытии')
    
    args = parser.parse_args()
    
    try:
        if args.security_only:
            success = runner.run_security_tests()
        elif args.performance_only:
            success = runner.run_performance_tests()
        elif args.coverage:
            runner.generate_coverage_report()
            success = True
        else:
            success = runner.run_all_tests()
        
        # Возвращаем код выхода
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        runner.logger.info("\nТестирование прервано пользователем")
        sys.exit(130)
    except Exception as e:
        runner.logger.error(f"Ошибка при запуске тестов: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()