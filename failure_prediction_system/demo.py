"""
Демо-режим работы системы без внешних сервисов
Обновленная версия с поддержкой ансамблевого детектора аномалий
"""

import sys
import time
from datetime import datetime, timedelta
import random
import numpy as np
import pandas as pd

# Добавляем путь к проекту
sys.path.append('.')

from collectors.base_collector import MetricPoint, LogEntry
from preprocessors.metrics_preprocessor import MetricsPreprocessor
from preprocessors.logs_preprocessor import LogsPreprocessor
from preprocessors.data_synchronizer import DataSynchronizer
from models.ensemble_detector import EnsembleAnomalyDetector
from models.failure_predictor import FailurePredictor
from alerts.alert_manager import AlertManager
from utils.logger import setup_logger

# Настройка логирования
logger = setup_logger("demo", "INFO")


def generate_demo_metrics(num_points=500):
    """Генерация демо-метрик с эмуляцией деградации"""
    metrics = []
    start_time = datetime.now() - timedelta(hours=2)
    
    for i in range(num_points):
        current_time = start_time + timedelta(seconds=i * 10)
        
        # Эмуляция деградации в конце периода (последние 20% точек)
        if i > num_points * 0.8:
            # Деградация нарастает линейно
            degradation = (i - num_points * 0.8) / (num_points * 0.2) * 30
            cpu = min(100, 45 + degradation + random.gauss(0, 3))
            memory = min(100, 55 + degradation * 0.6 + random.gauss(0, 2))
            disk = 40 + degradation * 0.5 + random.gauss(0, 8)
            network = 85 + degradation * 0.3 + random.gauss(0, 10)
        else:
            # Нормальная работа с небольшими колебаниями
            cpu = 45 + random.gauss(0, 8)
            memory = 55 + random.gauss(0, 5)
            disk = 40 + random.gauss(0, 10)
            network = 85 + random.gauss(0, 12)
        
        # Ограничение значений
        cpu = max(0, min(100, cpu))
        memory = max(0, min(100, memory))
        disk = max(0, disk)
        network = max(0, network)
        
        metrics.append(MetricPoint(
            timestamp=current_time,
            metric_name='cpu_usage_percent',
            value=cpu,
            source='demo-server'
        ))
        
        metrics.append(MetricPoint(
            timestamp=current_time,
            metric_name='memory_usage_percent',
            value=memory,
            source='demo-server'
        ))
        
        metrics.append(MetricPoint(
            timestamp=current_time,
            metric_name='disk_io_mbps',
            value=disk,
            source='demo-server'
        ))
        
        metrics.append(MetricPoint(
            timestamp=current_time,
            metric_name='network_traffic_mbps',
            value=network,
            source='demo-server'
        ))
        
    return metrics


def generate_demo_logs(num_entries=200):
    """Генерация демо-логов с нарастанием ошибок"""
    logs = []
    start_time = datetime.now() - timedelta(hours=2)
    
    levels = ['INFO', 'WARNING', 'ERROR', 'CRITICAL']
    messages = {
        'INFO': ['Normal operation', 'Request processed', 'Cache hit', 'Authentication successful'],
        'WARNING': ['High latency detected', 'Memory usage increasing', 'Slow query', 'Retry attempt'],
        'ERROR': ['Connection timeout', 'Database error', 'API call failed', 'Resource unavailable'],
        'CRITICAL': ['System failure imminent', 'Resource exhaustion', 'Service degraded']
    }
    
    for i in range(num_entries):
        current_time = start_time + timedelta(seconds=random.randint(0, 7200))
        
        # Больше ошибок и предупреждений ближе к концу
        if i > num_entries * 0.9:
            level = 'ERROR' if random.random() > 0.3 else 'WARNING'
        elif i > num_entries * 0.7:
            level = 'WARNING' if random.random() > 0.5 else 'INFO'
        else:
            level = 'INFO' if random.random() > 0.1 else 'WARNING'
            
        logs.append(LogEntry(
            timestamp=current_time,
            source='demo-app',
            level=level,
            message=random.choice(messages[level]),
            service='demo-service',
            host='localhost'
        ))
        
    return logs


