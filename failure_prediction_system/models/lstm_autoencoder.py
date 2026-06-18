import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
from typing import Tuple, Dict, Any, Optional
import pickle

from utils.logger import get_logger

logger = get_logger(__name__)


class LSTMAutoencoder(nn.Module):
    """
    LSTM-автоэнкодер для моделирования нормального поведения системы.
    Аномалии выявляются по увеличению ошибки восстановления (reconstruction error).
    Архитектура: двунаправленный энкодер + однонаправленный декодер.
    """
    
    def __init__(self, input_size: int, hidden_size: int = 128, 
                 num_layers: int = 2, dropout: float = 0.2):
        super(LSTMAutoencoder, self).__init__()
        
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        
        # Энкодер: двунаправленный LSTM (Bidirectional) для учета контекста с обеих сторон
        # В соответствии с архитектурой, описанной в Главе 3
        self.encoder = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0,
            bidirectional=True
        )
        
        # Декодер: однонаправленный LSTM
        self.decoder = nn.LSTM(
            input_size=hidden_size * 2,  # *2 из-за bidirectional
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0,
            bidirectional=False
        )
        
        # Выходной слой для восстановления исходных признаков
        self.output_layer = nn.Linear(hidden_size, input_size)
        
        # Функция потерь
        self.criterion = nn.MSELoss()
        
    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Прямой проход автоэнкодера
        
        Args:
            x: Входная последовательность [batch_size, seq_len, input_size]
            
        Returns:
            reconstructed: Восстановленная последовательность
            latent: Скрытое представление (последнее состояние энкодера)
        """
        # Энкодирование
        encoded, (hidden, cell) = self.encoder(x)
        
        # Последнее скрытое состояние энкодера (объединение направлений)
        # hidden shape: [num_layers * 2, batch_size, hidden_size]
        hidden_combined = hidden[-2:, :, :]  # [2, batch_size, hidden_size]
        hidden_combined = hidden_combined.permute(1, 0, 2)  # [batch_size, 2, hidden_size]
        latent = hidden_combined.reshape(hidden_combined.size(0), -1)  # [batch_size, 2*hidden_size]
        
        # Подготовка для декодера
        decoder_hidden = latent.unsqueeze(0).repeat(self.num_layers, 1, 1)
        decoder_cell = torch.zeros_like(decoder_hidden)
        
        # Декодирование
        decoded, _ = self.decoder(encoded, (decoder_hidden, decoder_cell))
        
        # Восстановление исходных признаков
        reconstructed = self.output_layer(decoded)
        
        return reconstructed, latent
    
    def compute_reconstruction_error(self, x: torch.Tensor) -> torch.Tensor:
        """
        Вычисление ошибки восстановления для каждого элемента последовательности
        
        Returns:
            Средняя ошибка MSE по признакам для каждого образца в батче
        """
        reconstructed, _ = self.forward(x)
        loss = self.criterion(reconstructed, x)
        return loss


class LSTMAnomalyDetector:
    """
    Детектор аномалий на основе LSTM-автоэнкодера
    Обучение на данных нормальной работы (без разметки)
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.sequence_length = config.get('sequence_length', 60)
        self.hidden_size = config.get('lstm_hidden_size', 128)
        self.num_layers = config.get('lstm_num_layers', 2)
        self.dropout = config.get('dropout_rate', 0.2)
        self.learning_rate = config.get('learning_rate', 0.001)
        self.epochs = config.get('epochs', 100)
        self.threshold_percentile = config.get('threshold_percentile', 95)
        self.batch_size = config.get('batch_size', 32)
        
        self.model = None
        self.threshold = None
        self.input_size = None
        self.is_trained = False
        
    def _build_model(self, input_size: int) -> LSTMAutoencoder:
        """Построение модели LSTM-автоэнкодера"""
        return LSTMAutoencoder(
            input_size=input_size,
            hidden_size=self.hidden_size,
            num_layers=self.num_layers,
            dropout=self.dropout
        )
    
    def train(self, X: np.ndarray):
        """
        Обучение LSTM-автоэнкодера на данных нормальной работы
        
        Args:
            X: Нормализованные данные [samples, seq_len, features]
        """
        if X is None or len(X) == 0:
            logger.warning("Empty training data for LSTM autoencoder")
            return
            
        self.input_size = X.shape[2]
        self.model = self._build_model(self.input_size)
        
        # Преобразование в тензоры PyTorch
        X_tensor = torch.FloatTensor(X)
        dataset = TensorDataset(X_tensor)
        dataloader = DataLoader(dataset, batch_size=self.batch_size, shuffle=True)
        
        # Оптимизатор
        optimizer = optim.Adam(self.model.parameters(), lr=self.learning_rate)
        
        logger.info(f"Training LSTM autoencoder on {len(X)} sequences")
        logger.info(f"Input size: {self.input_size}, Hidden size: {self.hidden_size}")
        
        self.model.train()
        for epoch in range(self.epochs):
            epoch_loss = 0.0
            for batch in dataloader:
                batch_X = batch[0]
                
                optimizer.zero_grad()
                reconstructed, _ = self.model(batch_X)
                loss = self.model.criterion(reconstructed, batch_X)
                loss.backward()
                optimizer.step()
                
                epoch_loss += loss.item()
            
            if (epoch + 1) % 20 == 0:
                avg_loss = epoch_loss / len(dataloader)
                logger.debug(f"Epoch {epoch+1}/{self.epochs}, Loss: {avg_loss:.6f}")
        
        # Вычисление порога аномальности на основе ошибок восстановления
        self.model.eval()
        reconstruction_errors = []
        
        with torch.no_grad():
            for batch in dataloader:
                batch_X = batch[0]
                loss = self.model.compute_reconstruction_error(batch_X)
                reconstruction_errors.append(loss.item())
        
        self.threshold = np.percentile(reconstruction_errors, self.threshold_percentile)
        self.is_trained = True
        
        logger.info(f"LSTM autoencoder training completed")
        logger.info(f"Reconstruction error threshold ({self.threshold_percentile}%): {self.threshold:.6f}")
        
    def detect(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Обнаружение аномалий на основе ошибки восстановления
        
        Returns:
            is_anomaly: булевый массив
            anomaly_scores: числовые значения ошибок восстановления
        """
        if not self.is_trained:
            logger.warning("LSTM autoencoder not trained")
            return np.zeros(len(X), dtype=bool), np.zeros(len(X))
            
        if X is None or len(X) == 0:
            return np.array([]), np.array([])
            
        # Обеспечение правильной формы
        original_shape = X.shape
        if len(X.shape) == 2:
            X = X.reshape(-1, self.sequence_length, self.input_size)
            
        X_tensor = torch.FloatTensor(X)
        
        self.model.eval()
        with torch.no_grad():
            anomaly_scores = []
            for i in range(0, len(X_tensor), self.batch_size):
                batch = X_tensor[i:i + self.batch_size]
                scores = self.model.compute_reconstruction_error(batch)
                anomaly_scores.extend(scores.cpu().numpy())
        
        anomaly_scores = np.array(anomaly_scores)
        is_anomaly = anomaly_scores > self.threshold
        
        return is_anomaly, anomaly_scores
    
    def save(self, path: str):
        """Сохранение модели"""
        if self.model:
            torch.save({
                'model_state_dict': self.model.state_dict(),
                'threshold': self.threshold,
                'input_size': self.input_size,
                'config': {
                    'sequence_length': self.sequence_length,
                    'hidden_size': self.hidden_size,
                    'num_layers': self.num_layers,
                    'dropout': self.dropout,
                    'learning_rate': self.learning_rate,
                    'epochs': self.epochs,
                    'threshold_percentile': self.threshold_percentile
                }
            }, path)
            logger.info(f"LSTM autoencoder saved to {path}")
            
    def load(self, path: str):
        """Загрузка модели"""
        checkpoint = torch.load(path, map_location='cpu')
        
        self.input_size = checkpoint['input_size']
        self.sequence_length = checkpoint['config']['sequence_length']
        self.hidden_size = checkpoint['config']['hidden_size']
        self.num_layers = checkpoint['config']['num_layers']
        self.dropout = checkpoint['config']['dropout']
        self.threshold = checkpoint['threshold']
        
        self.model = self._build_model(self.input_size)
        self.model.load_state_dict(checkpoint['model_state_dict'])
        self.is_trained = True
        
        logger.info(f"LSTM autoencoder loaded from {path}")