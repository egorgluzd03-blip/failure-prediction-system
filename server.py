from flask import Flask, jsonify, render_template_string
import time
import threading
import math
from datetime import datetime

app = Flask(__name__)

# Глобальное состояние системы
state = {
    'step': 0,
    'cpu': 45.0,
    'ram': 50.0,
    'errors': 2,
    'probability': 0.0,
    'status': 'NORMAL',
    'start_time': time.time()
}

# Параметры эмуляции
CONFIG = {
    'degradation_start': 60,      # шаг, с которого начинается деградация
    'degradation_duration': 40,   # длительность деградации в шагах
    'seasonal_amplitude': 8,      # амплитуда суточных колебаний
    'noise_amplitude': 3,         # амплитуда шума
    'step_interval': 1.8          # интервал обновления в секундах
}


def calculate_cpu(step, degradation):
    """
    Расчет загрузки CPU на основе:
    - базовой нагрузки (45%)
    - сезонных колебаний (суточный цикл)
    - деградации (линейный рост)
    - шума
    """
    # Суточный цикл (синусоида с периодом 24 часа)
    seasonal = CONFIG['seasonal_amplitude'] * math.sin(step / 24.0 * 2 * math.pi)
    
    # Шум (детерминированный, на основе шага)
    noise = CONFIG['noise_amplitude'] * math.sin(step * 1.7) * 0.5
    
    # Базовая нагрузка + сезонность + шум + деградация
    cpu = 45.0 + seasonal + noise + degradation * 55.0
    
    # Ограничение
    return max(0, min(100, cpu))


def calculate_ram(step, degradation):
    """
    Расчет использования RAM
    """
    # Суточный цикл (сдвинут относительно CPU)
    seasonal = CONFIG['seasonal_amplitude'] * 0.8 * math.sin((step / 24.0 + 2) * 2 * math.pi)
    
    # Шум
    noise = CONFIG['noise_amplitude'] * 0.7 * math.sin(step * 2.3)
    
    # Базовая нагрузка + сезонность + шум + деградация
    ram = 50.0 + seasonal + noise + degradation * 45.0
    
    return max(0, min(100, ram))


def calculate_errors(step, degradation):
    """
    Расчет количества ошибок
    """
    # Базовый уровень ошибок (2-3 в минуту)
    base = 2
    
    # Шум (целочисленный)
    noise = int(math.sin(step * 3.1) * 1.5)
    
    # Рост ошибок при деградации
    error_growth = degradation * 25.0
    
    # Дополнительные всплески при высокой нагрузке
    spike = 0
    if degradation > 0.3 and step % 7 == 0:
        spike = 3
    
    errors = base + noise + error_growth + spike
    
    return max(0, int(errors))


def calculate_probability(cpu, ram, errors):
    """
    Расчет вероятности отказа на основе текущих метрик
    """
    prob = 0.0
    
    # CPU > 85% даёт 50% вероятности
    if cpu > 85:
        prob += 0.5
    elif cpu > 70:
        prob += 0.25
    
    # RAM > 90% даёт 30% вероятности
    if ram > 90:
        prob += 0.3
    elif ram > 75:
        prob += 0.15
    
    # Ошибки > 15 в минуту дают 20% вероятности
    if errors > 15:
        prob += 0.2
    elif errors > 8:
        prob += 0.1
    
    return min(0.99, prob)


def get_status(probability):
    """
    Определение статуса на основе вероятности
    """
    if probability > 0.7:
        return "CRITICAL"
    elif probability > 0.4:
        return "WARNING"
    else:
        return "NORMAL"


def get_rul(probability):
    """
    Расчет остаточного ресурса (RUL) в минутах
    """
    if probability < 0.5:
        return "> 60 мин"
    else:
        minutes = int(60 * (1 - probability))
        return f"{minutes} мин"