def demo_run():
    """Запуск демо-режима"""
    print("=" * 60)
    print("FAILURE PREDICTION SYSTEM - DEMO MODE")
    print("Ансамблевый детектор: Isolation Forest + LSTM-автоэнкодер")
    print("=" * 60)
    
    # Создание компонентов
    metrics_preprocessor = MetricsPreprocessor({})
    logs_preprocessor = LogsPreprocessor({})
    data_synchronizer = DataSynchronizer({'sync_interval': '10s'})
    
    # Ансамблевый детектор аномалий
    anomaly_detector = EnsembleAnomalyDetector({
        'contamination': 0.05,
        'n_estimators': 100,
        'sequence_length': 60,
        'lstm_hidden_size': 128,
        'lstm_num_layers': 2,
        'dropout_rate': 0.2,
        'learning_rate': 0.001,
        'epochs': 50,
        'isolation_weight': 0.3,
        'lstm_weight': 0.7,
        'high_confidence_threshold': 0.8
    })
    
    # Предиктор отказов
    failure_predictor = FailurePredictor({
        'sequence_length': 60,
        'batch_size': 32,
        'epochs': 30,
        'learning_rate': 0.001,
        'lstm_units': [64, 32, 16],
        'dropout_rate': 0.2,
        'random_forest_estimators': 100
    })
    
    # Менеджер оповещений
    alert_manager = AlertManager({'threshold': 0.6})
    
    print("\n[1] Generating demo data...")
    metrics = generate_demo_metrics(500)
    logs = generate_demo_logs(200)
    print(f"    Generated {len(metrics)} metric points and {len(logs)} log entries")
    
    print("\n[2] Preprocessing data...")
    metrics_df = metrics_preprocessor.process(metrics)
    logs_df = logs_preprocessor.process(logs)
    print(f"    Metrics shape: {metrics_df.shape}")
    print(f"    Logs shape: {logs_df.shape}")
    
    print("\n[3] Synchronizing data...")
    synchronized = data_synchronizer.synchronize(metrics_df, logs_df)
    print(f"    Synchronized data shape: {synchronized.shape}")
    
    print("\n[4] Training models...")
    
    # Обучение ансамблевого детектора аномалий
    anomaly_detector.train(synchronized)
    print("    Ensemble anomaly detector trained (IF + LSTM)")
    
    # Создание меток отказов для обучения предиктора
    if 'cpu_usage_percent' in synchronized.columns:
        failure_labels = (synchronized['cpu_usage_percent'] > 85).astype(int)
    else:
        failure_labels = pd.Series([0] * len(synchronized))
        
    X, y, features = data_synchronizer.create_training_set(synchronized, failure_labels)
    
    if X is not None and len(X) > 0:
        failure_predictor.train(X, y, features)
        print("    Failure predictor trained (XGBoost)")
    
    print("\n[5] Processing real-time data (simulation)...")
    
    # Симуляция работы в реальном времени
    for cycle in range(10):
        print(f"\n--- Cycle {cycle+1}/10 ---")
        
        # Генерация новых данных
        new_metrics = generate_demo_metrics(20)
        new_logs = generate_demo_logs(10)
        
        # Предобработка
        metrics_df = metrics_preprocessor.process(new_metrics)
        logs_df = logs_preprocessor.process(new_logs)
        synchronized = data_synchronizer.synchronize(metrics_df, logs_df)
        
        if not synchronized.empty:
            # Ансамблевое обнаружение аномалий
            with_anomalies = anomaly_detector.detect(synchronized)
            
            # Подсчет аномалий по каждому детектору
            if 'is_anomaly_ensemble' in with_anomalies.columns:
                anomaly_count = with_anomalies['is_anomaly_ensemble'].sum()
                if_count = with_anomalies['is_anomaly_if'].sum() if 'is_anomaly_if' in with_anomalies.columns else 0
                lstm_count = with_anomalies['is_anomaly_lstm'].sum() if 'is_anomaly_lstm' in with_anomalies.columns else 0
                print(f"    Anomalies detected: {anomaly_count} (IF: {if_count}, LSTM: {lstm_count})")
            else:
                anomaly_count = 0
                print(f"    Anomalies detected: 0")
            
            # Прогнозирование отказов
            numeric_cols = with_anomalies.select_dtypes(include=['float64', 'int64']).columns
            X_new = with_anomalies[numeric_cols].fillna(0).values
            
            if len(X_new) > 0:
                probability, details = failure_predictor.predict(X_new)
                
                # Расчет остаточного ресурса
                if probability > 0.5:
                    rul = 3600 * (1 - probability)
                else:
                    rul = 3600
                    
                # Оценка состояния
                if probability > 0.7:
                    status = "🔴 КРИТИЧЕСКИЙ РИСК!"
                elif probability > 0.4:
                    status = "🟡 ВНИМАНИЕ"
                else:
                    status = "🟢 НОРМА"
                    
                print(f"    Failure probability: {probability:.2%}")
                print(f"    Remaining useful life: {rul/60:.1f} minutes")
                print(f"    Status: {status}")
                
                # Отправка оповещения при высоком риске
                if probability > 0.6:
                    alert_manager.send_alert(
                        component="demo-system",
                        failure_type="predicted_failure",
                        probability=probability,
                        predicted_rul=rul,
                        contributing_metrics=list(failure_predictor.get_feature_importance().keys())[:3]
                    )
            else:
                print("    Insufficient data for prediction")
        
        time.sleep(2)
    
    print("\n" + "=" * 60)
    print("Demo completed successfully!")
    print("=" * 60)
    
    # Вывод важности признаков
    print("\nFeature Importance (top 5):")
    importance = failure_predictor.get_feature_importance()
    for feat, imp in list(importance.items())[:5]:
        print(f"  {feat}: {imp:.3f}")
    
    print("\nSystem summary:")
    print("  - Ансамблевый детектор: Isolation Forest + LSTM-автоэнкодер")
    print("  - Классификатор отказов: XGBoost")
    print("  - Синхронизация данных: 10-секундные окна")
    print("\nДля полноценного запуска с реальными данными:")
    print("  1. Установите Docker")
    print("  2. Запустите docker-compose up -d")
    print("  3. Настройте Prometheus и Elasticsearch")
    print("  4. Запустите python main.py")


if __name__ == "__main__":
    demo_run()