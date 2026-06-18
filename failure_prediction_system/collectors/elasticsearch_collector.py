"""
Сборщик логов из Elasticsearch
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import time

from elasticsearch import Elasticsearch
from elasticsearch.exceptions import ConnectionError, NotFoundError

from collectors.base_collector import BaseCollector, LogEntry
from utils.logger import get_logger

logger = get_logger(__name__)


class ElasticsearchCollector(BaseCollector):
    """Сборщик логов из Elasticsearch"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.hosts = config.get('hosts', ['http://localhost:9200'])
        self.api_key = config.get('api_key', '')
        self.username = config.get('username', '')
        self.password = config.get('password', '')
        self.index_pattern = config.get('index_pattern', 'logs-*')
        self.services = config.get('services', [])
        self.batch_size = config.get('batch_size', 10000)
        
        self._connect()
        
    def _connect(self):
        """Подключение к Elasticsearch"""
        try:
            if self.api_key:
                self.es = Elasticsearch(
                    self.hosts,
                    api_key=self.api_key,
                    request_timeout=60,
                    verify_certs=True,
                    max_retries=3,
                    retry_on_timeout=True
                )
            elif self.username and self.password:
                self.es = Elasticsearch(
                    self.hosts,
                    http_auth=(self.username, self.password),
                    use_ssl=True,
                    verify_certs=True
                )
            else:
                self.es = Elasticsearch(self.hosts)
                
            info = self.es.info()
            logger.info(f"Connected to Elasticsearch cluster: {info['cluster_name']}")
            
        except Exception as e:
            logger.error(f"Failed to connect to Elasticsearch: {e}")
            self.es = None
            
    def _fetch_logs(
        self, 
        start_time: datetime,
        end_time: datetime,
        query: Dict = None,
        scroll_mode: bool = False
    ) -> List[Dict]:
        """Извлечение логов из Elasticsearch"""
        if not self.es:
            logger.error("Elasticsearch not connected")
            return []
            
        logs = []
        
        # Базовый запрос
        base_query = {
            "query": {
                "bool": {
                    "filter": [
                        {"range": {"@timestamp": {
                            "gte": start_time.isoformat(),
                            "lte": end_time.isoformat()
                        }}}
                    ]
                }
            },
            "sort": [{"@timestamp": "asc"}],
            "size": self.batch_size
        }
        
        # Добавление дополнительных условий
        if query:
            base_query["query"]["bool"]["filter"].append(query)
            
        if self.services:
            base_query["query"]["bool"]["filter"].append(
                {"terms": {"service": self.services}}
            )
            
        try:
            if scroll_mode:
                # Использование scroll для больших объемов данных
                response = self.es.search(
                    index=self.index_pattern,
                    body=base_query,
                    scroll='10m'
                )
                
                scroll_id = response['_scroll_id']
                hits = response['hits']['hits']
                
                while hits:
                    for hit in hits:
                        logs.append(hit['_source'])
                        
                    response = self.es.scroll(scroll_id=scroll_id, scroll='10m')
                    scroll_id = response['_scroll_id']
                    hits = response['hits']['hits']
                    
                # Очистка scroll
                self.es.clear_scroll(scroll_id=scroll_id)
                
            else:
                # Обычный поиск
                response = self.es.search(
                    index=self.index_pattern,
                    body=base_query
                )
                
                for hit in response['hits']['hits']:
                    logs.append(hit['_source'])
                    
        except Exception as e:
            logger.error(f"Error fetching logs: {e}")
            
        return logs
    
    def collect(self, last_seconds: int = 10) -> List[LogEntry]:
        """Сбор последних логов"""
        end_time = datetime.now()
        start_time = end_time - timedelta(seconds=last_seconds)
        
        logs_data = self._fetch_logs(start_time, end_time)
        
        logs = []
        for log_data in logs_data:
            logs.append(LogEntry(
                timestamp=log_data.get('@timestamp', datetime.now()),
                source=log_data.get('source', log_data.get('service', 'unknown')),
                level=log_data.get('level', 'INFO'),
                message=log_data.get('message', log_data.get('msg', '')),
                service=log_data.get('service', 'unknown'),
                host=log_data.get('host', 'unknown')
            ))
            
        return logs
    
    def collect_historical(self, hours: int = 168) -> List[LogEntry]:
        """Сбор исторических логов"""
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours)
        
        logs_data = self._fetch_logs(start_time, end_time, scroll_mode=True)
        
        logs = []
        for log_data in logs_data:
            logs.append(LogEntry(
                timestamp=log_data.get('@timestamp', datetime.now()),
                source=log_data.get('source', log_data.get('service', 'unknown')),
                level=log_data.get('level', 'INFO'),
                message=log_data.get('message', log_data.get('msg', '')),
                service=log_data.get('service', 'unknown'),
                host=log_data.get('host', 'unknown')
            ))
            
        return logs
    
    def get_error_logs(self, hours: int = 24) -> List[LogEntry]:
        """Получение только логов с ошибками"""
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours)
        
        query = {"term": {"level": "ERROR"}}
        logs_data = self._fetch_logs(start_time, end_time, query, scroll_mode=True)
        
        logs = []
        for log_data in logs_data:
            logs.append(LogEntry(
                timestamp=log_data.get('@timestamp', datetime.now()),
                source=log_data.get('source', log_data.get('service', 'unknown')),
                level='ERROR',
                message=log_data.get('message', log_data.get('msg', '')),
                service=log_data.get('service', 'unknown'),
                host=log_data.get('host', 'unknown')
            ))
            
        return logs