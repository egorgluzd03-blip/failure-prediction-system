"""
Предобработка временных рядов метрик
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Any, Optional
from datetime import datetime
from sklearn.preprocessing import StandardScaler

from collectors.base_collector import MetricPoint
from utils.logger import get_logger

logger = get_logger(__name__)


class MetricsPreprocessor:
    """Предобработчик метрик"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.scaler = StandardScaler()
        self.is_fitted = False
        
    def to_dataframe(self, metrics: List[MetricPoint]) -> pd.DataFrame:
        """Преобразование списка метрик в DataFrame"""
        if not metrics:
            return pd.DataFrame()
            
        df = pd.DataFrame([
            {
                'timestamp': m.timestamp,
                'source': m.source,
                'metric': m.metric_name,
                'value': m.value
            }
            for m in metrics
        ])
        
        # Создание сводной таблицы
        pivot_df = df.pivot_table(
            index=['timestamp', 'source'],
            columns='metric',
            values='value'
        ).reset_index()
        
        return pivot_df
    
    def interpolate(self, df: pd.DataFrame, method: str = 'linear') -> pd.DataFrame:
        """Интерполяция пропущенных значений"""
        if df.empty:
            return df
            
        df = df.set_index('timestamp')
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        
        for col in numeric_cols:
            df[col] = df[col].interpolate(method=method, limit_direction='both')
            
        return df.reset_index()
    
    def remove_outliers(self, df: pd.DataFrame, method: str = 'iqr') -> pd.DataFrame:
        """Удаление выбросов"""
        if df.empty:
            return df
            
        df_out = df.copy()
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        
        for col in numeric_cols:
            if method == 'iqr':
                Q1 = df[col].quantile(0.25)
                Q3 = df[col].quantile(0.75)
                IQR = Q3 - Q1
                lower_bound = Q1 - 1.5 * IQR
                upper_bound = Q3 + 1.5 * IQR
                df_out[col] = df[col].clip(lower_bound, upper_bound)
            elif method == 'zscore':
                mean = df[col].mean()
                std = df[col].std()
                df_out[col] = df[col].clip(mean - 3*std, mean + 3*std)
                
        return df_out
    
    def create_features(self, df: pd.DataFrame, windows: List[int] = [5, 10, 30]) -> pd.DataFrame:
        """Создание дополнительных признаков"""
        if df.empty:
            return df
            
        df_feat = df.copy()
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        
        for col in numeric_cols:
            for window in windows:
                df_feat[f'{col}_rolling_mean_{window}'] = df_feat[col].rolling(window, min_periods=1).mean()
                df_feat[f'{col}_rolling_std_{window}'] = df_feat[col].rolling(window, min_periods=1).std()
                df_feat[f'{col}_rate_of_change'] = df_feat[col].diff()
                
        return df_feat
    
    def normalize(self, df: pd.DataFrame, fit: bool = True) -> pd.DataFrame:
        """Нормализация данных"""
        if df.empty:
            return df
            
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        df_norm = df.copy()
        
        if fit:
            self.scaler.fit(df[numeric_cols].fillna(0))
            self.is_fitted = True
            
        scaled_data = self.scaler.transform(df[numeric_cols].fillna(0))
        
        for i, col in enumerate(numeric_cols):
            df_norm[col] = scaled_data[:, i]
            
        return df_norm
    
    def process(self, metrics: List[MetricPoint]) -> pd.DataFrame:
        """Полный цикл предобработки"""
        logger.info(f"Processing {len(metrics)} metrics")
        
        # Преобразование в DataFrame
        df = self.to_dataframe(metrics)
        
        if df.empty:
            return df
            
        # Интерполяция
        df = self.interpolate(df)
        
        # Удаление выбросов
        df = self.remove_outliers(df)
        
        # Создание признаков
        df = self.create_features(df)
        
        return df