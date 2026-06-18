import json
import re
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Union
from pathlib import Path

import numpy as np
import pandas as pd

from utils.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# Функции для работы с временными метками
# ============================================================================

def normalize_timestamp(timestamp: Union[datetime, str, float, int]) -> datetime:
    """
    Приведение временной метки к единому формату datetime
    
    Args:
        timestamp: Временная метка в различных форматах
        
    Returns:
        datetime объект
    """
    if isinstance(timestamp, datetime):
        return timestamp
    elif isinstance(timestamp, str):
        # Попытка разбора ISO формата
        try:
            return datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        except ValueError:
            # Попытка разбора других форматов
            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S', '%d.%m.%Y %H:%M:%S']:
                try:
                    return datetime.strptime(timestamp, fmt)
                except ValueError:
                    continue
            raise ValueError(f"Unrecognized timestamp format: {timestamp}")
    elif isinstance(timestamp, (float, int)):
        return datetime.fromtimestamp(timestamp)
    else:
        raise TypeError(f"Unsupported timestamp type: {type(timestamp)}")


def time_window_to_string(window_start: datetime, window_end: datetime) -> str:
    """Преобразование временного окна в строковый идентификатор"""
    return f"{window_start.isoformat()}_{window_end.isoformat()}"


def get_time_bucket(timestamp: datetime, bucket_seconds: int = 10) -> datetime:
    """Округление временной метки до заданного интервала (по умолчанию 10 секунд)"""
    epoch = timestamp.timestamp()
    bucket = int(epoch / bucket_seconds) * bucket_seconds
    return datetime.fromtimestamp(bucket)


# ============================================================================
# Функции для работы с данными
# ============================================================================

def safe_json_parse(json_string: str, default: Any = None) -> Any:
    """Безопасный парсинг JSON с обработкой ошибок"""
    try:
        return json.loads(json_string)
    except (json.JSONDecodeError, TypeError):
        return default


def safe_json_dumps(obj: Any, default: Any = None) -> str:
    """Безопасное преобразование в JSON с обработкой ошибок"""
    try:
        return json.dumps(obj, default=str)
    except (TypeError, ValueError):
        return json.dumps(default) if default else "{}"


def truncate_string(text: str, max_length: int = 500, suffix: str = "...") -> str:
    """Обрезание строки до указанной длины"""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def clean_metric_name(metric_name: str) -> str:
    """Очистка имени метрики для использования в качестве ключа"""
    # Замена специальных символов на подчеркивания
    cleaned = re.sub(r'[^a-zA-Z0-9_]', '_', metric_name)
    # Удаление дублирующихся подчеркиваний
    cleaned = re.sub(r'_+', '_', cleaned)
    # Удаление начальных и конечных подчеркиваний
    cleaned = cleaned.strip('_')
    return cleaned.lower()


def detect_data_type(series: pd.Series) -> str:
    """
    Определение типа данных временного ряда
    
    Returns:
        'constant' - постоянное значение
        'categorical' - категориальные данные
        'numeric_continuous' - непрерывные числовые
        'numeric_discrete' - дискретные числовые
        'unknown' - неопределенный тип
    """
    if series.nunique() == 1:
        return 'constant'
    
    if series.dtype == 'object':
        return 'categorical'
    
    if series.dtype in ['int64', 'int32', 'float64', 'float32']:
        unique_ratio = series.nunique() / len(series)
        if unique_ratio < 0.05:
            return 'categorical'
        elif series.dtype in ['int64', 'int32']:
            return 'numeric_discrete'
        else:
            return 'numeric_continuous'
    
    return 'unknown'


# ============================================================================
# Функции для оценки качества
# ============================================================================

def calculate_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    """
    Расчет метрик качества для бинарной классификации
    
    Returns:
        Словарь с метриками: accuracy, precision, recall, f1, specificity
    """
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix
    
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred).ravel()
    
    metrics = {
        'accuracy': accuracy_score(y_true, y_pred),
        'precision': precision_score(y_true, y_pred, zero_division=0),
        'recall': recall_score(y_true, y_pred, zero_division=0),
        'f1_score': f1_score(y_true, y_pred, zero_division=0),
        'specificity': tn / (tn + fp) if (tn + fp) > 0 else 0,
        'true_positives': int(tp),
        'false_positives': int(fp),
        'true_negatives': int(tn),
        'false_negatives': int(fn)
    }
    
    return metrics


def calculate_regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    """
    Расчет метрик регрессии для оценки RUL
    
    Returns:
        Словарь с метриками: mae, mse, rmse, mape, r2
    """
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    
    mae = mean_absolute_error(y_true, y_pred)
    mse = mean_squared_error(y_true, y_pred)
    rmse = np.sqrt(mse)
    
    # MAPE (Mean Absolute Percentage Error)
    non_zero_mask = y_true != 0
    if non_zero_mask.any():
        mape = np.mean(np.abs((y_true[non_zero_mask] - y_pred[non_zero_mask]) / y_true[non_zero_mask])) * 100
    else:
        mape = float('inf')
    
    r2 = r2_score(y_true, y_pred)
    
    return {
        'mae': mae,
        'mse': mse,
        'rmse': rmse,
        'mape': mape,
        'r2': r2
    }


