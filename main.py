#!/usr/bin/env python3
# main.py - УЛУЧШЕННАЯ ОБРАБОТКА ОШИБОК
import sys
import os
import logging
import traceback
import atexit
import signal
from performance_monitor import global_monitor

# Расширенная настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.FileHandler('media_vault.log', encoding='utf-8', mode='a'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


class EmergencyShutdown:
    """Аварийное завершение приложения"""
    
    @staticmethod
    def emergency_cleanup():
        """Экстренная очистка ресурсов"""
        try:
            logger.critical("АВАРИЙНОЕ ЗАВЕРШЕНИЕ - очистка ресурсов")
            
            # Пытаемся сохранить важные данные
            EmergencyShutdown._save_crash_report()
            
            # Завершаем мониторинг
            global_monitor.stop_monitoring()
            
            logger.critical("Аварийное завершение выполнено")
            
        except Exception as e:
            logger.critical(f"Ошибка при аварийном завершении: {e}")
    
    @staticmethod
    def _save_crash_report():
        """Сохранение отчета о краше"""
        try:
            crash_info = traceback.format_exc()
            with open('media_vault_crash.log', 'w', encoding='utf-8') as f:
                f.write("=== CRASH REPORT ===\n")
                f.write(f"Time: {logging.Formatter().formatTime(logging.makeLogRecord({}))}\n")
                f.write(f"Python: {sys.version}\n")
                f.write(f"Platform: {sys.platform}\n")
                f.write(f"\nTraceback:\n{crash_info}\n")
        except Exception as e:
            logger.error(f"Не удалось сохранить отчет об ошибке: {e}")


def setup_error_handling():
    """Настройка обработки непредвиденных ошибок"""
    
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        
        logger.critical("НЕПРЕДВИДЕННАЯ ОШИБКА:", 
                       exc_info=(exc_type, exc_value, exc_traceback))
        
        # Записываем в мониторинг
        global_monitor.record_error()
        
        # Сохраняем отчет об ошибке
        try:
            error_msg = f"Критическая ошибка: {exc_value}"
            error_details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            
            with open('media_vault_crash.log', 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*50}\n")
                f.write(f"UNHANDLED EXCEPTION\n")
                f.write(f"Time: {logging.Formatter().formatTime(logging.makeLogRecord({}))}\n")
                f.write(f"Error: {error_msg}\n")
                f.write(f"Details:\n{error_details}\n")
        except Exception as e:
            logger.error(f"Не удалось сохранить отчет об ошибке: {e}")
        
        # Аварийное завершение
        EmergencyShutdown.emergency_cleanup()
    
    sys.excepthook = handle_exception
    
    # Обработка сигналов
    def signal_handler(signum, frame):
        logger.critical(f"Получен сигнал {signum}, завершение...")
        EmergencyShutdown.emergency_cleanup()
        sys.exit(1)
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)


def check_system_requirements():
    """Проверка системных требований"""
    issues = []
    
    # Проверяем Python версию
    if sys.version_info < (3, 7):
        issues.append("Требуется Python 3.7 или выше")
    
    # Проверяем доступное место на диске
    try:
        if hasattr(os, 'statvfs'):  # Unix-like systems
            stat = os.statvfs('.')
            free_space_gb = (stat.f_bavail * stat.f_frsize) / (1024 ** 3)
            if free_space_gb < 1:
                issues.append(f"Мало свободного места на диске: {free_space_gb:.1f} GB")
        else:  # Windows
            import ctypes
            free_bytes = ctypes.c_ulonglong(0)
            ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                ctypes.c_wchar_p('.'), None, None, ctypes.pointer(free_bytes)
            )
            free_space_gb = free_bytes.value / (1024 ** 3)
            if free_space_gb < 1:
                issues.append(f"Мало свободного места на диске: {free_space_gb:.1f} GB")
    except Exception as e:
        logger.warning(f"Не удалось проверить свободное место на диске: {e}")
    
    return issues


def setup_environment():
    """Настройка окружения"""
    try:
        # Проверяем и создаем необходимые директории
        required_dirs = [
            'data/encrypted_files',
            'temp',
            'backups',
            'logs'
        ]
        
        for dir_path in required_dirs:
            os.makedirs(dir_path, exist_ok=True)
            logger.debug(f"Создана директория: {dir_path}")
        
        # Ограничиваем размер логов
        log_file = 'media_vault.log'
        if os.path.exists(log_file) and os.path.getsize(log_file) > 10 * 1024 * 1024:
            # Ротируем лог
            import shutil
            backup_log = f'{log_file}.backup'
            if os.path.exists(backup_log):
                os.remove(backup_log)
            shutil.move(log_file, backup_log)
            logger.info("Лог файл был ротирован")
            
    except Exception as e:
        logger.error(f"Ошибка настройки окружения: {e}")
        raise


def main():
    """Главная функция"""
    # Настройка обработки ошибок
    setup_error_handling()
    
    logger.info("Запуск Media Vault...")
    
    # Регистрируем аварийное завершение
    atexit.register(EmergencyShutdown.emergency_cleanup)
    
    # Проверяем системные требования
    issues = check_system_requirements()
    if issues:
        logger.warning("Обнаружены потенциальные проблемы:")
        for issue in issues:
            logger.warning(f"  - {issue}")
    
    # Настраиваем окружение
    try:
        setup_environment()
    except Exception as e:
        logger.error(f"Критическая ошибка настройки окружения: {e}")
        sys.exit(1)
    
    # Мониторинг производительности
    global_monitor.start_monitoring()
    
    try:
        # Запускаем приложение
        from gui.main_window import MediaVaultApp
        
        logger.info("Инициализация приложения...")
        app = MediaVaultApp()
        
        logger.info("Запуск основного цикла...")
        app.run()
        
        logger.info("Media Vault завершил работу")
        
    except ImportError as e:
        logger.error(f"Ошибка импорта модулей: {e}")
        logger.error("Проверьте установку зависимостей: pip install -r requirements.txt")
        global_monitor.record_error()
        sys.exit(1)
        
    except Exception as e:
        logger.error(f"Критическая ошибка запуска приложения: {e}")
        global_monitor.record_error()
        sys.exit(1)
    
    finally:
        global_monitor.stop_monitoring()
        
        # Сохраняем финальную статистику
        try:
            stats = global_monitor.get_summary_stats()
            logger.info("Финальная статистика производительности:")
            logger.info(f"  Использование памяти: {stats['memory_usage_mb']:.1f} MB")
            logger.info(f"  Использование CPU: {stats['cpu_usage_percent']:.1f}%")
            logger.info(f"  Всего ошибок: {stats['total_errors']}")
            logger.info(f"  Отслеживаемых операций: {stats['monitored_operations']}")
        except Exception as e:
            logger.error(f"Ошибка при сохранении статистики: {e}")


if __name__ == "__main__":
    main()