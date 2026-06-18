import os
from dataclasses import dataclass, field
from typing import List, Dict, Any
from pathlib import Path

# Базовые пути
BASE_DIR = Path(__file__).parent.parent
MODELS_DIR = BASE_DIR / "models"
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

# Создание директорий
MODELS_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)


@dataclass
class PrometheusConfig:
    """Конфигурация Prometheus (раздел 3.1.1)"""
    url: str = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
    scrape_interval: int = 10
    timeout: int = 30
    servers: List[str] = field(default_factory=lambda: ["server-01", "server-02"])


@dataclass
class ElasticsearchConfig:
    """Конфигурация Elasticsearch (раздел 3.1.1)"""
    hosts: List[str] = field(default_factory=lambda: ["http://localhost:9200"])
    api_key: str = os.getenv("ELASTIC_API_KEY", "")
    username: str = os.getenv("ELASTIC_USERNAME", "")
    password: str = os.getenv("ELASTIC_PASSWORD", "")
    index_pattern: str = "logs-*"
    services: List[str] = field(default_factory=lambda: ["api-gateway", "auth-service", "database"])


@dataclass
class KafkaConfig:
    """Конфигурация Kafka (раздел 3.1.2)"""
    enabled: bool = os.getenv("KAFKA_ENABLED", "false").lower() == "true"
    bootstrap_servers: List[str] = field(default_factory=lambda: ["localhost:9092"])
    metrics_topic: str = "raw-metrics"
    logs_topic: str = "raw-logs"


@dataclass
class PostgresConfig:
    """Конфигурация PostgreSQL (раздел 3.3.2)"""
    host: str = os.getenv("POSTGRES_HOST", "localhost")
    port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    database: str = os.getenv("POSTGRES_DB", "failure_prediction")
    user: str = os.getenv("POSTGRES_USER", "postgres")
    password: str = os.getenv("POSTGRES_PASSWORD", "")


@dataclass
class ModelConfig:
    """
    Конфигурация моделей машинного обучения
    В соответствии с разделами 3.4.1 и 3.4.2
    """
    # Общие параметры
    sequence_length: int = 60  # 10 минут истории при шаге 10 секунд
    batch_size: int = 32
    epochs: int = 100
    lstm_units: List[int] = field(default_factory=lambda: [128, 64, 32])
    
    # Isolation Forest (раздел 3.4.1, шаг 5)
    random_forest_estimators: int = 100
    isolation_forest_estimators: int = 100
    contamination: float = 0.05
    
    # LSTM-автоэнкодер (раздел 3.4.1, шаг 6)
    lstm_hidden_size: int = 128
    lstm_num_layers: int = 2
    dropout_rate: float = 0.2
    learning_rate: float = 0.001
    threshold_percentile: int = 95
    
    # XGBoost (раздел 3.4.1, шаг 7)
    xgboost_estimators: int = 100
    xgboost_max_depth: int = 10
    xgboost_learning_rate: float = 0.1
    
    # Веса ансамбля (раздел 3.4.2, шаг 6)
    isolation_weight: float = 0.3
    lstm_weight: float = 0.7
    
    # Пути сохранения
    model_save_path: str = str(MODELS_DIR)


@dataclass
class AlertConfig:
    """Конфигурация оповещений (раздел 3.6)"""
    email_enabled: bool = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
    email_smtp_host: str = os.getenv("EMAIL_SMTP_HOST", "")
    email_smtp_port: int = int(os.getenv("EMAIL_SMTP_PORT", "587"))
    email_username: str = os.getenv("EMAIL_USERNAME", "")
    email_password: str = os.getenv("EMAIL_PASSWORD", "")
    email_from: str = os.getenv("EMAIL_FROM", "")
    email_to: str = os.getenv("EMAIL_TO", "")
    
    telegram_enabled: bool = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    
    failure_threshold: float = 0.7  # Порог для критических оповещений (раздел 3.4.3)
    warning_threshold: float = 0.4  # Порог для предупреждений


@dataclass
class SystemConfig:
    """Основная конфигурация системы"""
    collection_interval: int = 10  # секунд (раздел 3.2.1)
    training_hours: int = 168  # 7 суток (раздел 3.4.1, шаг 1)
    log_level: str = "INFO"
    
    prometheus: PrometheusConfig = field(default_factory=PrometheusConfig)
    elasticsearch: ElasticsearchConfig = field(default_factory=ElasticsearchConfig)
    kafka: KafkaConfig = field(default_factory=KafkaConfig)
    postgres: PostgresConfig = field(default_factory=PostgresConfig)
    models: ModelConfig = field(default_factory=ModelConfig)
    alerts: AlertConfig = field(default_factory=AlertConfig)


# Глобальный объект конфигурации
config = SystemConfig()