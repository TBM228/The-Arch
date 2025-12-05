# performance_monitor.py - УЛУЧШЕННЫЙ МОНИТОРИНГ
import time
import logging
import threading
import psutil
import gc
from collections import deque, defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime


@dataclass
class PerformanceMetrics:
    memory_usage: float
    cpu_usage: float
    disk_usage: float
    operation_times: Dict[str, List[float]]
    error_count: int
    gc_stats: Dict[str, int]
    thread_count: int


class ResourceMonitor:
    """Мониторинг системных ресурсов"""
    
    def __init__(self):
        self._process = psutil.Process()
        self._metrics_history = deque(maxlen=100)
        self._lock = threading.RLock()
    
    def collect_metrics(self) -> Dict:
        """Сбор метрик системы"""
        with self._lock:
            try:
                # Использование памяти
                memory_info = self._process.memory_info()
                memory_mb = memory_info.rss / 1024 / 1024
                
                # Использование CPU
                cpu_percent = self._process.cpu_percent(interval=0.1)
                
                # Использование диска (текущая директория)
                disk_usage = psutil.disk_usage('.').percent
                
                # Статистика сборщика мусора
                gc_stats = {
                    'collections': gc.get_count(),
                    'threshold': gc.get_threshold(),
                    'enabled': gc.isenabled()
                }
                
                # Количество потоков
                thread_count = threading.active_count()
                
                metrics = {
                    'memory_usage_mb': memory_mb,
                    'cpu_usage_percent': cpu_percent,
                    'disk_usage_percent': disk_usage,
                    'gc_stats': gc_stats,
                    'thread_count': thread_count,
                    'timestamp': time.time()
                }
                
                self._metrics_history.append(metrics)
                return metrics
                
            except Exception as e:
                logging.error(f"Ошибка сбора метрик: {e}")
                return {}