def update_system():
    """
    Основной цикл обновления системы
    """
    step = 0
    alert_triggered = False
    
    while True:
        step += 1
        state['step'] = step
        
        # Расчет деградации (начинается с определённого шага)
        if step > CONFIG['degradation_start']:
            degradation = min(1.0, (step - CONFIG['degradation_start']) / CONFIG['degradation_duration'])
        else:
            degradation = 0.0
        
        # Расчёт метрик
        cpu = calculate_cpu(step, degradation)
        ram = calculate_ram(step, degradation)
        errors = calculate_errors(step, degradation)
        probability = calculate_probability(cpu, ram, errors)
        status = get_status(probability)
        
        # Обновление состояния
        state['cpu'] = round(cpu, 1)
        state['ram'] = round(ram, 1)
        state['errors'] = errors
        state['probability'] = round(probability * 100, 1)
        state['status'] = status
        state['rul'] = get_rul(probability)
        
        # Оповещение при критическом состоянии
        if status == "CRITICAL" and not alert_triggered:
            alert_triggered = True
            state['alert'] = True
        elif status != "CRITICAL":
            alert_triggered = False
            state['alert'] = False
        
        # Пауза между обновлениями
        time.sleep(CONFIG['step_interval'])


@app.route('/')
def index():
    """Главная страница - дашборд"""
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/data')
def get_data():
    """API для получения текущих данных"""
    return jsonify({
        'step': state['step'],
        'cpu': state['cpu'],
        'ram': state['ram'],
        'errors': state['errors'],
        'probability': state['probability'],
        'status': state['status'],
        'rul': state.get('rul', '> 60 мин'),
        'alert': state.get('alert', False),
        'time': datetime.now().strftime('%H:%M:%S')
    })


@app.route('/api/reset')
def reset():
    """Сброс системы"""
    state['step'] = 0
    state['cpu'] = 45.0
    state['ram'] = 50.0
    state['errors'] = 2
    state['probability'] = 0.0
    state['status'] = 'NORMAL'
    state['alert'] = False
    state['rul'] = '> 60 мин'
    return jsonify({'status': 'reset'})


