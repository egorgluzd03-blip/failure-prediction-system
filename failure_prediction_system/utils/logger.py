# -*- coding: utf-8 -*-
import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional
import json

from config.settings import LOGS_DIR


class JSONFormatter(logging.Formatter):
    """JSON ôîðìàòòåð äëÿ ëîãîâ"""
    
    def format(self, record):
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        
        if hasattr(record, 'extra_data'):
            log_entry["extra"] = record.extra_data
            
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
            
        return json.dumps(log_entry)


def setup_logger(name: str, level: str = "INFO", json_format: bool = False) -> logging.Logger:
    """
    Íàñòðîéêà ëîããåðà
    
    Args:
        name: Èìÿ ëîããåðà
        level: Óðîâåíü ëîãèðîâàíèÿ
        json_format: Èñïîëüçîâàòü JSON ôîðìàò
        
    Returns:
        Íàñòðîåííûé ëîããåð
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))
    
    # Î÷èñòêà ñóùåñòâóþùèõ îáðàáîò÷èêîâ
    logger.handlers.clear()
    
    # Êîíñîëüíûé îáðàáîò÷èê
    console_handler = logging.StreamHandler(sys.stdout)
    
    if json_format:
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Ôàéëîâûé îáðàáîò÷èê
    log_file = LOGS_DIR / f"{name}_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """Ïîëó÷åíèå ëîããåðà ïî èìåíè"""
    return logging.getLogger(name)
