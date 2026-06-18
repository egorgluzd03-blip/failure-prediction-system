import sqlite3
import json
import pandas as pd
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from contextlib import contextmanager
from pathlib import Path

from utils.logger import get_logger

logger = get_logger(__name__)


class SQLiteClient:
    """
    Клиент для работы с SQLite.
    Используется для оперативного хранения:
    - результатов прогнозирования
    - состояния моделей
    - истории оповещений
    """
    
    def __init__(self, db_path: str = "failure_prediction.db"):
        self.db_path = db_path
        self._init_database()
        
    @contextmanager
    def get_connection(self):
        """Контекстный менеджер для соединения с БД"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"SQLite error: {e}")
            raise
        finally:
            conn.close()
            
    def _init_database(self):
        """Инициализация таблиц (соответствует разделу 3.3.1)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица прогнозов (оперативное хранение)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP NOT NULL,
                    component TEXT NOT NULL,
                    failure_type TEXT NOT NULL,
                    probability REAL NOT NULL,
                    predicted_rul REAL NOT NULL,
                    confidence_lower REAL,
                    confidence_upper REAL,
                    contributing_metrics TEXT,
                    contributing_log_patterns TEXT
                )
            """)
            
            # Таблица для хранения метаинформации о моделях
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS model_metadata (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_type TEXT NOT NULL,
                    version TEXT NOT NULL,
                    trained_at TIMESTAMP NOT NULL,
                    file_path TEXT NOT NULL,
                    hyperparameters TEXT,
                    metrics TEXT,
                    is_active INTEGER DEFAULT 0
                )
            """)
            
            # Таблица для истории оповещений
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP NOT NULL,
                    component TEXT NOT NULL,
                    failure_type TEXT NOT NULL,
                    probability REAL NOT NULL,
                    predicted_rul REAL NOT NULL,
                    message TEXT,
                    status TEXT DEFAULT 'sent',
                    acknowledged INTEGER DEFAULT 0
                )
            """)
            
            # Таблица для состояния системы (буфер последних окон)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS system_state (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP
                )
            """)
            
            # Создание индексов для ускорения запросов
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_predictions_timestamp ON predictions(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_predictions_component ON predictions(component)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON alerts(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status)")
            
            logger.info(f"SQLite database initialized at {self.db_path}")
            
    # ==================== Методы для работы с прогнозами ====================
    
    def save_prediction(self, prediction: Dict[str, Any]) -> int:
        """
        Сохранение прогноза в SQLite
        
        Args:
            prediction: Словарь с полями:
                - timestamp
                - component
                - failure_type
                - probability
                - predicted_rul
                - confidence_lower (опционально)
                - confidence_upper (опционально)
                - contributing_metrics (опционально)
                - contributing_log_patterns (опционально)
        
        Returns:
            ID сохраненной записи
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Преобразование списков в JSON
            contributing_metrics = json.dumps(prediction.get('contributing_metrics', []))
            contributing_logs = json.dumps(prediction.get('contributing_log_patterns', []))
            
            cursor.execute("""
                INSERT INTO predictions 
                (timestamp, component, failure_type, probability, predicted_rul, 
                 confidence_lower, confidence_upper, contributing_metrics, contributing_log_patterns)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                prediction.get('timestamp', datetime.now()),
                prediction.get('component', 'unknown'),
                prediction.get('failure_type', 'normal'),
                prediction.get('probability', 0.0),
                prediction.get('predicted_rul', 3600),
                prediction.get('confidence_lower'),
                prediction.get('confidence_upper'),
                contributing_metrics,
                contributing_logs
            ))
            
            return cursor.lastrowid
            
    def get_recent_predictions(self, limit: int = 100, component: str = None) -> List[Dict]:
        """Получение последних прогнозов"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if component:
                cursor.execute("""
                    SELECT * FROM predictions 
                    WHERE component = ? 
                    ORDER BY timestamp DESC 
                    LIMIT ?
                """, (component, limit))
            else:
                cursor.execute("""
                    SELECT * FROM predictions 
                    ORDER BY timestamp DESC 
                    LIMIT ?
                """, (limit,))
                
            rows = cursor.fetchall()
            predictions = []
            for row in rows:
                pred = dict(row)
                # Десериализация JSON
                if pred.get('contributing_metrics'):
                    pred['contributing_metrics'] = json.loads(pred['contributing_metrics'])
                if pred.get('contributing_log_patterns'):
                    pred['contributing_log_patterns'] = json.loads(pred['contributing_log_patterns'])
                predictions.append(pred)
                
            return predictions
            
    def get_predictions_by_time_range(self, start_time: datetime, end_time: datetime) -> List[Dict]:
        """Получение прогнозов за временной интервал"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM predictions 
                WHERE timestamp BETWEEN ? AND ?
                ORDER BY timestamp ASC
            """, (start_time, end_time))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
            
    # ==================== Методы для работы с моделями ====================
    
    def save_model_metadata(self, model_type: str, version: str, file_path: str,
                           hyperparameters: Dict = None, metrics: Dict = None,
                           is_active: bool = False) -> int:
        """Сохранение метаинформации о модели"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Если модель активируется, деактивируем другие модели этого типа
            if is_active:
                cursor.execute("""
                    UPDATE model_metadata SET is_active = 0 
                    WHERE model_type = ?
                """, (model_type,))
            
            cursor.execute("""
                INSERT INTO model_metadata 
                (model_type, version, trained_at, file_path, hyperparameters, metrics, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                model_type, version, datetime.now(), file_path,
                json.dumps(hyperparameters or {}),
                json.dumps(metrics or {}),
                1 if is_active else 0
            ))
            
            return cursor.lastrowid
            
    def get_active_model(self, model_type: str) -> Optional[Dict]:
        """Получение активной модели указанного типа"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM model_metadata 
                WHERE model_type = ? AND is_active = 1
                ORDER BY trained_at DESC
                LIMIT 1
            """, (model_type,))
            
            row = cursor.fetchone()
            if row:
                model = dict(row)
                if model.get('hyperparameters'):
                    model['hyperparameters'] = json.loads(model['hyperparameters'])
                if model.get('metrics'):
                    model['metrics'] = json.loads(model['metrics'])
                return model
            return None
            
    def get_model_history(self, model_type: str, limit: int = 10) -> List[Dict]:
        """Получение истории версий модели"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM model_metadata 
                WHERE model_type = ?
                ORDER BY trained_at DESC
                LIMIT ?
            """, (model_type, limit))
            
            return [dict(row) for row in cursor.fetchall()]
            
    # ==================== Методы для работы с оповещениями ====================
    
    def save_alert(self, alert: Dict[str, Any]) -> int:
        """Сохранение оповещения"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO alerts 
                (timestamp, component, failure_type, probability, predicted_rul, message, status, acknowledged)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                alert.get('timestamp', datetime.now()),
                alert.get('component', 'unknown'),
                alert.get('failure_type', 'unknown'),
                alert.get('probability', 0.0),
                alert.get('predicted_rul', 0),
                alert.get('message', ''),
                alert.get('status', 'sent'),
                0
            ))
            return cursor.lastrowid
            
    def acknowledge_alert(self, alert_id: int):
        """Подтверждение оповещения оператором"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE alerts SET acknowledged = 1, status = 'acknowledged'
                WHERE id = ?
            """, (alert_id,))
            
    def get_pending_alerts(self) -> List[Dict]:
        """Получение неподтвержденных оповещений"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM alerts 
                WHERE acknowledged = 0
                ORDER BY timestamp DESC
            """)
            return [dict(row) for row in cursor.fetchall()]
            
    # ==================== Методы для работы с состоянием системы ====================
    
    def save_system_state(self, key: str, value: Any):
        """Сохранение состояния системы (например, буфера окон)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO system_state (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, json.dumps(value), datetime.now()))
            
    def load_system_state(self, key: str) -> Optional[Any]:
        """Загрузка состояния системы"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM system_state WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                return json.loads(row['value'])
            return None
            
    def save_buffer(self, buffer_data: List[Dict], buffer_name: str = "metrics_buffer"):
        """Сохранение буфера данных (для отказоустойчивости)"""
        self.save_system_state(buffer_name, buffer_data)
        logger.debug(f"Saved buffer '{buffer_name}' with {len(buffer_data)} items")
        
    def load_buffer(self, buffer_name: str = "metrics_buffer") -> List[Dict]:
        """Загрузка буфера данных"""
        data = self.load_system_state(buffer_name)
        return data if data else []
        
    # ==================== Статистические методы ====================
    
    def get_statistics(self, hours: int = 24) -> Dict[str, Any]:
        """Получение статистики за указанный период"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Количество прогнозов
            cursor.execute("""
                SELECT COUNT(*) as total, AVG(probability) as avg_prob
                FROM predictions WHERE timestamp >= ?
            """, (cutoff_time,))
            pred_stats = cursor.fetchone()
            
            # Количество оповещений
            cursor.execute("""
                SELECT COUNT(*) as total, 
                       SUM(CASE WHEN acknowledged = 1 THEN 1 ELSE 0 END) as acknowledged
                FROM alerts WHERE timestamp >= ?
            """, (cutoff_time,))
            alert_stats = cursor.fetchone()
            
            return {
                'predictions': {
                    'total': pred_stats['total'] if pred_stats else 0,
                    'avg_probability': pred_stats['avg_prob'] if pred_stats and pred_stats['avg_prob'] else 0
                },
                'alerts': {
                    'total': alert_stats['total'] if alert_stats else 0,
                    'acknowledged': alert_stats['acknowledged'] if alert_stats else 0
                }
            }
            
    def cleanup_old_records(self, days: int = 30):
        """Удаление старых записей (для экономии места)"""
        cutoff_time = datetime.now() - timedelta(days=days)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Удаление старых прогнозов
            cursor.execute("DELETE FROM predictions WHERE timestamp < ?", (cutoff_time,))
            deleted_pred = cursor.rowcount
            
            # Удаление старых оповещений
            cursor.execute("DELETE FROM alerts WHERE timestamp < ?", (cutoff_time,))
            deleted_alerts = cursor.rowcount
            
            logger.info(f"Cleaned up {deleted_pred} old predictions and {deleted_alerts} old alerts")
            
    def close(self):
        """Закрытие соединения (для SQLite не требуется, но метод оставлен для совместимости)"""
        logger.info("SQLite client closed")