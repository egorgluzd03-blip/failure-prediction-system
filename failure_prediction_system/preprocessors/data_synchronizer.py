"""
Синхронизация метрик и логов
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from datetime import datetime

from utils.logger import get_logger

logger = get_logger(__name__)


class DataSynchronizer:
    """Синхронизатор данных"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.interval = config.get('sync_interval', '10s')
        
    def synchronize(self, metrics_df: pd.DataFrame, logs_df: pd.DataFrame) -> pd.DataFrame:
        """
        Синхронизация метрик и логов по времени
        
        Args:
            metrics_df: DataFrame с метриками
            logs_df: DataFrame с логами
            
        Returns:
            Синхронизированный DataFrame
        """
        if metrics_df.empty:
            logger.warning("Metrics DataFrame is empty")
            return logs_df if not logs_df.empty else pd.DataFrame()
            
        if logs_df.empty:
            logger.warning("Logs DataFrame is empty")
            return metrics_df
            
        # Установка временного индекса
        metrics_df = metrics_df.set_index('timestamp')
        logs_df = logs_df.set_index('timestamp')
        
        # Ресемплирование на общий интервал
        metrics_resampled = metrics_df.resample(self.interval).mean()
        logs_resampled = logs_df.resample(self.interval).mean()
        
        # Объединение данных
        synchronized = metrics_resampled.join(logs_resampled, how='outer')
        
        # Заполнение пропусков
        synchronized = synchronized.fillna(method='ffill').fillna(0)
        
        # Сброс индекса
        synchronized = synchronized.reset_index()
        
        logger.info(f"Synchronized data: {len(synchronized)} rows")
        
        return synchronized
    
    def create_training_set(
        self, 
        synchronized_data: pd.DataFrame,
        failure_labels: pd.Series = None,
        label_column: str = None
    ) -> tuple:
        """
        Создание обучающей выборки
        
        Args:
            synchronized_data: Синхронизированные данные
            failure_labels: Метки отказов
            label_column: Название колонки с метками
            
        Returns:
            Кортеж (признаки, метки)
        """
        if synchronized_data.empty:
            return None, None
            
        # Выбор признаков (все числовые колонки)
        feature_cols = synchronized_data.select_dtypes(include=[np.number]).columns.tolist()
        
        # Исключение колонок, которые не должны быть признаками
        exclude_cols = ['log_max_level', 'log_avg_level', 'log_count', 'log_error_score']
        feature_cols = [col for col in feature_cols if col not in exclude_cols]
        
        X = synchronized_data[feature_cols].fillna(0).values
        
        if failure_labels is not None:
            y = failure_labels.values
        elif label_column and label_column in synchronized_data.columns:
            y = synchronized_data[label_column].values
        else:
            y = None
            
        return X, y, feature_cols