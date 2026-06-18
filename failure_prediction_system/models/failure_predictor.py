"""
Прогнозирование отказов
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple
import pickle
import json

from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, roc_auc_score

import tensorflow as tf
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import LSTM, Dense, Dropout, GRU, Bidirectional
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint
from tensorflow.keras.optimizers import Adam

from utils.logger import get_logger

logger = get_logger(__name__)


class FailurePredictor:
    """Прогнозировщик отказов"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.sequence_length = config.get('sequence_length', 60)
        self.batch_size = config.get('batch_size', 32)
        self.epochs = config.get('epochs', 50)
        self.learning_rate = config.get('learning_rate', 0.001)
        self.lstm_units = config.get('lstm_units', [128, 64, 32])
        self.dropout_rate = config.get('dropout_rate', 0.2)
        
        self.rf_model = RandomForestClassifier(
            n_estimators=config.get('random_forest_estimators', 100),
            max_depth=config.get('random_forest_max_depth', 10),
            random_state=42,
            n_jobs=-1
        )
        self.lstm_model = None
        self.scaler = StandardScaler()
        self.feature_names = []
        self.is_trained = False
        
    def _create_sequences(self, data: np.ndarray, labels: np.ndarray = None) -> Tuple:
        """Создание последовательностей для LSTM"""
        X, y = [], []
        
        for i in range(len(data) - self.sequence_length):
            X.append(data[i:i + self.sequence_length])
            if labels is not None:
                y.append(labels[i + self.sequence_length])
                
        X = np.array(X)
        y = np.array(y) if labels is not None else None
        
        return X, y
    
    def _build_lstm_model(self, input_shape: Tuple[int, int]) -> Sequential:
        """Построение архитектуры LSTM"""
        model = Sequential()
        
        # Первый Bidirectional LSTM слой
        model.add(Bidirectional(
            LSTM(self.lstm_units[0], return_sequences=True),
            input_shape=input_shape
        ))
        model.add(Dropout(self.dropout_rate))
        
        # Второй Bidirectional LSTM слой
        model.add(Bidirectional(
            LSTM(self.lstm_units[1], return_sequences=True)
        ))
        model.add(Dropout(self.dropout_rate))
        
        # Третий LSTM слой
        model.add(LSTM(self.lstm_units[2]))
        model.add(Dropout(self.dropout_rate))
        
        # Выходной слой
        model.add(Dense(16, activation='relu'))
        model.add(Dense(1, activation='sigmoid'))
        
        # Компиляция
        model.compile(
            optimizer=Adam(learning_rate=self.learning_rate),
            loss='binary_crossentropy',
            metrics=['accuracy', tf.keras.metrics.AUC()]
        )
        
        return model
    
    def _extract_sequence_features(self, X: np.ndarray) -> np.ndarray:
        """Извлечение статистических признаков из последовательностей"""
        features = []
        
        for seq in X:
            stats = np.concatenate([
                seq.mean(axis=0),
                seq.std(axis=0),
                seq.max(axis=0),
                seq.min(axis=0),
                np.percentile(seq, 95, axis=0)
            ])
            features.append(stats)
            
        return np.array(features)
    
    def train(self, X: np.ndarray, y: np.ndarray, feature_names: List[str] = None):
        """Обучение моделей прогнозирования"""
        if X is None or len(X) == 0:
            logger.warning("Empty training data")
            return
            
        self.feature_names = feature_names or [f'feature_{i}' for i in range(X.shape[1])]
        
        logger.info(f"Training failure predictor on {len(X)} samples")
        
        # Нормализация
        X_scaled = self.scaler.fit_transform(X)
        
        # Создание последовательностей для LSTM
        X_seq, y_seq = self._create_sequences(X_scaled, y)
        
        if len(X_seq) > 0:
            # Разделение на обучающую и валидационную выборки
            split_idx = int(len(X_seq) * 0.8)
            X_train_seq, X_val_seq = X_seq[:split_idx], X_seq[split_idx:]
            y_train_seq, y_val_seq = y_seq[:split_idx], y_seq[split_idx:]
            
            # Обучение LSTM
            self.lstm_model = self._build_lstm_model(
                (self.sequence_length, X_scaled.shape[1])
            )
            
            early_stopping = EarlyStopping(
                monitor='val_loss',
                patience=10,
                restore_best_weights=True
            )
            
            model_checkpoint = ModelCheckpoint(
                'best_lstm_model.h5',
                monitor='val_accuracy',
                save_best_only=True
            )
            
            self.lstm_model.fit(
                X_train_seq, y_train_seq,
                validation_data=(X_val_seq, y_val_seq),
                epochs=self.epochs,
                batch_size=self.batch_size,
                callbacks=[early_stopping, model_checkpoint],
                verbose=1
            )
            
        # Обучение Random Forest на агрегированных признаках
        if len(X_seq) > 0:
            seq_features = self._extract_sequence_features(X_seq)
            self.rf_model.fit(seq_features, y_seq)
        else:
            self.rf_model.fit(X_scaled, y)
            
        self.is_trained = True
        logger.info("Failure predictor training completed")
        
    def predict(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Прогнозирование отказов"""
        if not self.is_trained:
            logger.warning("Failure predictor not trained")
            return np.array([0.5]), np.array([0.5])
            
        # Нормализация
        X_scaled = self.scaler.transform(X)
        
        # LSTM прогноз
        lstm_prob = np.array([0.5])
        if self.lstm_model and len(X_scaled) >= self.sequence_length:
            X_seq = X_scaled[-self.sequence_length:].reshape(
                1, self.sequence_length, -1
            )
            lstm_prob = self.lstm_model.predict(X_seq, verbose=0)[0][0]
            
        # Random Forest прогноз
        if len(X_scaled) >= self.sequence_length:
            X_seq_all = X_scaled.reshape(1, -1, X_scaled.shape[1])
            # Создание скользящих окон для последней последовательности
            if len(X_scaled) >= self.sequence_length:
                last_seq = X_scaled[-self.sequence_length:]
                seq_features = self._extract_sequence_features(last_seq.reshape(1, self.sequence_length, -1))
                rf_prob = self.rf_model.predict_proba(seq_features)[0][1]
            else:
                rf_prob = self.rf_model.predict_proba(X_scaled.reshape(1, -1))[0][1]
        else:
            rf_prob = self.rf_model.predict_proba(X_scaled.reshape(1, -1))[0][1]
            
        # Комбинированный прогноз
        combined_prob = (float(lstm_prob) + float(rf_prob)) / 2
        
        return combined_prob, [lstm_prob, rf_prob]
    
    def get_feature_importance(self) -> Dict[str, float]:
        """Получение важности признаков"""
        if not self.is_trained:
            return {}
            
        importance = {}
        if hasattr(self.rf_model, 'feature_importances_'):
            for name, imp in zip(self.feature_names, self.rf_model.feature_importances_):
                importance[name] = float(imp)
                
        return dict(sorted(importance.items(), key=lambda x: x[1], reverse=True)[:10])
    
    def save(self, path_prefix: str):
        """Сохранение моделей"""
        with open(f"{path_prefix}_rf.pkl", 'wb') as f:
            pickle.dump(self.rf_model, f)
        with open(f"{path_prefix}_scaler.pkl", 'wb') as f:
            pickle.dump(self.scaler, f)
        with open(f"{path_prefix}_features.json", 'w') as f:
            json.dump(self.feature_names, f)
            
        if self.lstm_model:
            self.lstm_model.save(f"{path_prefix}_lstm.h5")
            
        logger.info(f"Models saved to {path_prefix}")
        
    def load(self, path_prefix: str):
        """Загрузка моделей"""
        with open(f"{path_prefix}_rf.pkl", 'rb') as f:
            self.rf_model = pickle.load(f)
        with open(f"{path_prefix}_scaler.pkl", 'rb') as f:
            self.scaler = pickle.load(f)
        with open(f"{path_prefix}_features.json", 'r') as f:
            self.feature_names = json.load(f)
            
        try:
            self.lstm_model = load_model(f"{path_prefix}_lstm.h5")
        except:
            self.lstm_model = None
            
        self.is_trained = True
        logger.info(f"Models loaded from {path_prefix}")