import numpy as np
import pandas as pd
from typing import Dict, Any, Tuple, List
from sklearn.preprocessing import StandardScaler

from models.anomaly_detector import AnomalyDetector as IsolationForestDetector
from models.lstm_autoencoder import LSTMAnomalyDetector
from utils.logger import get_logger

logger = get_logger(__name__)


class EnsembleAnomalyDetector:
    """
    Ансамблевый детектор аномалий, объединяющий:
    1. Isolation Forest - для быстрого обнаружения точечных выбросов (F1-мера 98-99.6%)
    2. LSTM-автоэнкодер - для выявления комплексных контекстуальных аномалий
    
    Правило агрегации: аномалия признается подтвержденной, если:
    - оба алгоритма согласны, ИЛИ
    - один алгоритм с высокой степенью уверенности (порог 0.8)
    
    Веса ансамбля: Isolation Forest - 0.3, LSTM - 0.7
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Компоненты ансамбля
        self.isolation_forest = IsolationForestDetector(config)
        self.lstm_autoencoder = LSTMAnomalyDetector(config)
        
        # Параметры
        self.sequence_length = config.get('sequence_length', 60)
        self.isolation_weight = config.get('isolation_weight', 0.3)
        self.lstm_weight = config.get('lstm_weight', 0.7)
        self.high_confidence_threshold = config.get('high_confidence_threshold', 0.8)
        
        self.is_trained = False
        self.scaler = StandardScaler()
        
    def train(self, data: pd.DataFrame):
        """
        Обучение ансамблевого детектора
        
        Процесс обучения соответствует разделу 3.4.1:
        - Шаг 5: обучение Isolation Forest
        - Шаг 6: обучение LSTM-автоэнкодера
        """
        if data.empty:
            logger.warning("Empty training data")
            return
            
        # Выбор числовых признаков
        numeric_cols = data.select_dtypes(include=[np.number]).columns
        X = data[numeric_cols].fillna(0).values
        
        # Нормализация (соответствует разделу 3.4.1, шаг 4)
        X_scaled = self.scaler.fit_transform(X)
        
        # Шаг 5: Обучение Isolation Forest
        logger.info("Training Isolation Forest component...")
        self.isolation_forest.train(data)
        
        # Создание последовательностей для LSTM-автоэнкодера
        X_sequences = []
        for i in range(len(X_scaled) - self.sequence_length):
            X_sequences.append(X_scaled[i:i + self.sequence_length])
        
        if len(X_sequences) < 10:
            logger.warning(f"Not enough data for LSTM autoencoder: {len(X_sequences)} sequences")
            self.is_trained = True
            return
            
        X_sequences = np.array(X_sequences)
        
        # Шаг 6: Обучение LSTM-автоэнкодера
        logger.info(f"Training LSTM autoencoder on {len(X_sequences)} sequences...")
        self.lstm_autoencoder.train(X_sequences)
        
        self.is_trained = True
        logger.info("Ensemble detector training completed")
        
    def detect(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Обнаружение аномалий с ансамблированием результатов
        
        Процесс инференса соответствует разделу 3.4.2
        
        Returns:
            DataFrame с добавленными колонками:
            - is_anomaly_if: аномалия по Isolation Forest
            - is_anomaly_lstm: аномалия по LSTM
            - is_anomaly_ensemble: итоговая аномалия (правило агрегации)
            - anomaly_score_ensemble: взвешенная оценка
            - anomaly_confidence: уверенность в определении
        """
        if not self.is_trained:
            logger.warning("Ensemble detector not trained")
            return data
            
        if data.empty:
            return data
            
        # Выбор числовых признаков
        numeric_cols = data.select_dtypes(include=[np.number]).columns
        X = data[numeric_cols].fillna(0).values
        
        # Нормализация
        X_scaled = self.scaler.transform(X)
        
        # 1. Обнаружение аномалий Isolation Forest (точечные выбросы)
        if_data = self.isolation_forest.detect(data)
        if_anomalies = if_data['is_anomaly'].values if 'is_anomaly' in if_data.columns else np.zeros(len(data), dtype=bool)
        if_scores = if_data['anomaly_score'].values if 'anomaly_score' in if_data.columns else np.zeros(len(data))
        
        # Нормализация iForest scores в диапазон [0,1]
        if_scores_min = if_scores.min()
        if_scores_max = if_scores.max()
        if if_scores_max > if_scores_min:
            if_scores_norm = (if_scores - if_scores_min) / (if_scores_max - if_scores_min)
        else:
            if_scores_norm = np.zeros_like(if_scores)
        
        # 2. Обнаружение аномалий LSTM-автоэнкодером (контекстуальные отклонения)
        lstm_anomalies = np.zeros(len(data), dtype=bool)
        lstm_scores = np.zeros(len(data))
        
        if len(X_scaled) >= self.sequence_length:
            # Создание скользящих окон
            X_sequences = []
            for i in range(len(X_scaled) - self.sequence_length + 1):
                X_sequences.append(X_scaled[i:i + self.sequence_length])
            
            if X_sequences:
                X_sequences = np.array(X_sequences)
                is_anom, scores = self.lstm_autoencoder.detect(X_sequences)
                
                # Выравнивание длины (первые (sequence_length-1) точек не имеют прогноза)
                lstm_anomalies[self.sequence_length - 1:] = is_anom
                lstm_scores[self.sequence_length - 1:] = scores
                
                # Интерполяция для первых точек
                if len(lstm_scores) > self.sequence_length - 1:
                    first_valid_score = lstm_scores[self.sequence_length - 1]
                    lstm_scores[:self.sequence_length - 1] = first_valid_score
        
        # Нормализация LSTM scores
        lstm_scores_max = lstm_scores.max()
        if lstm_scores_max > 0:
            lstm_scores_norm = lstm_scores / lstm_scores_max
        else:
            lstm_scores_norm = lstm_scores
        
        # 3. Ансамблирование с взвешенным подходом
        anomaly_scores_combined = (self.isolation_weight * if_scores_norm + 
                                   self.lstm_weight * lstm_scores_norm)
        
        # Правило агрегации (раздел 3.4.2, шаг 6)
        both_anomalies = if_anomalies & lstm_anomalies
        
        # Высокая уверенность: оценка > порога 0.8
        if_high_confidence = if_scores_norm > self.high_confidence_threshold
        lstm_high_confidence = lstm_scores_norm > self.high_confidence_threshold
        
        ensemble_anomalies = both_anomalies | (if_high_confidence & lstm_anomalies) | (if_anomalies & lstm_high_confidence)
        
        # Добавление результатов в DataFrame
        data['is_anomaly_if'] = if_anomalies
        data['is_anomaly_lstm'] = lstm_anomalies
        data['is_anomaly_ensemble'] = ensemble_anomalies
        data['anomaly_score_if'] = if_scores_norm
        data['anomaly_score_lstm'] = lstm_scores_norm
        data['anomaly_score_ensemble'] = anomaly_scores_combined
        data['anomaly_confidence'] = np.maximum(if_scores_norm, lstm_scores_norm)
        
        anomaly_count = ensemble_anomalies.sum()
        if_count = if_anomalies.sum()
        lstm_count = lstm_anomalies.sum()
        
        logger.info(f"Ensemble detector found {anomaly_count} anomalies "
                   f"(IF: {if_count}, LSTM: {lstm_count})")
        
        return data
    
    def save(self, path_prefix: str):
        """Сохранение компонентов ансамбля"""
        self.isolation_forest.save(f"{path_prefix}_if.pkl")
        self.lstm_autoencoder.save(f"{path_prefix}_lstm.pt")
        logger.info(f"Ensemble detector saved to {path_prefix}")
        
    def load(self, path_prefix: str):
        """Загрузка компонентов ансамбля"""
        self.isolation_forest.load(f"{path_prefix}_if.pkl")
        self.lstm_autoencoder.load(f"{path_prefix}_lstm.pt")
        self.is_trained = True
        logger.info(f"Ensemble detector loaded from {path_prefix}")