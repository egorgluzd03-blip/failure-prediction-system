"""
Менеджер оповещений
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from utils.logger import get_logger

logger = get_logger(__name__)


class AlertManager:
    """Менеджер оповещений"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.alert_history = []
        
        # Настройки уведомлений
        self.email_enabled = config.get('email_enabled', False)
        self.email_smtp = config.get('email_smtp', {})
        
        self.telegram_enabled = config.get('telegram_enabled', False)
        self.telegram_bot_token = config.get('telegram_bot_token', '')
        self.telegram_chat_id = config.get('telegram_chat_id', '')
        
        self.webhook_enabled = config.get('webhook_enabled', False)
        self.webhook_url = config.get('webhook_url', '')
        
        self.threshold = config.get('threshold', 0.7)
        
    def send_alert(
        self, 
        component: str, 
        failure_type: str, 
        probability: float,
        predicted_rul: float,
        contributing_metrics: List[str] = None,
        contributing_logs: List[str] = None
    ) -> bool:
        """
        Отправка оповещения о прогнозируемом отказе
        
        Returns:
            True если успешно отправлено
        """
        if probability < self.threshold:
            return False
            
        alert_data = {
            'timestamp': datetime.now().isoformat(),
            'component': component,
            'failure_type': failure_type,
            'probability': probability,
            'predicted_rul_minutes': predicted_rul / 60,
            'contributing_metrics': contributing_metrics or [],
            'contributing_logs': contributing_logs or []
        }
        
        # Сохранение в истории
        self.alert_history.append(alert_data)
        
        # Формирование сообщения
        message = self._format_alert_message(alert_data)
        
        success = True
        
        # Отправка через email
        if self.email_enabled:
            if not self._send_email(message):
                success = False
                
        # Отправка через Telegram
        if self.telegram_enabled:
            if not self._send_telegram(message):
                success = False
                
        # Отправка через webhook
        if self.webhook_enabled:
            if not self._send_webhook(alert_data):
                success = False
                
        if success:
            logger.warning(f"Alert sent: {alert_data['component']} - {probability:.2%}")
            
        return success
    
    def _format_alert_message(self, alert_data: Dict) -> str:
        """Форматирование сообщения оповещения"""
        message = f"""
⚠️ CRITICAL ALERT - Predicted Failure
====================================
Component: {alert_data['component']}
Failure Type: {alert_data['failure_type']}
Probability: {alert_data['probability']:.2%}
Remaining Useful Life: {alert_data['predicted_rul_minutes']:.1f} minutes
Timestamp: {alert_data['timestamp']}

Contributing Metrics:
{chr(10).join(f'  - {m}' for m in alert_data['contributing_metrics'][:5])}

Contributing Log Patterns:
{chr(10).join(f'  - {l}' for l in alert_data['contributing_logs'][:5])}
====================================
"""
        return message.strip()
    
    def _send_email(self, message: str) -> bool:
        """Отправка email"""
        try:
            smtp_config = self.email_smtp
            msg = MIMEMultipart()
            msg['From'] = smtp_config.get('from', '')
            msg['To'] = smtp_config.get('to', '')
            msg['Subject'] = '[ALERT] Predicted Failure Detected'
            
            msg.attach(MIMEText(message, 'plain'))
            
            server = smtplib.SMTP(smtp_config.get('host', ''), smtp_config.get('port', 587))
            server.starttls()
            server.login(
                smtp_config.get('username', ''),
                smtp_config.get('password', '')
            )
            server.send_message(msg)
            server.quit()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False
            
    def _send_telegram(self, message: str) -> bool:
        """Отправка в Telegram"""
        try:
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            data = {
                'chat_id': self.telegram_chat_id,
                'text': message,
                'parse_mode': 'HTML'
            }
            response = requests.post(url, json=data, timeout=10)
            response.raise_for_status()
            return True
            
        except Exception as e:
            logger.error(f"Failed to send Telegram: {e}")
            return False
            
    def _send_webhook(self, alert_data: Dict) -> bool:
        """Отправка webhook"""
        try:
            response = requests.post(
                self.webhook_url,
                json=alert_data,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            response.raise_for_status()
            return True
            
        except Exception as e:
            logger.error(f"Failed to send webhook: {e}")
            return False
            
    def get_recent_alerts(self, limit: int = 10) -> List[Dict]:
        """Получение последних оповещений"""
        return self.alert_history[-limit:]