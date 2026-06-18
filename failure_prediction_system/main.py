"""
Основной модуль системы прогнозирования отказов
Обновленная версия с поддержкой:
- LSTM-автоэнкодера вместо бинарного LSTM
- Ансамблевого детектора аномалий
- Kafka для буферизации
- PostgreSQL для долгосрочного хранения
"""

import sys
import time
import signal
import pandas as pd
from datetime import datetime

from config.settings import config
from collectors.prometheus_collector import PrometheusCollector
from collectors.elasticsearch_collector import ElasticsearchCollector
from collectors.kafka_producer import KafkaMetricsProducer, KafkaLogsProducer
from preprocessors.metrics_preprocessor import MetricsPreprocessor
from preprocessors.logs_preprocessor import LogsPreprocessor
from preprocessors.data_synchronizer import DataSynchronizer
from models.ensemble_detector import EnsembleAnomalyDetector
from models.failure_predictor import FailurePredictor
from alerts.alert_manager import AlertManager
from database.postgres_client import PostgresClient
from utils.database import Database as SQLiteDB
from utils.logger import setup_logger, get_logger

# Настройка логирования
setup_logger("failure_prediction", level=config.log_level)
logger = get_logger("failure_prediction")


class FailurePredictionSystem:
    """Основной класс системы прогнозирования отказов"""
    
    def __init__(self):
        logger.info("Initializing Failure Prediction System")
        
        # Инициализация коллекторов
        self.metrics_collector = PrometheusCollector({
            'url': config.prometheus.url,
            'servers': config.prometheus.servers,
            'timeout': config.prometheus.timeout
        })
        
        self.logs_collector = ElasticsearchCollector({
            'hosts': config.elasticsearch.hosts,
            'api_key': config.elasticsearch.api_key,
            'index_pattern': config.elasticsearch.index_pattern,
            'services': config.elasticsearch.services
        })
        
        # Инициализация Kafka продюсеров
        if config.kafka.enabled:
            self.metrics_producer = KafkaMetricsProducer(
                config.kafka.bootstrap_servers,
                topic='raw-metrics'
            )
            self.logs_producer = KafkaLogsProducer(
                config.kafka.bootstrap_servers,
                topic='raw-logs'
            )
        else:
            self.metrics_producer = None
            self.logs_producer = None
            
        # Инициализация препроцессоров
        self.metrics_preprocessor = MetricsPreprocessor({})
        self.logs_preprocessor = LogsPreprocessor({})
        self.data_synchronizer = DataSynchronizer({'sync_interval': '10s'})
        
        # Инициализация детектора аномалий (ансамбль)
        self.anomaly_detector = EnsembleAnomalyDetector({
            'contamination': config.models.contamination,
            'n_estimators': config.models.isolation_forest_estimators,
            'sequence_length': config.models.sequence_length,
            'lstm_hidden_size': 128,
            'lstm_num_layers': 2,
            'dropout_rate': config.models.dropout_rate,
            'learning_rate': config.models.learning_rate,
            'epochs': config.models.epochs,
            'isolation_weight': 0.3,
            'lstm_weight': 0.7,
            'high_confidence_threshold': 0.8
        })
        
        # Инициализация предиктора отказов
        self.failure_predictor = FailurePredictor({
            'sequence_length': config.models.sequence_length,
            'batch_size': config.models.batch_size,
            'epochs': config.models.epochs,
            'learning_rate': config.models.learning_rate,
            'lstm_units': config.models.lstm_units,
            'dropout_rate': config.models.dropout_rate,
            'random_forest_estimators': config.models.random_forest_estimators
        })
        
        # Инициализация менеджера оповещений
        self.alert_manager = AlertManager({
            'email_enabled': config.alerts.email_enabled,
            'telegram_enabled': config.alerts.telegram_enabled,
            'threshold': config.alerts.failure_threshold
        })
        
        # Инициализация баз данных
        self.postgres = PostgresClient({
            'host': config.postgres.host,
            'port': config.postgres.port,
            'database': config.postgres.database,
            'user': config.postgres.user,
            'password': config.postgres.password
        })
        
        self.sqlite = SQLiteDB('failure_prediction.db')
        
        self.is_running = False
        
    def train(self, hours: int = None):
        """Обучение системы"""
        hours = hours or config.training_hours
        logger.info(f"Starting training with {hours} hours of data")
        
        # Сбор исторических данных
        historical_metrics = self.metrics_collector.collect_historical(hours)
        historical_logs = self.logs_collector.collect_historical(hours)
        
        # Сохранение в PostgreSQL для долгосрочного хранения
        if historical_metrics:
            self.postgres.insert_metrics([m.to_dict() for m in historical_metrics])
            
        # Предобработка и синхронизация
        metrics_df = self.metrics_preprocessor.process(historical_metrics)
        logs_df = self.logs_preprocessor.process(historical_logs)
        synchronized = self.data_synchronizer.synchronize(metrics_df, logs_df)
        
        # Обучение ансамблевого детектора аномалий
        logger.info("Training ensemble anomaly detector...")
        self.anomaly_detector.train(synchronized)
        
        # Подготовка данных для обучения предиктора отказов
        if 'cpu_usage_percent' in synchronized.columns:
            failure_labels = (synchronized['cpu_usage_percent'] > 90) | \
                            (synchronized.get('memory_usage_percent', 0) > 95)
            failure_labels = failure_labels.astype(int)
        else:
            failure_labels = pd.Series([0] * len(synchronized))
            
        X, y, feature_names = self.data_synchronizer.create_training_set(
            synchronized, failure_labels
        )
        
        # Обучение предиктора отказов
        if X is not None:
            self.failure_predictor.train(X, y, feature_names)
            
        logger.info("Training completed successfully")
        
    def process_realtime(self):
        """Обработка данных в реальном времени"""
        # Сбор данных
        metrics = self.metrics_collector.collect()
        logs = self.logs_collector.collect()
        
        # Отправка в Kafka при наличии
        if self.metrics_producer and metrics:
            self.metrics_producer.send_metrics(metrics)
        if self.logs_producer and logs:
            self.logs_producer.send_logs(logs)
            
        # Предобработка
        metrics_df = self.metrics_preprocessor.process(metrics)
        logs_df = self.logs_preprocessor.process(logs)
        synchronized = self.data_synchronizer.synchronize(metrics_df, logs_df)
        
        if synchronized.empty:
            return None
            
        # Ансамблевое обнаружение аномалий
        anomaly_result = self.anomaly_detector.detect(synchronized)
        
        # Прогнозирование отказов
        numeric_cols = anomaly_result.select_dtypes(include=['float64', 'int64']).columns
        X = anomaly_result[numeric_cols].fillna(0).values
        
        if len(X) > 0:
            probability, details = self.failure_predictor.predict(X)
            
            # Оценка RUL
            if probability > 0.5:
                rul = 3600 * (1 - probability)
            else:
                rul = 3600
                
            # Отправка оповещения
            if probability > config.alerts.failure_threshold:
                self.alert_manager.send_alert(
                    component="system",
                    failure_type="predicted_failure",
                    probability=probability,
                    predicted_rul=rul
                )
                
            return {
                'probability': probability,
                'rul': rul,
                'anomaly_count': anomaly_result['is_anomaly_ensemble'].sum() if 'is_anomaly_ensemble' in anomaly_result.columns else 0
            }
            
        return None