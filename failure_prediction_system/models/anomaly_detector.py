"""
Обнаружение аномалий
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, Tuple
import pickle
from sklearn.ensemble import IsolationForest

from utils.logger import get_logger

logger = get_logger(__name__)


class AnomalyDetector:
    """Детектор аномалий на основе Isolation Forest"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.contamination = config.get('contamination', 0.05)
        self.n_estimators = config.get('n_estimators', 100)
        self.random_state = config.get('random_state', 42)
        
        self.model = IsolationForest(
            contamination=self.contamination,
            n_estimators=self.n_estimators,
            random_state=self.random_state,
            n_jobs=-1
        )
        self.is_trained = False
        
    def train(self, data: pd.DataFrame):
        """Обучение модели на данных нормальной работы"""
        if data.empty:
            logger.warning("Empty training data")
            return
            
        # Выбор числовых признаков
        numeric_cols = data.select_dtypes(include=[np.number]).columns
        X = data[numeric_cols].fillna(0).values
        
        logger.info(f"Training anomaly detector on {len(X)} samples")
        
        self.model.fit(X)
        self.is_trained = True
        
        logger.info("Anomaly detector training completed")
        
    def detect(self, data: pd.DataFrame) -> pd.DataFrame:
        """Обнаружение аномалий"""
        if not self.is_trained:
            logger.warning("Anomaly detector not trained")
            return data
            
        if data.empty:
            return data
            
        # Выбор числовых признаков
        numeric_cols = data.select_dtypes(include=[np.number]).columns
        X = data[numeric_cols].fillna(0).values
        
        # Предсказание
        predictions = self.model.predict(X)
        scores = self.model.score_samples(X)
        
        data['is_anomaly'] = predictions == -1
        data['anomaly_score'] = scores
        
        anomaly_count = data['is_anomaly'].sum()
        logger.info(f"Detected {anomaly_count} anomalies")
        
        return data
    
    def save(self, path: str):
        """Сохранение модели"""
        with open(path, 'wb') as f:
            pickle.dump(self.model, f)
        logger.info(f"Model saved to {path}")
        
    def load(self, path: str):
        """Загрузка модели"""
        with open(path, 'rb') as f:
            self.model = pickle.load(f)
        self.is_trained = True
        logger.info(f"Model loaded from {path}")