# HTML-шаблон дашборда
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Система прогнозирования отказов</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Times New Roman', Times, serif;
            background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { text-align: center; margin-bottom: 30px; }
        .header h1 { font-size: 28px; color: #fff; text-shadow: 2px 2px 4px rgba(0,0,0,0.3); }
        .header p { color: #888; font-size: 14px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .card {
            background: rgba(255,255,255,0.95);
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }
        .card h3 { 
            margin-bottom: 15px; 
            color: #2c3e50; 
            border-left: 4px solid #e74c3c; 
            padding-left: 12px; 
            font-size: 16px;
        }
        .metrics { display: flex; gap: 15px; flex-wrap: wrap; }
        .metric {
            flex: 1;
            background: #ecf0f1;
            border-radius: 10px;
            padding: 15px;
            text-align: center;
            min-width: 100px;
        }
        .metric-label { font-size: 12px; color: #7f8c8d; text-transform: uppercase; letter-spacing: 1px; }
        .metric-value { font-size: 28px; font-weight: bold; color: #2c3e50; }
        .metric-value.critical { color: #e74c3c; }
        .metric-value.warning { color: #f39c12; }
        .metric-value.normal { color: #27ae60; }
        
        .prediction-card { background: linear-gradient(135deg, #667eea, #764ba2); color: white; }
        .prediction-card h3 { color: white; border-left-color: white; }
        .prediction-value { font-size: 48px; font-weight: bold; text-align: center; margin: 15px 0; }
        .progress-bar {
            background: rgba(255,255,255,0.2);
            border-radius: 10px;
            height: 20px;
            overflow: hidden;
            margin: 10px 0;
        }
        .progress-fill {
            background: #e74c3c;
            width: 0%;
            height: 100%;
            transition: width 0.5s;
        }
        .rul-value { font-size: 24px; font-weight: bold; text-align: center; margin-top: 10px; }
        
        .logs-container {
            height: 200px;
            overflow-y: auto;
            background: #1e1e1e;
            border-radius: 10px;
            padding: 10px;
            font-family: 'Consolas', monospace;
            font-size: 12px;
            color: #ccc;
        }
        .log-entry { padding: 4px 0; border-bottom: 1px solid #333; }
        .log-entry.info { color: #3498db; }
        .log-entry.warning { color: #f39c12; }
        .log-entry.error { color: #e74c3c; }
        .log-entry.alert { color: #e74c3c; background: rgba(231,76,60,0.2); font-weight: bold; }
        .log-time { color: #888; margin-right: 10px; }
        
        .anomaly-list { min-height: 120px; }
        .anomaly-item {
            background: #fff3cd;
            border-left: 4px solid #f39c12;
            padding: 8px 12px;
            margin-bottom: 6px;
            border-radius: 4px;
            font-size: 13px;
        }
        .anomaly-item.critical { background: #f8d7da; border-left-color: #e74c3c; }
        
        .btn {
            background: #2c3e50;
            border: none;
            color: white;
            padding: 8px 20px;
            border-radius: 20px;
            cursor: pointer;
            font-size: 14px;
            font-family: 'Times New Roman', Times, serif;
            transition: all 0.3s;
        }
        .btn:hover { background: #e74c3c; transform: scale(1.02); }
        
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th, td { padding: 8px 12px; text-align: center; border-bottom: 1px solid #ddd; }
        th { background: #34495e; color: white; }
        .status-normal { color: #27ae60; font-weight: bold; }
        .status-warning { color: #f39c12; font-weight: bold; }
        .status-critical { color: #e74c3c; font-weight: bold; }
        
        .footer { text-align: center; margin-top: 20px; color: #666; font-size: 12px; }
        @media (max-width: 768px) { .grid { grid-template-columns: 1fr; } }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>📊 СИСТЕМА ПРОГНОЗИРОВАНИЯ ОТКАЗОВ</h1>
        <p>Анализ временных рядов метрик и логов | LSTM + Isolation Forest (эмуляция)</p>
    </div>
    
    <div class="grid">
        <div class="card">
            <h3>📈 ТЕКУЩИЕ МЕТРИКИ</h3>
            <div class="metrics">
                <div class="metric">
                    <div class="metric-label">CPU</div>
                    <div class="metric-value" id="cpu">--%</div>
                </div>
                <div class="metric">
                    <div class="metric-label">RAM</div>
                    <div class="metric-value" id="ram">--%</div>
                </div>
                <div class="metric">
                    <div class="metric-label">ОШИБКИ</div>
                    <div class="metric-value" id="errors">--</div>
                </div>
                <div class="metric">
                    <div class="metric-label">ШАГ</div>
                    <div class="metric-value" id="step">0</div>
                </div>
            </div>
        </div>
        
        <div class="card prediction-card">
            <h3>⚠️ ПРОГНОЗ ОТКАЗА</h3>
            <div class="prediction-value" id="probability">0%</div>
            <div class="progress-bar"><div class="progress-fill" id="probFill"></div></div>
            <div style="display:flex; justify-content:space-between; font-size:12px; opacity:0.8;">
                <span>🟢 НОРМА</span>
                <span>🟡 ВНИМАНИЕ</span>
                <span>🔴 КРИТИЧЕСКИЙ</span>
            </div>
            <div class="rul-value" id="rul">RUL: &gt; 60 мин</div>
            <div style="text-align:center; margin-top:10px; font-size:13px; opacity:0.9;" id="statusText">Статус: НОРМА</div>
        </div>
    </div>
    
    <div class="grid">
        <div class="card">
            <h3>🔍 ОБНАРУЖЕННЫЕ АНОМАЛИИ</h3>
            <div class="anomaly-list" id="anomalyList">
                <div style="color:#999; text-align:center; padding:20px;">Мониторинг активен...</div>
            </div>
        </div>
        
        <div class="card">
            <h3>📋 ЖУРНАЛ СОБЫТИЙ</h3>
            <div class="logs-container" id="logsContainer">
                <div class="log-entry info"><span class="log-time">[--:--:--]</span> Система мониторинга запущена</div>
            </div>
        </div>
    </div>
    
    <div class="card">
        <h3>🖥️ СОСТОЯНИЕ КОМПОНЕНТОВ ИКС</h3>
        <table id="componentsTable">
            <thead><tr><th>Компонент</th><th>CPU</th><th>RAM</th><th>Ошибки</th><th>Статус</th></tr></thead>
            <tbody></tbody>
        </table>
        <div style="margin-top: 15px;">
            <button class="btn" onclick="resetSystem()">🔄 СБРОС СИМУЛЯЦИИ</button>
        </div>
    </div>
    
    <div class="footer">Инфокоммуникационная система | Предиктивная аналитика | © 2026</div>
</div>

<script>
    let anomalyCount = 0;
    let alertTriggered = false;
    
    function addLog(message, type = 'info') {
        const container = document.getElementById('logsContainer');
        const time = new Date().toLocaleTimeString();
        const div = document.createElement('div');
        div.className = 'log-entry ' + type;
        div.innerHTML = `<span class="log-time">[${time}]</span> ${message}`;
        container.insertBefore(div, container.firstChild);
        while (container.children.length > 50) container.removeChild(container.lastChild);
    }
    
    function addAnomaly(message, critical = false) {
        const container = document.getElementById('anomalyList');
        if (container.innerHTML.includes('Мониторинг активен')) container.innerHTML = '';
        const div = document.createElement('div');
        div.className = 'anomaly-item' + (critical ? ' critical' : '');
        const time = new Date().toLocaleTimeString();
        div.innerHTML = `<strong>🕒 ${time}</strong><br>${message}`;
        container.insertBefore(div, container.firstChild);
        while (container.children.length > 10) container.removeChild(container.lastChild);
    }
    
    function updateComponents(cpu, ram, errors) {
        const components = [
            { name: 'api-gateway-01', cpuMod: 0, ramMod: 0, errMod: 0 },
            { name: 'auth-service-01', cpuMod: -5, ramMod: -4, errMod: -1 },
            { name: 'database-01', cpuMod: +12, ramMod: +14, errMod: +3 },
            { name: 'cache-01', cpuMod: -8, ramMod: -9, errMod: -1 }
        ];
        const tbody = document.querySelector('#componentsTable tbody');
        tbody.innerHTML = '';
        components.forEach(c => {
            let cc = Math.min(100, Math.max(0, cpu + c.cpuMod + (Math.sin(Date.now()/1000 + c.cpuMod) * 4)));
            let cr = Math.min(100, Math.max(0, ram + c.ramMod + (Math.cos(Date.now()/1000 + c.ramMod) * 3)));
            let ce = Math.max(0, errors + c.errMod + Math.floor(Math.random() * 2));
            let status = '', statusClass = '';
            if (cc > 85 || cr > 90 || ce > 15) {
                status = 'КРИТИЧЕСКИЙ';
                statusClass = 'status-critical';
            } else if (cc > 70 || cr > 75 || ce > 8) {
                status = 'ВНИМАНИЕ';
                statusClass = 'status-warning';
            } else {
                status = 'НОРМА';
                statusClass = 'status-normal';
            }
            const row = tbody.insertRow();
            row.insertCell(0).innerHTML = c.name;
            row.insertCell(1).innerHTML = Math.round(cc) + '%';
            row.insertCell(2).innerHTML = Math.round(cr) + '%';
            row.insertCell(3).innerHTML = ce;
            row.insertCell(4).innerHTML = `<span class="${statusClass}">${status}</span>`;
        });
    }
    
    function fetchData() {
        fetch('/api/data')
            .then(r => r.json())
            .then(d => {
                document.getElementById('cpu').innerHTML = d.cpu + '%';
                document.getElementById('ram').innerHTML = d.ram + '%';
                document.getElementById('errors').innerHTML = d.errors;
                document.getElementById('step').innerHTML = d.step;
                document.getElementById('probability').innerHTML = d.probability + '%';
                document.getElementById('probFill').style.width = d.probability + '%';
                document.getElementById('rul').innerHTML = 'RUL: ' + d.rul;
                
                const statusText = document.getElementById('statusText');
                if (d.status === 'CRITICAL') {
                    statusText.innerHTML = '🔴 Статус: КРИТИЧЕСКИЙ РИСК!';
                    statusText.style.color = '#e74c3c';
                } else if (d.status === 'WARNING') {
                    statusText.innerHTML = '🟡 Статус: ВНИМАНИЕ!';
                    statusText.style.color = '#f39c12';
                } else {
                    statusText.innerHTML = '🟢 Статус: НОРМАЛЬНАЯ РАБОТА';
                    statusText.style.color = '#27ae60';
                }
                
                const probElem = document.getElementById('probability');
                if (d.probability > 70) {
                    probElem.style.color = '#e74c3c';
                } else if (d.probability > 40) {
                    probElem.style.color = '#f39c12';
                } else {
                    probElem.style.color = '#27ae60';
                }
                
                // Логирование при изменениях
                if (d.status === 'CRITICAL' && !alertTriggered) {
                    alertTriggered = true;
                    addLog('🔴 КРИТИЧЕСКОЕ ОПОВЕЩЕНИЕ! Вероятность отказа ' + d.probability + '%', 'alert');
                    addAnomaly('🚨 КРИТИЧЕСКОЕ ОПОВЕЩЕНИЕ: требуется вмешательство оператора', true);
                } else if (d.status !== 'CRITICAL') {
                    alertTriggered = false;
                }
                
                if (d.cpu > 85) {
                    addLog('⚠️ Аномалия: загрузка CPU ' + d.cpu + '%', 'error');
                    addAnomaly('Загрузка CPU достигла ' + d.cpu + '% (порог: 85%)');
                }
                if (d.ram > 85) {
                    addLog('⚠️ Аномалия: использование RAM ' + d.ram + '%', 'error');
                    addAnomaly('Использование RAM достигло ' + d.ram + '% (порог: 85%)');
                }
                if (d.errors > 12) {
                    addLog('⚠️ Аномалия: частота ошибок ' + d.errors + '/мин', 'warning');
                    if (d.errors > 18) {
                        addAnomaly('Критическая частота ошибок: ' + d.errors + '/мин', true);
                    } else {
                        addAnomaly('Частота ошибок ' + d.errors + '/мин (превышение нормы)');
                    }
                }
                
                if (d.step % 10 === 0 && d.status === 'NORMAL') {
                    addLog('Сбор метрик: CPU ' + d.cpu + '%, RAM ' + d.ram + '%, ошибки ' + d.errors, 'info');
                }
                
                updateComponents(d.cpu, d.ram, d.errors);
            })
            .catch(e => console.log('Ошибка:', e));
    }
    
    function resetSystem() {
        fetch('/api/reset')
            .then(r => r.json())
            .then(() => {
                alertTriggered = false;
                document.getElementById('anomalyList').innerHTML = '<div style="color:#999; text-align:center; padding:20px;">Мониторинг активен...</div>';
                document.getElementById('logsContainer').innerHTML = '<div class="log-entry info"><span class="log-time">[' + new Date().toLocaleTimeString() + ']</span> Система перезапущена</div>';
                addLog('Система сброшена оператором', 'info');
            });
    }
    
    fetchData();
    setInterval(fetchData, 1500);
</script>
</body>
</html>
"""


if __name__ == '__main__':
    # Запуск фонового потока обновления данных
    thread = threading.Thread(target=update_system)
    thread.daemon = True
    thread.start()
    
    # Запуск веб-сервера
    app.run(host='0.0.0.0', port=5000, debug=False)
