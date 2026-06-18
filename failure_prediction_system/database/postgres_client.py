import psycopg2
from psycopg2.extras import execute_values
from psycopg2 import sql
import pandas as pd
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from contextlib import contextmanager

from utils.logger import get_logger

logger = get_logger(__name__)


class PostgresClient:
    """Клиент для работы с PostgreSQL с поддержкой партиционирования"""
    
    def __init__(self, config: Dict[str, Any]):
        self.host = config.get('host', 'localhost')
        self.port = config.get('port', 5432)
        self.database = config.get('database', 'failure_prediction')
        self.user = config.get('user', 'postgres')
        self.password = config.get('password', '')
        
        self.conn = None
        self._connect()
        self._init_tables()
        
    def _connect(self):
        """Установление соединения с PostgreSQL"""
        try:
            self.conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password
            )
            logger.info(f"Connected to PostgreSQL at {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            
    @contextmanager
    def get_cursor(self):
        """Контекстный менеджер для курсора"""
        if not self.conn:
            self._connect()
        cursor = self.conn.cursor()
        try:
            yield cursor
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            cursor.close()
            
    def _init_tables(self):
        """Инициализация таблиц с партиционированием"""
        with self.get_cursor() as cur:
            # Таблица метрик с партиционированием по месяцам
            cur.execute("""
                CREATE TABLE IF NOT EXISTS metrics (
                    timestamp TIMESTAMPTZ NOT NULL,
                    metric_name TEXT NOT NULL,
                    value DOUBLE PRECISION NOT NULL,
                    source TEXT NOT NULL,
                    tags JSONB DEFAULT '{}'
                ) PARTITION BY RANGE (timestamp)
            """)
            
            # Таблица логов с партиционированием
            cur.execute("""
                CREATE TABLE IF NOT EXISTS logs (
                    timestamp TIMESTAMPTZ NOT NULL,
                    source TEXT NOT NULL,
                    level INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    service TEXT NOT NULL,
                    host TEXT NOT NULL,
                    tags JSONB DEFAULT '{}'
                ) PARTITION BY RANGE (timestamp)
            """)
            
            # Таблица прогнозов
            cur.execute("""
                CREATE TABLE IF NOT EXISTS predictions (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMPTZ NOT NULL,
                    component TEXT NOT NULL,
                    failure_type TEXT NOT NULL,
                    probability REAL NOT NULL,
                    predicted_rul REAL NOT NULL,
                    confidence_lower REAL,
                    confidence_upper REAL,
                    contributing_metrics JSONB,
                    contributing_log_patterns JSONB
                )
            """)
            
            # Таблица моделей
            cur.execute("""
                CREATE TABLE IF NOT EXISTS models (
                    id SERIAL PRIMARY KEY,
                    model_type TEXT NOT NULL,
                    version TEXT NOT NULL,
                    trained_at TIMESTAMPTZ NOT NULL,
                    file_path TEXT NOT NULL,
                    hyperparameters JSONB,
                    metrics JSONB
                )
            """)
            
            # Создание индексов
            cur.execute("CREATE INDEX IF NOT EXISTS idx_metrics_timestamp ON metrics (timestamp)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs (timestamp)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_predictions_timestamp ON predictions (timestamp)")
            
            logger.info("PostgreSQL tables initialized")
            
    def create_partition(self, table_name: str, date: datetime):
        """
        Создание партиции для указанного месяца
        В соответствии с разделом 3.3.2
        """
        partition_name = f"{table_name}_{date.strftime('%Y_%m')}"
        start_date = date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        if date.month == 12:
            end_date = date.replace(year=date.year + 1, month=1, day=1)
        else:
            end_date = date.replace(month=date.month + 1, day=1)
            
        with self.get_cursor() as cur:
            # Проверка существования партиции
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_class WHERE relname = %s
                )
            """, (partition_name,))
            
            if not cur.fetchone()[0]:
                cur.execute(sql.SQL("""
                    CREATE TABLE IF NOT EXISTS {} PARTITION OF {}
                    FOR VALUES FROM (%s) TO (%s)
                """).format(sql.Identifier(partition_name), sql.Identifier(table_name)), 
                (start_date, end_date))
                logger.debug(f"Created partition: {partition_name}")
                
    def insert_metrics(self, metrics: List[Dict[str, Any]]):
        """
        Вставка метрик с автоматическим созданием партиций
        """
        if not metrics or not self.conn:
            return
            
        # Определение необходимых партиций
        for metric in metrics:
            timestamp = metric['timestamp']
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            self.create_partition('metrics', timestamp)
            
        with self.get_cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO metrics (timestamp, metric_name, value, source, tags)
                VALUES %s
                """,
                [(m['timestamp'], m['metric_name'], m['value'], 
                  m['source'], m.get('tags', '{}')) for m in metrics]
            )
            logger.debug(f"Inserted {len(metrics)} metrics into PostgreSQL")
            
    def insert_logs(self, logs: List[Dict[str, Any]]):
        """Вставка логов с автоматическим созданием партиций"""
        if not logs or not self.conn:
            return
            
        # Определение необходимых партиций
        for log in logs:
            timestamp = log['timestamp']
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            self.create_partition('logs', timestamp)
            
        with self.get_cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO logs (timestamp, source, level, message, service, host, tags)
                VALUES %s
                """,
                [(l['timestamp'], l['source'], l['level'], l['message'], 
                  l['service'], l['host'], l.get('tags', '{}')) for l in logs]
            )
            logger.debug(f"Inserted {len(logs)} logs into PostgreSQL")
            
    def get_metrics_for_training(self, hours: int = 168) -> pd.DataFrame:
        """
        Получение метрик для обучения моделей
        hours: количество часов истории (по умолчанию 168 = 7 суток)
        """
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        query = """
            SELECT timestamp, metric_name, value, source, tags
            FROM metrics
            WHERE timestamp >= %s
            ORDER BY timestamp ASC
        """
        
        return pd.read_sql_query(query, self.conn, params=(cutoff_time,))
    
    def get_logs_for_training(self, hours: int = 168) -> pd.DataFrame:
        """Получение логов для обучения моделей"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        query = """
            SELECT timestamp, source, level, message, service, host
            FROM logs
            WHERE timestamp >= %s
            ORDER BY timestamp ASC
        """
        
        return pd.read_sql_query(query, self.conn, params=(cutoff_time,))
    
    def save_prediction(self, prediction: Dict[str, Any]):
        """Сохранение прогноза"""
        with self.get_cursor() as cur:
            cur.execute("""
                INSERT INTO predictions 
                (timestamp, component, failure_type, probability, predicted_rul, 
                 confidence_lower, confidence_upper, contributing_metrics, contributing_log_patterns)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                prediction['timestamp'], prediction['component'], prediction['failure_type'],
                prediction['probability'], prediction['predicted_rul'],
                prediction.get('confidence_lower'), prediction.get('confidence_upper'),
                prediction.get('contributing_metrics', '[]'),
                prediction.get('contributing_log_patterns', '[]')
            ))
            logger.debug(f"Saved prediction to PostgreSQL")
            
    def close(self):
        """Закрытие соединения"""
        if self.conn:
            self.conn.close()
            logger.info("PostgreSQL connection closed")