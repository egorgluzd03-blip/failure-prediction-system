"""
Визуализация результатов
"""

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional

from utils.logger import get_logger

logger = get_logger(__name__)


class Dashboard:
    """Дашборд для визуализации"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
    def plot_metrics_timeseries(
        self, 
        data: pd.DataFrame, 
        metrics: List[str],
        title: str = "System Metrics"
    ) -> go.Figure:
        """Построение временных рядов метрик"""
        fig = make_subplots(
            rows=len(metrics),
            cols=1,
            subplot_titles=metrics,
            shared_xaxes=True,
            vertical_spacing=0.05
        )
        
        for i, metric in enumerate(metrics, 1):
            if metric in data.columns:
                fig.add_trace(
                    go.Scatter(
                        x=data.index if 'timestamp' not in data.columns else data['timestamp'],
                        y=data[metric],
                        mode='lines',
                        name=metric,
                        line=dict(width=1.5, color='#1f77b4')
                    ),
                    row=i, col=1
                )
                
                # Добавление аномалий
                if 'is_anomaly' in data.columns:
                    anomalies = data[data['is_anomaly']]
                    if not anomalies.empty:
                        x_vals = anomalies.index if 'timestamp' not in anomalies.columns else anomalies['timestamp']
                        fig.add_trace(
                            go.Scatter(
                                x=x_vals,
                                y=anomalies[metric],
                                mode='markers',
                                name='Anomaly',
                                marker=dict(color='red', size=8, symbol='x')
                            ),
                            row=i, col=1
                        )
                        
        fig.update_layout(
            height=300 * len(metrics),
            title_text=title,
            showlegend=True,
            hovermode='x unified'
        )
        
        fig.update_xaxes(title_text="Time", row=len(metrics), col=1)
        
        return fig
    
    def plot_anomaly_heatmap(self, data: pd.DataFrame) -> plt.Figure:
        """Построение тепловой карты аномалий"""
        numeric_cols = data.select_dtypes(include=[np.number]).columns
        corr_matrix = data[numeric_cols].corr()
        
        fig, ax = plt.subplots(figsize=(12, 10))
        mask = np.triu(np.ones_like(corr_matrix, dtype=bool))
        
        sns.heatmap(
            corr_matrix,
            mask=mask,
            annot=True,
            fmt='.2f',
            cmap='RdYlGn_r',
            center=0,
            square=True,
            linewidths=0.5,
            cbar_kws={"shrink": 0.8},
            ax=ax
        )
        
        ax.set_title('Feature Correlation Matrix with Anomaly Patterns', fontsize=14)
        plt.tight_layout()
        
        return fig
    
    def plot_prediction_gauge(
        self, 
        probability: float,
        predicted_rul: float,
        failure_type: str
    ) -> go.Figure:
        """Построение датчика прогноза"""
        fig = make_subplots(
            rows=1, cols=2,
            subplot_titles=('Failure Probability', 'Remaining Useful Life'),
            specs=[[{'type': 'indicator'}, {'type': 'indicator'}]]
        )
        
        # Датчик вероятности отказа
        fig.add_trace(
            go.Indicator(
                mode="gauge+number",
                value=probability * 100,
                title={'text': "Failure Probability (%)"},
                domain={'x': [0, 1], 'y': [0, 1]},
                gauge={
                    'axis': {'range': [0, 100]},
                    'bar': {'color': "red" if probability > 0.5 else "green"},
                    'steps': [
                        {'range': [0, 30], 'color': "lightgreen"},
                        {'range': [30, 70], 'color': "yellow"},
                        {'range': [70, 100], 'color': "salmon"}
                    ],
                    'threshold': {
                        'line': {'color': "red", 'width': 4},
                        'thickness': 0.75,
                        'value': probability * 100
                    }
                }
            ),
            row=1, col=1
        )
        
        # Датчик остаточного ресурса
        fig.add_trace(
            go.Indicator(
                mode="gauge+number",
                value=predicted_rul / 60,
                title={'text': "Remaining Useful Life (minutes)"},
                domain={'x': [0, 1], 'y': [0, 1]},
                gauge={
                    'axis': {'range': [0, 120]},
                    'bar': {'color': "orange" if predicted_rul / 60 < 30 else "green"},
                    'steps': [
                        {'range': [0, 30], 'color': "red"},
                        {'range': [30, 60], 'color': "yellow"},
                        {'range': [60, 120], 'color': "lightgreen"}
                    ]
                }
            ),
            row=1, col=2
        )
        
        fig.update_layout(
            height=400,
            title_text=f"Prediction Results: {failure_type.upper()}",
            showlegend=False
        )
        
        return fig
    
    def plot_feature_importance(self, importance: Dict[str, float]) -> plt.Figure:
        """Построение графика важности признаков"""
        if not importance:
            fig, ax = plt.subplots(figsize=(10, 6))
            ax.text(0.5, 0.5, "No feature importance data available", 
                   ha='center', va='center', fontsize=14)
            ax.set_title('Feature Importance')
            return fig
            
        features = list(importance.keys())
        values = list(importance.values())
        
        fig, ax = plt.subplots(figsize=(10, 8))
        bars = ax.barh(features[:15], values[:15], color='steelblue')
        ax.set_xlabel('Importance')
        ax.set_title('Top 15 Most Important Features for Failure Prediction')
        
        # Добавление значений на бары
        for bar, val in zip(bars, values[:15]):
            ax.text(val + 0.01, bar.get_y() + bar.get_height()/2, 
                   f'{val:.3f}', va='center')
            
        plt.tight_layout()
        
        return fig
    
    def plot_alert_timeline(self, alerts: List[Dict]) -> go.Figure:
        """Построение временной линии оповещений"""
        if not alerts:
            fig = go.Figure()
            fig.add_annotation(text="No alerts available", x=0.5, y=0.5)
            return fig
            
        timestamps = [a['timestamp'] for a in alerts]
        probabilities = [a['probability'] for a in alerts]
        components = [a['component'] for a in alerts]
        
        colors = ['red' if p > 0.8 else 'orange' if p > 0.6 else 'yellow' 
                  for p in probabilities]
        
        fig = go.Figure()
        
        fig.add_trace(go.Scatter(
            x=timestamps,
            y=probabilities,
            mode='markers+lines',
            marker=dict(size=15, color=colors, symbol='circle'),
            line=dict(width=2, color='gray'),
            text=[f"{c}<br>Probability: {p:.2%}" for c, p in zip(components, probabilities)],
            hoverinfo='text+x+y'
        ))
        
        fig.update_layout(
            title='Alert Timeline',
            xaxis_title='Time',
            yaxis_title='Failure Probability',
            yaxis=dict(range=[0, 1]),
            height=400
        )
        
        return fig
    
    def save_html(self, fig: go.Figure, filename: str):
        """Сохранение графика в HTML"""
        fig.write_html(filename)
        logger.info(f"Saved plot to {filename}")