class PerformanceMonitor:
    def __init__(self):
        self.metrics = PerformanceMetrics(0, 0, 0, {}, 0, {}, 0)
        self._operation_stats = {}
        self._error_count = 0
        self._is_monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        
        # Мониторинг ресурсов
        self._resource_monitor = ResourceMonitor()
        
        # Статистика операций
        self._operation_times: Dict[str, deque] = {}
        self._operation_errors: Dict[str, int] = defaultdict(int)
        self._max_samples = 100
        
        # Оповещения
        self._alerts = deque(maxlen=50)
        self._alert_thresholds = {
            'memory_mb': 1024,  # 1GB
            'cpu_percent': 80,   # 80%
            'disk_percent': 90   # 90%
        }
    
    def start_monitoring(self):
        """Запуск мониторинга производительности"""
        if self._is_monitoring:
            return
            
        self._is_monitoring = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logging.info("Мониторинг производительности запущен")
    
    def stop_monitoring(self):
        """Остановка мониторинга"""
        self._is_monitoring = False
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2.0)
        logging.info("Мониторинг производительности остановлен")
    
    def _monitor_loop(self):
        """Цикл мониторинга"""
        while self._is_monitoring:
            try:
                # Собираем метрики
                metrics = self._resource_monitor.collect_metrics()
                
                if metrics:
                    # Обновляем основные метрики
                    self.metrics.memory_usage = metrics.get('memory_usage_mb', 0)
                    self.metrics.cpu_usage = metrics.get('cpu_usage_percent', 0)
                    self.metrics.disk_usage = metrics.get('disk_usage_percent', 0)
                    self.metrics.gc_stats = metrics.get('gc_stats', {})
                    self.metrics.thread_count = metrics.get('thread_count', 0)
                    
                    # Проверяем пороги
                    self._check_thresholds(metrics)
                
                time.sleep(5)  # Проверка каждые 5 секунд
                
            except Exception as e:
                logging.error(f"Ошибка мониторинга производительности: {e}")
                time.sleep(10)  # Увеличиваем интервал при ошибках
    
    def _check_thresholds(self, metrics):
        """Проверка превышения порогов"""
        alerts = []
        
        # Проверка памяти
        if metrics['memory_usage_mb'] > self._alert_thresholds['memory_mb']:
            alerts.append(f"Высокое использование памяти: {metrics['memory_usage_mb']:.1f} MB")
        
        # Проверка CPU
        if metrics['cpu_usage_percent'] > self._alert_thresholds['cpu_percent']:
            alerts.append(f"Высокая загрузка CPU: {metrics['cpu_usage_percent']:.1f}%")
        
        # Проверка диска
        if metrics['disk_usage_percent'] > self._alert_thresholds['disk_percent']:
            alerts.append(f"Мало свободного места на диске: {metrics['disk_usage_percent']:.1f}%")
        
        # Логируем оповещения
        for alert in alerts:
            self._record_alert(alert)
            logging.warning(f"ОПОВЕЩЕНИЕ: {alert}")
    
    def _record_alert(self, message):
        """Запись оповещения"""
        alert = {
            'timestamp': datetime.now().isoformat(),
            'message': message
        }
        self._alerts.append(alert)
    
    def record_operation_time(self, operation_name: str, execution_time: float):
        """Запись времени выполнения операции"""
        if operation_name not in self._operation_times:
            self._operation_times[operation_name] = deque(maxlen=self._max_samples)
        
        self._operation_times[operation_name].append(execution_time)
        
        # Обновляем метрики
        self.metrics.operation_times[operation_name] = list(self._operation_times[operation_name])
        
        # Логируем медленные операции
        if execution_time > 2.0:  # Больше 2 секунд
            self._record_alert(f"Медленная операция {operation_name}: {execution_time:.2f} сек.")
            logging.warning(f"Медленная операция {operation_name}: {execution_time:.2f} сек.")
    
    def record_operation_error(self, operation_name: str):
        """Запись ошибки операции"""
        self._operation_errors[operation_name] += 1
        self.record_error()
    
    def record_error(self):
        """Запись общей ошибки"""
        self._error_count += 1
        self.metrics.error_count = self._error_count
    
    def get_operation_stats(self, operation_name: str) -> Dict:
        """Получение статистики по операции"""
        if operation_name not in self._operation_times:
            return {}
        
        times = list(self._operation_times[operation_name])
        if not times:
            return {}
        
        error_count = self._operation_errors.get(operation_name, 0)
        
        return {
            'count': len(times),
            'avg_time': sum(times) / len(times),
            'max_time': max(times),
            'min_time': min(times),
            'last_time': times[-1] if times else 0,
            'error_count': error_count,
            'error_rate': error_count / len(times) if times else 0
        }
    
    def get_summary_stats(self) -> Dict:
        """Получение сводной статистики"""
        stats = {
            'memory_usage_mb': self.metrics.memory_usage,
            'cpu_usage_percent': self.metrics.cpu_usage,
            'disk_usage_percent': self.metrics.disk_usage,
            'total_errors': self.metrics.error_count,
            'monitored_operations': len(self._operation_times),
            'thread_count': self.metrics.thread_count,
            'operations': {},
            'alerts': list(self._alerts)
        }
        
        for op_name in self._operation_times:
            stats['operations'][op_name] = self.get_operation_stats(op_name)
        
        return stats
    
    def get_performance_report(self) -> Dict:
        """Получение детального отчета о производительности"""
        report = self.get_summary_stats()
        
        # Добавляем историю метрик
        report['metrics_history'] = list(self._resource_monitor._metrics_history)
        
        # Анализ производительности
        report['performance_analysis'] = self._analyze_performance()
        
        return report
    
    def _analyze_performance(self) -> Dict:
        """Анализ производительности"""
        analysis = {
            'issues': [],
            'recommendations': []
        }
        
        # Анализ памяти
        if self.metrics.memory_usage > 500:  # 500MB
            analysis['issues'].append("Высокое использование памяти")
            analysis['recommendations'].append("Рассмотрите оптимизацию использования памяти")
        
        # Анализ CPU
        if self.metrics.cpu_usage > 70:  # 70%
            analysis['issues'].append("Высокая загрузка CPU")
            analysis['recommendations'].append("Проверьте ресурсоемкие операции")
        
        # Анализ ошибок
        if self.metrics.error_count > 10:
            analysis['issues'].append("Много ошибок")
            analysis['recommendations'].append("Проверьте логи и исправьте частые ошибки")
        
        return analysis
    
    def clear_old_data(self):
        """Очистка устаревших данных"""
        # В этой реализации данные автоматически ограничиваются deque
        # Можно добавить очистку по времени
        pass


# Глобальный экземпляр монитора
global_monitor = PerformanceMonitor()