import json
from typing import List, Dict, Any, Optional
from kafka import KafkaProducer
from kafka.errors import KafkaError

from collectors.base_collector import MetricPoint, LogEntry
from utils.logger import get_logger

logger = get_logger(__name__)


class KafkaMetricsProducer:
    """
    Производитель метрик в Kafka
    Топик: raw-metrics
    """
    
    def __init__(self, bootstrap_servers: List[str], topic: str = 'raw-metrics'):
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic
        self.producer = None
        self._connect()
        
    def _connect(self):
        """Установление соединения с Kafka"""
        try:
            self.producer = KafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                value_serializer=lambda v: json.dumps(v, default=str).encode('utf-8'),
                compression_type='snappy',
                retries=3,
                acks='all',
                request_timeout_ms=30000,
                max_block_ms=60000
            )
            logger.info(f"Kafka metrics producer connected to {self.bootstrap_servers}")
        except Exception as e:
            logger.error(f"Failed to connect to Kafka: {e}")
            self.producer = None
            
    def send_metrics(self, metrics: List[MetricPoint]) -> int:
        """Отправка метрик в Kafka"""
        if not self.producer:
            logger.warning("Kafka producer not available")
            return 0
            
        sent_count = 0
        for metric in metrics:
            try:
                future = self.producer.send(
                    self.topic,
                    key=metric.source.encode('utf-8'),
                    value=metric.to_dict()
                )
                # Неблокирующая отправка
                future.add_callback(lambda x: None)
                sent_count += 1
            except KafkaError as e:
                logger.error(f"Failed to send metric: {e}")
                
        self.producer.flush()
        logger.debug(f"Sent {sent_count} metrics to Kafka topic '{self.topic}'")
        return sent_count
    
    def close(self):
        """Закрытие соединения"""
        if self.producer:
            self.producer.close()
            logger.info("Kafka metrics producer closed")


class KafkaLogsProducer:
    """
    Производитель логов в Kafka
    Топик: raw-logs
    """
    
    def __init__(self, bootstrap_servers: List[str], topic: str = 'raw-logs'):
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic
        self.producer = None
        self._connect()
        
    def _connect(self):
        """Установление соединения с Kafka"""
        try:
            self.producer = KafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                value_serializer=lambda v: json.dumps(v, default=str).encode('utf-8'),
                compression_type='snappy',
                retries=3,
                acks='all'
            )
            logger.info(f"Kafka logs producer connected to {self.bootstrap_servers}")
        except Exception as e:
            logger.error(f"Failed to connect to Kafka: {e}")
            self.producer = None
            
    def send_logs(self, logs: List[LogEntry]) -> int:
        """Отправка логов в Kafka"""
        if not self.producer:
            logger.warning("Kafka producer not available")
            return 0
            
        sent_count = 0
        for log in logs:
            try:
                future = self.producer.send(
                    self.topic,
                    key=log.service.encode('utf-8'),
                    value=log.to_dict()
                )
                sent_count += 1
            except KafkaError as e:
                logger.error(f"Failed to send log: {e}")
                
        self.producer.flush()
        logger.debug(f"Sent {sent_count} logs to Kafka topic '{self.topic}'")
        return sent_count
    
    def close(self):
        """Закрытие соединения"""
        if self.producer:
            self.producer.close()
            logger.info("Kafka logs producer closed")