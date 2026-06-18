"""
Сборщик метрик из Prometheus
"""

import requests
import pandas as pd
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import time

from collectors.base_collector import BaseCollector, MetricPoint
from utils.logger import get_logger

logger = get_logger(__name__)


class PrometheusCollector(BaseCollector):
    """Сборщик метрик из Prometheus"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.prometheus_url = config.get('url', 'http://localhost:9090')
        self.servers = config.get('servers', [])
        self.timeout = config.get('timeout', 30)
        
    def _query_prometheus(self, query: str, start: Optional[datetime] = None, 
                          end: Optional[datetime] = None, step: str = '10s') -> List[Dict]:
        """Выполнение запроса к Prometheus API"""
        if start and end:
            # Запрос диапазона
            url = f"{self.prometheus_url}/api/v1/query_range"
            params = {
                'query': query,
                'start': start.timestamp(),
                'end': end.timestamp(),
                'step': step
            }
        else:
            # Запрос текущего значения
            url = f"{self.prometheus_url}/api/v1/query"
            params = {'query': query}
            
        try:
            response = requests.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            
            if data['status'] == 'success':
                return data['data']['result']
            else:
                logger.error(f"Prometheus query failed: {data}")
                return []
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error querying Prometheus: {e}")
            return []
            
    def get_cpu_usage(self, instance: str = None, hours: int = None) -> List[MetricPoint]:
        """Получение использования CPU"""
        query = '100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) by (instance) * 100)'
        if instance:
            query = f'100 - (avg(rate(node_cpu_seconds_total{{mode="idle", instance="{instance}"}}[5m])) * 100)'
            
        if hours:
            end = datetime.now()
            start = end - timedelta(hours=hours)
            results = self._query_prometheus(query, start, end)
        else:
            results = self._query_prometheus(query)
            
        metrics = []
        current_time = datetime.now()
        
        for result in results:
            instance_name = result['metric'].get('instance', instance or 'unknown')
            
            if hours:
                # Диапазонные данные
                for timestamp, value in result.get('values', []):
                    metrics.append(MetricPoint(
                        timestamp=datetime.fromtimestamp(float(timestamp)),
                        metric_name='cpu_usage_percent',
                        value=float(value),
                        source=instance_name
                    ))
            else:
                # Текущее значение
                value = float(result.get('value', [0, 0])[1]) if result.get('value') else 0
                metrics.append(MetricPoint(
                    timestamp=current_time,
                    metric_name='cpu_usage_percent',
                    value=value,
                    source=instance_name
                ))
                
        return metrics
    
    def get_memory_usage(self, instance: str = None, hours: int = None) -> List[MetricPoint]:
        """Получение использования памяти"""
        query = """(
            node_memory_MemTotal_bytes - 
            (node_memory_MemFree_bytes + node_memory_Cached_bytes + node_memory_Buffers_bytes)
        ) / node_memory_MemTotal_bytes * 100"""
        
        if instance:
            query = f'({query}){{instance="{instance}"}}'
            
        if hours:
            end = datetime.now()
            start = end - timedelta(hours=hours)
            results = self._query_prometheus(query, start, end)
        else:
            results = self._query_prometheus(query)
            
        metrics = []
        current_time = datetime.now()
        
        for result in results:
            instance_name = result['metric'].get('instance', instance or 'unknown')
            
            if hours:
                for timestamp, value in result.get('values', []):
                    metrics.append(MetricPoint(
                        timestamp=datetime.fromtimestamp(float(timestamp)),
                        metric_name='memory_usage_percent',
                        value=float(value),
                        source=instance_name
                    ))
            else:
                value = float(result.get('value', [0, 0])[1]) if result.get('value') else 0
                metrics.append(MetricPoint(
                    timestamp=current_time,
                    metric_name='memory_usage_percent',
                    value=value,
                    source=instance_name
                ))
                
        return metrics
    
    def get_disk_io(self, instance: str = None, hours: int = None) -> List[MetricPoint]:
        """Получение дискового I/O"""
        query = 'rate(node_disk_read_bytes_total[5m]) + rate(node_disk_written_bytes_total[5m])'
        if instance:
            query = f'{query}{{instance="{instance}"}}'
            
        if hours:
            end = datetime.now()
            start = end - timedelta(hours=hours)
            results = self._query_prometheus(query, start, end)
        else:
            results = self._query_prometheus(query)
            
        metrics = []
        current_time = datetime.now()
        
        for result in results:
            instance_name = result['metric'].get('instance', instance or 'unknown')
            
            if hours:
                for timestamp, value in result.get('values', []):
                    metrics.append(MetricPoint(
                        timestamp=datetime.fromtimestamp(float(timestamp)),
                        metric_name='disk_io_mbps',
                        value=float(value) / (1024 * 1024),  # bytes to MB
                        source=instance_name
                    ))
            else:
                value = float(result.get('value', [0, 0])[1]) if result.get('value') else 0
                metrics.append(MetricPoint(
                    timestamp=current_time,
                    metric_name='disk_io_mbps',
                    value=value / (1024 * 1024),
                    source=instance_name
                ))
                
        return metrics
    
    def get_network_traffic(self, instance: str = None, hours: int = None) -> List[MetricPoint]:
        """Получение сетевого трафика"""
        query = 'rate(node_network_receive_bytes_total[5m]) + rate(node_network_transmit_bytes_total[5m])'
        if instance:
            query = f'{query}{{instance="{instance}"}}'
            
        if hours:
            end = datetime.now()
            start = end - timedelta(hours=hours)
            results = self._query_prometheus(query, start, end)
        else:
            results = self._query_prometheus(query)
            
        metrics = []
        current_time = datetime.now()
        
        for result in results:
            instance_name = result['metric'].get('instance', instance or 'unknown')
            
            if hours:
                for timestamp, value in result.get('values', []):
                    metrics.append(MetricPoint(
                        timestamp=datetime.fromtimestamp(float(timestamp)),
                        metric_name='network_traffic_mbps',
                        value=float(value) / (1024 * 1024),
                        source=instance_name
                    ))
            else:
                value = float(result.get('value', [0, 0])[1]) if result.get('value') else 0
                metrics.append(MetricPoint(
                    timestamp=current_time,
                    metric_name='network_traffic_mbps',
                    value=value / (1024 * 1024),
                    source=instance_name
                ))
                
        return metrics
    
    def collect(self) -> List[MetricPoint]:
        """Сбор всех метрик в реальном времени"""
        all_metrics = []
        
        for server in self.servers:
            all_metrics.extend(self.get_cpu_usage(server))
            all_metrics.extend(self.get_memory_usage(server))
            all_metrics.extend(self.get_disk_io(server))
            all_metrics.extend(self.get_network_traffic(server))
            
        return all_metrics
    
    def collect_historical(self, hours: int = 168) -> List[MetricPoint]:
        """Сбор исторических метрик"""
        all_metrics = []
        
        for server in self.servers:
            all_metrics.extend(self.get_cpu_usage(server, hours))
            all_metrics.extend(self.get_memory_usage(server, hours))
            all_metrics.extend(self.get_disk_io(server, hours))
            all_metrics.extend(self.get_network_traffic(server, hours))
            
        return all_metrics