# ============================================================================
# Функции для работы с конфигурацией
# ============================================================================

def load_config_from_env(prefix: str = "FAILURE_") -> Dict[str, Any]:
    """
    Загрузка конфигурации из переменных окружения
    
    Args:
        prefix: Префикс переменных окружения
        
    Returns:
        Словарь с параметрами конфигурации
    """
    import os
    
    config = {}
    for key, value in os.environ.items():
        if key.startswith(prefix):
            config_key = key[len(prefix):].lower()
            
            # Преобразование значений
            if value.lower() in ('true', 'false'):
                config[config_key] = value.lower() == 'true'
            elif value.isdigit():
                config[config_key] = int(value)
            elif value.replace('.', '').isdigit() and value.count('.') <= 1:
                config[config_key] = float(value)
            else:
                config[config_key] = value
                
    return config


def merge_configs(default: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Рекурсивное слияние двух конфигураций"""
    result = default.copy()
    
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value
            
    return result


# ============================================================================
# Функции для работы с файлами
# ============================================================================

def ensure_directory(directory_path: Union[str, Path]) -> Path:
    """Создание директории, если она не существует"""
    path = Path(directory_path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_file_hash(file_path: Union[str, Path]) -> str:
    """Вычисление MD5 хэша файла"""
    hasher = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def save_dataframe_chunked(df: pd.DataFrame, file_path: Union[str, Path], 
                           chunk_size: int = 10000):
    """Сохранение DataFrame частями (для больших объемов)"""
    path = Path(file_path)
    ensure_directory(path.parent)
    
    num_chunks = (len(df) + chunk_size - 1) // chunk_size
    
    for i in range(num_chunks):
        start_idx = i * chunk_size
        end_idx = min((i + 1) * chunk_size, len(df))
        chunk = df.iloc[start_idx:end_idx]
        
        mode = 'w' if i == 0 else 'a'
        header = i == 0
        chunk.to_csv(path, mode=mode, header=header, index=False)
        
    logger.info(f"Saved {len(df)} rows to {file_path} in {num_chunks} chunks")


# ============================================================================
# Функции для форматирования вывода
# ============================================================================

def format_duration(seconds: float) -> str:
    """Форматирование длительности в человеко-читаемый формат"""
    if seconds < 60:
        return f"{seconds:.0f} сек"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f} мин"
    elif seconds < 86400:
        hours = seconds / 3600
        return f"{hours:.1f} ч"
    else:
        days = seconds / 86400
        return f"{days:.1f} дн"


def format_probability(prob: float, as_percent: bool = True) -> str:
    """Форматирование вероятности"""
    if as_percent:
        return f"{prob * 100:.1f}%"
    return f"{prob:.4f}"


def format_timestamp(dt: datetime, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Форматирование временной метки"""
    return dt.strftime(fmt)


# ============================================================================
# Функции для валидации данных
# ============================================================================

def validate_metric_value(value: float, metric_name: str = None) -> bool:
    """
    Проверка корректности значения метрики
    
    Args:
        value: Значение метрики
        metric_name: Имя метрики (для специфичных проверок)
        
    Returns:
        True если значение корректно
    """
    # Проверка на None и NaN
    if value is None or np.isnan(value):
        return False
    
    # Проверка на бесконечность
    if np.isinf(value):
        return False
    
    # Проверка диапазона для известных метрик
    if metric_name:
        if 'percent' in metric_name and (value < 0 or value > 100):
            return False
        if 'temperature' in metric_name and (value < -50 or value > 150):
            return False
            
    return True


def validate_timestamp(timestamp: datetime, max_future_seconds: int = 300) -> bool:
    """
    Проверка корректности временной метки
    
    Args:
        timestamp: Проверяемая временная метка
        max_future_seconds: Максимальное допустимое опережение текущего времени
        
    Returns:
        True если временная метка корректна
    """
    now = datetime.now()
    
    # Не может быть слишком старым (более года)
    if timestamp < now - timedelta(days=365):
        return False
    
    # Не может быть слишком далеко в будущем
    if timestamp > now + timedelta(seconds=max_future_seconds):
        return False
        
    return True


# ============================================================================
# Декораторы
# ============================================================================

def timing_decorator(func):
    """Декоратор для измерения времени выполнения функции"""
    import time
    
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        logger.debug(f"{func.__name__} executed in {(end_time - start_time)*1000:.2f} ms")
        return result
    return wrapper


def retry_on_failure(max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """
    Декоратор для повторного выполнения функции при ошибке
    
    Args:
        max_retries: Максимальное количество попыток
        delay: Начальная задержка между попытками (секунды)
        backoff: Множитель для увеличения задержки
    """
    import time
    
    def decorator(func):
        def wrapper(*args, **kwargs):
            current_delay = delay
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {current_delay}s")
                    time.sleep(current_delay)
                    current_delay *= backoff
            return None
        return wrapper
    return decorator