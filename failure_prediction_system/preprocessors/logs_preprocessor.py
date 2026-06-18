"""
Предобработка текстовых логов
"""

import re
import numpy as np
import pandas as pd
from typing import List, Dict, Any, Optional
from collections import Counter
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD

from collectors.base_collector import LogEntry
from utils.logger import get_logger

logger = get_logger(__name__)


class LogsPreprocessor:
    """Предобработчик логов"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.tfidf_vectorizer = TfidfVectorizer(
            max_features=100,
            stop_words='english',
            lowercase=True,
            token_pattern=r'\b[a-zA-Z]{3,}\b'
        )
        self.svd = TruncatedSVD(n_components=20, random_state=42)
        self.is_fitted = False
        
        # Маппинг уровней критичности
        self.level_map = {'DEBUG': 0, 'INFO': 1, 'WARNING': 2, 'ERROR': 3, 'CRITICAL': 4}
        
    def to_dataframe(self, logs: List[LogEntry]) -> pd.DataFrame:
        """Преобразование списка логов в DataFrame"""
        if not logs:
            return pd.DataFrame()
            
        df = pd.DataFrame([
            {
                'timestamp': l.timestamp,
                'source': l.source,
                'level': l.level,
                'message': l.message,
                'service': l.service,
                'host': l.host
            }
            for l in logs
        ])
        
        return df
    
    def clean_message(self, message: str) -> str:
        """Очистка сообщения лога"""
        # Удаление временных меток
        message = re.sub(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', '', message)
        message = re.sub(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', '', message)
        
        # Удаление IP-адресов
        message = re.sub(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', '', message)
        
        # Удаление UUID
        message = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '', message)
        
        # Приведение к нижнему регистру
        message = message.lower()
        
        # Удаление специальных символов
        message = re.sub(r'[^\w\s]', ' ', message)
        
        # Удаление лишних пробелов
        message = ' '.join(message.split())
        
        return message
    
    def encode_level(self, df: pd.DataFrame) -> pd.DataFrame:
        """Кодирование уровня критичности"""
        df['level_code'] = df['level'].map(self.level_map).fillna(1)
        return df
    
    def extract_error_patterns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Извлечение паттернов ошибок"""
        # Выделение сообщений с ошибками
        error_messages = df[df['level'].isin(['ERROR', 'CRITICAL'])]['cleaned_message'].tolist()
        
        if error_messages:
            # Подсчет частоты слов в ошибках
            all_words = ' '.join(error_messages).split()
            word_freq = Counter(all_words)
            common_words = {word for word, count in word_freq.items() if count > 5}
            
            # Вычисление score для каждого сообщения
            df['error_pattern_score'] = df['cleaned_message'].apply(
                lambda x: sum(1 for word in x.split() if word in common_words)
            )
        else:
            df['error_pattern_score'] = 0
            
        return df
    
    def vectorize(self, df: pd.DataFrame, fit: bool = True) -> pd.DataFrame:
        """Векторизация текстовых сообщений"""
        if df.empty or 'cleaned_message' not in df.columns:
            return df
            
        if fit:
            tfidf_matrix = self.tfidf_vectorizer.fit_transform(df['cleaned_message'])
            log_features = self.svd.fit_transform(tfidf_matrix)
            self.is_fitted = True
        else:
            tfidf_matrix = self.tfidf_vectorizer.transform(df['cleaned_message'])
            log_features = self.svd.transform(tfidf_matrix)
            
        # Добавление векторных признаков
        for i in range(log_features.shape[1]):
            df[f'log_feature_{i}'] = log_features[:, i]
            
        return df
    
    def aggregate_by_time(self, df: pd.DataFrame, interval: str = '10s') -> pd.DataFrame:
        """Агрегация логов по временным интервалам"""
        if df.empty:
            return df
            
        df['time_bucket'] = df['timestamp'].dt.floor(interval)
        
        # Агрегация
        aggregated = df.groupby('time_bucket').agg({
            'level_code': ['max', 'mean', 'count'],
            'error_pattern_score': 'mean'
        }).reset_index()
        
        aggregated.columns = ['timestamp', 'log_max_level', 'log_avg_level', 
                              'log_count', 'log_error_score']
        
        # Добавление векторных признаков
        vector_cols = [col for col in df.columns if col.startswith('log_feature_')]
        if vector_cols:
            vector_agg = df.groupby('time_bucket')[vector_cols].mean().reset_index()
            aggregated = aggregated.merge(vector_agg, on='timestamp', how='left')
            
        return aggregated
    
    def process(self, logs: List[LogEntry]) -> pd.DataFrame:
        """Полный цикл предобработки"""
        logger.info(f"Processing {len(logs)} logs")
        
        # Преобразование в DataFrame
        df = self.to_dataframe(logs)
        
        if df.empty:
            return df
            
        # Очистка сообщений
        df['cleaned_message'] = df['message'].apply(self.clean_message)
        
        # Кодирование уровня
        df = self.encode_level(df)
        
        # Извлечение паттернов ошибок
        df = self.extract_error_patterns(df)
        
        # Векторизация
        df = self.vectorize(df)
        
        # Агрегация по времени
        aggregated = self.aggregate_by_time(df)
        
        return aggregated