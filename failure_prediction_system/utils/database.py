"""
Модуль для работы с базой данных (SQLite для хранения истории)
"""

import sqlite3
import pandas as pd
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from contextlib import contextmanager
import json

from utils.logger import get_logger

logger = get_logger(__name__)


class Database:
    """Класс для работы с базой данных"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_database()
        
    @contextmanager
    def get_connection(self):
        """Получение соединения с БД (контекстный менеджер)"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            conn.close()
            
    def _init_database(self):
        """Инициализация таблиц БД"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица метрик
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL,
                    metric_name TEXT NOT NULL,
                    value REAL NOT NULL,
                    source TEXT NOT NULL,
                    tags TEXT
                )
            """)
            
            # Таблица логов
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL,
                    source TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    service TEXT NOT NULL,
                    host TEXT NOT NULL
                )
            """)
            
            # Таблица прогнозов
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL,
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
            
            # Индексы
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_metrics_timestamp ON metrics(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_metrics_source ON metrics(source)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_predictions_timestamp ON predictions(timestamp)")
            
    def save_metrics(self, metrics_data: List[Dict[str, Any]]):
        """Сохранение метрик"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT INTO metrics (timestamp, metric_name, value, source, tags)
                VALUES (?, ?, ?, ?, ?)
            """, [
                (m['timestamp'], m['metric_name'], m['value'], m['source'], 
                 json.dumps(m.get('tags', {})))
                for m in metrics_data
            ])
            
    def save_logs(self, logs_data: List[Dict[str, Any]]):
        """Сохранение логов"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT INTO logs (timestamp, source, level, message, service, host)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [
                (l['timestamp'], l['source'], l['level'], l['message'], l['service'], l['host'])
                for l in logs_data
            ])
            
    def save_predictions(self, predictions_data: List[Dict[str, Any]]):
        """Сохранение прогнозов"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT INTO predictions 
                (timestamp, component, failure_type, probability, predicted_rul, 
                 confidence_lower, confidence_upper, contributing_metrics, contributing_log_patterns)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (p['timestamp'], p['component'], p['failure_type'], p['probability'],
                 p['predicted_rul'], p.get('confidence_lower'), p.get('confidence_upper'),
                 json.dumps(p.get('contributing_metrics', [])),
                 json.dumps(p.get('contributing_log_patterns', [])))
                for p in predictions_data
            ])
            
    def get_metrics_for_training(self, hours: int = 168) -> pd.DataFrame:
        """Получение метрик для обучения"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        query = """
            SELECT timestamp, metric_name, value, source
            FROM metrics
            WHERE timestamp >= ?
            ORDER BY timestamp ASC
        """
        
        with self.get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=(cutoff_time,))
            
        return df
    
    def get_logs_for_training(self, hours: int = 168) -> pd.DataFrame:
        """Получение логов для обучения"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        query = """
            SELECT timestamp, source, level, message, service, host
            FROM logs
            WHERE timestamp >= ?
            ORDER BY timestamp ASC
        """
        
        with self.get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=(cutoff_time,))
            
        return df