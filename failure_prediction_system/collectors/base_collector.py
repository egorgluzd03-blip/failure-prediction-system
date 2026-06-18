"""
Базовый класс для сборщиков данных
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass

from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MetricPoint:
    """Точка метрики"""
    timestamp: datetime
    metric_name: str
    value: float
    source: str
    tags: Dict[str, str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразование в словарь"""
        return {
            'timestamp': self.timestamp,
            'metric_name': self.metric_name,
            'value': self.value,
            'source': self.source,
            'tags': self.tags or {}
        }


@dataclass
class LogEntry:
    """Запись лога"""
    timestamp: datetime
    source: str
    level: str
    message: str
    service: str
    host: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразование в словарь"""
        return {
            'timestamp': self.timestamp,
            'source': self.source,
            'level': self.level,
            'message': self.message,
            'service': self.service,
            'host': self.host
        }


class BaseCollector(ABC):
    """Базовый класс для сборщиков данных"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.is_running = False
        self.buffer = []
        
    @abstractmethod
    def collect(self) -> List[Any]:
        """Сбор данных"""
        pass
    
    @abstractmethod
    def collect_historical(self, hours: int) -> List[Any]:
        """Сбор исторических данных"""
        pass
    
    def start(self):
        """Запуск сбора"""
        self.is_running = True
        logger.info(f"{self.__class__.__name__} started")
        
    def stop(self):
        """Остановка сбора"""
        self.is_running = False
        logger.info(f"{self.__class__.__name__} stopped")