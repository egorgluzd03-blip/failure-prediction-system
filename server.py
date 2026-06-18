from flask import Flask, jsonify, render_template_string, request, Response
import time
import threading
import math
from datetime import datetime
import csv
import io

app = Flask(__name__)

# Глобальное состояние системы
state = {
    'step': 0,
    'cpu': 45.0,
    'ram': 50.0,
    'errors': 2,
    'probability': 0.0,
    'status': 'NORMAL',
    'start_time': time.time(),
    'running': True  # Флаг управления симуляцией
}

# История метрик
history = {
    'steps': [],
    'cpu': [],
    'ram': [],
    'errors': [],
    'probability': []
}
MAX_HISTORY = 100

# Параметры эмуляции
CONFIG = {
    'degradation_start': 60,
    'degradation_duration': 40,
    'seasonal_amplitude': 8,
    'noise_amplitude': 3,
    'step_interval': 1.8
}

# Глобальный поток для обновления данных
update_thread = None
thread_running = False


def calculate_cpu(step, degradation):
    seasonal = CONFIG['seasonal_amplitude'] * math.sin(step / 24.0 * 2 * math.pi)
    noise = CONFIG['noise_amplitude'] * math.sin(step * 1.7) * 0.5
    cpu = 45.0 + seasonal + noise + degradation * 55.0
    return max(0, min(100, cpu))


def calculate_ram(step, degradation):
    seasonal = CONFIG['seasonal_amplitude'] * 0.8 * math.sin((step / 24.0 + 2) * 2 * math.pi)
    noise = CONFIG['noise_amplitude'] * 0.7 * math.sin(step * 2.3)
    ram = 50.0 + seasonal + noise + degradation * 45.0
    return max(0, min(100, ram))


def calculate_errors(step, degradation):
    base = 2
    noise = int(math.sin(step * 3.1) * 1.5)
    error_growth = degradation * 25.0
    spike = 3 if (degradation > 0.3 and step % 7 == 0) else 0
    return max(0, int(base + noise + error_growth + spike))


def calculate_probability(cpu, ram, errors):
    prob = 0.0
    if cpu > 85:
        prob += 0.5
    elif cpu > 70:
        prob += 0.25
    if ram > 90:
        prob += 0.3
    elif ram > 75:
        prob += 0.15
    if errors > 15:
        prob += 0.2
    elif errors > 8:
        prob += 0.1
    return min(0.99, prob)


def get_status(probability):
    if probability > 0.7:
        return "CRITICAL"
    elif probability > 0.4:
        return "WARNING"
    else:
        return "NORMAL"


def get_rul(probability):
    if probability < 0.5:
        return "> 60 мин"
    else:
        return f"{int(60 * (1 - probability))} мин"


def update_system():
    """Основной цикл обновления системы"""
    global thread_running
    step = 0
    alert_triggered = False
    
    while thread_running:
        # Проверяем флаг running из состояния
        if not state.get('running', True):
            time.sleep(0.5)
            continue
            
        step += 1
        state['step'] = step
        
        if step > CONFIG['degradation_start']:
            degradation = min(1.0, (step - CONFIG['degradation_start']) / CONFIG['degradation_duration'])
        else:
            degradation = 0.0
        
        cpu = calculate_cpu(step, degradation)
        ram = calculate_ram(step, degradation)
        errors = calculate_errors(step, degradation)
        probability = calculate_probability(cpu, ram, errors)
        status = get_status(probability)
        
        state['cpu'] = round(cpu, 1)
        state['ram'] = round(ram, 1)
        state['errors'] = errors
        state['probability'] = round(probability * 100, 1)
        state['status'] = status
        state['rul'] = get_rul(probability)
        
        if status == "CRITICAL" and not alert_triggered:
            alert_triggered = True
            state['alert'] = True
        elif status != "CRITICAL":
            alert_triggered = False
            state['alert'] = False
        
        history['steps'].append(step)
        history['cpu'].append(round(cpu, 1))
        history['ram'].append(round(ram, 1))
        history['errors'].append(errors)
        history['probability'].append(round(probability * 100, 1))
        
        if len(history['steps']) > MAX_HISTORY:
            for key in history:
                history[key] = history[key][-MAX_HISTORY:]
        
        time.sleep(CONFIG['step_interval'])


@app.route('/')
def index():
    return render_template_string(INDEX_HTML)


@app.route('/history')
def history_page():
    return render_template_string(HISTORY_HTML)


@app.route('/docs')
def docs_page():
    return render_template_string(DOCS_HTML)


@app.route('/api/data')
def get_data():
    return jsonify({
        'step': state['step'],
        'cpu': state['cpu'],
        'ram': state['ram'],
        'errors': state['errors'],
        'probability': state['probability'],
        'status': state['status'],
        'rul': state.get('rul', '> 60 мин'),
        'alert': state.get('alert', False),
        'running': state.get('running', True),
        'time': datetime.now().strftime('%H:%M:%S')
    })


@app.route('/api/history')
def get_history():
    return jsonify({
        'steps': history['steps'][-50:],
        'cpu': history['cpu'][-50:],
        'ram': history['ram'][-50:],
        'errors': history['errors'][-50:],
        'probability': history['probability'][-50:]
    })


@app.route('/api/export')
def export_csv():
    """Экспорт данных в CSV"""
    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(['Step', 'CPU', 'RAM', 'Errors', 'Probability'])
    for i in range(len(history['steps'])):
        writer.writerow([
            history['steps'][i],
            history['cpu'][i],
            history['ram'][i],
            history['errors'][i],
            history['probability'][i]
        ])
    output = si.getvalue()
    return Response(output, mimetype='text/csv', headers={
        'Content-Disposition': 'attachment; filename=metrics_history.csv'
    })


@app.route('/api/reset')
def reset():
    """Полный сброс системы (останавливает и очищает)"""
    global thread_running
    # Останавливаем поток
    thread_running = False
    # Сбрасываем состояние
    state['step'] = 0
    state['cpu'] = 45.0
    state['ram'] = 50.0
    state['errors'] = 2
    state['probability'] = 0.0
    state['status'] = 'NORMAL'
    state['alert'] = False
    state['rul'] = '> 60 мин'
    state['running'] = False
    for key in history:
        history[key] = []
    return jsonify({'status': 'reset'})


@app.route('/api/start')
def start_simulation():
    """Запуск симуляции"""
    global thread_running, update_thread
    if thread_running:
        return jsonify({'status': 'already_running'})
    
    state['running'] = True
    thread_running = True
    update_thread = threading.Thread(target=update_system)
    update_thread.daemon = True
    update_thread.start()
    return jsonify({'status': 'started'})


@app.route('/api/stop')
def stop_simulation():
    """Остановка симуляции (сохраняет текущие данные)"""
    global thread_running
    thread_running = False
    state['running'] = False
    return jsonify({'status': 'stopped'})


@app.route('/api/status')
def get_status_info():
    """Получение статуса симуляции"""
    return jsonify({
        'running': state.get('running', False),
        'step': state['step']
    })


@app.route('/api/speed')
def set_speed():
    """Изменение скорости обновления"""
    speed = request.args.get('speed', 1.8)
    try:
        CONFIG['step_interval'] = float(speed)
        return jsonify({'status': 'ok', 'speed': CONFIG['step_interval']})
    except:
        return jsonify({'status': 'error'}), 400


# ============= HTML-ШАБЛОН ГЛАВНОЙ СТРАНИЦЫ =============
INDEX_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Система прогнозирования отказов</title>
    <style>
        :root {
            --bg: #0f0c29;
            --bg2: #1a1a2e;
            --card-bg: rgba(255,255,255,0.95);
            --text: #fff;
            --text2: #ccc;
            --border: #ddd;
            --shadow: rgba(0,0,0,0.2);
            --metric-bg: #ecf0f1;
            --metric-text: #2c3e50;
            --nav-bg: rgba(255,255,255,0.1);
        }
        [data-theme="light"] {
            --bg: #f0f2f5;
            --bg2: #e8ecf1;
            --card-bg: #ffffff;
            --text: #2c3e50;
            --text2: #555;
            --border: #ddd;
            --shadow: rgba(0,0,0,0.1);
            --metric-bg: #f8f9fa;
            --metric-text: #2c3e50;
            --nav-bg: rgba(44,62,80,0.08);
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Times New Roman', Times, serif; background: var(--bg); transition: background 0.3s; min-height: 100vh; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; margin-bottom: 20px; }
        .header h1 { font-size: 26px; color: var(--text); }
        .header p { color: var(--text2); font-size: 13px; margin-top: 4px; }
        .header-controls { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
        .theme-toggle, .speed-toggle { background: var(--nav-bg); border: none; color: var(--text); padding: 8px 16px; border-radius: 20px; cursor: pointer; font-size: 14px; font-family: 'Times New Roman', Times, serif; transition: all 0.3s; }
        .theme-toggle:hover, .speed-toggle:hover { background: #667eea; color: #fff; }
        .nav { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 20px; align-items: center; }
        .nav a { color: var(--text); text-decoration: none; padding: 8px 22px; background: var(--nav-bg); border-radius: 25px; transition: all 0.3s; font-size: 14px; }
        .nav a:hover, .nav a.active { background: #667eea; color: #fff; }
        .nav-controls { display: flex; gap: 8px; margin-left: auto; flex-wrap: wrap; }
        .status-indicator { display: flex; align-items: center; gap: 8px; margin-left: 15px; }
        .indicator-dot { width: 12px; height: 12px; border-radius: 50%; animation: pulse 1.5s infinite; }
        .indicator-dot.green { background: #27ae60; box-shadow: 0 0 8px #27ae60; }
        .indicator-dot.yellow { background: #f39c12; box-shadow: 0 0 8px #f39c12; }
        .indicator-dot.red { background: #e74c3c; box-shadow: 0 0 8px #e74c3c; }
        .indicator-dot.gray { background: #7f8c8d; box-shadow: 0 0 8px #7f8c8d; animation: none; }
        @keyframes pulse { 0% { opacity: 0.5; transform: scale(0.8); } 100% { opacity: 1; transform: scale(1.2); } }
        
        .btn { border: none; padding: 8px 18px; border-radius: 20px; cursor: pointer; font-size: 14px; font-family: 'Times New Roman', Times, serif; transition: all 0.3s; font-weight: bold; }
        .btn-start { background: #27ae60; color: white; }
        .btn-start:hover { background: #2ecc71; transform: scale(1.02); }
        .btn-start:disabled { background: #95a5a6; cursor: not-allowed; transform: none; }
        .btn-stop { background: #e74c3c; color: white; }
        .btn-stop:hover { background: #c0392b; transform: scale(1.02); }
        .btn-stop:disabled { background: #95a5a6; cursor: not-allowed; transform: none; }
        .btn-reset { background: #f39c12; color: white; }
        .btn-reset:hover { background: #d68910; transform: scale(1.02); }
        
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
        .card { background: var(--card-bg); border-radius: 15px; padding: 20px; box-shadow: 0 8px 30px var(--shadow); transition: all 0.3s; }
        .card:hover { transform: translateY(-2px); box-shadow: 0 12px 40px var(--shadow); }
        .card h3 { margin-bottom: 15px; color: var(--metric-text); border-left: 4px solid #e74c3c; padding-left: 12px; }
        .metrics { display: flex; gap: 15px; flex-wrap: wrap; }
        .metric { flex: 1; background: var(--metric-bg); border-radius: 10px; padding: 15px; text-align: center; min-width: 80px; }
        .metric-label { font-size: 11px; color: #7f8c8d; text-transform: uppercase; letter-spacing: 1px; }
        .metric-value { font-size: 28px; font-weight: bold; color: var(--metric-text); }
        .metric-value.critical { color: #e74c3c; }
        .metric-value.warning { color: #f39c12; }
        .metric-value.normal { color: #27ae60; }
        .metric-value.paused { color: #7f8c8d; }
        .prediction-card { background: linear-gradient(135deg, #667eea, #764ba2); color: white; }
        .prediction-card h3 { color: white; border-left-color: rgba(255,255,255,0.5); }
        .prediction-value { font-size: 48px; font-weight: bold; text-align: center; margin: 10px 0; }
        .progress-bar { background: rgba(255,255,255,0.2); border-radius: 10px; height: 20px; overflow: hidden; margin: 10px 0; }
        .progress-fill { background: #e74c3c; width: 0%; height: 100%; transition: width 0.5s; }
        .rul-value { font-size: 24px; font-weight: bold; text-align: center; margin-top: 10px; }
        .logs-container { height: 200px; overflow-y: auto; background: #1a1a2e; border-radius: 10px; padding: 10px; font-family: 'Consolas', monospace; font-size: 12px; color: #ccc; }
        .log-entry { padding: 4px 0; border-bottom: 1px solid #333; animation: fadeIn 0.3s; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(-10px); } to { opacity: 1; transform: translateY(0); } }
        .log-entry.info { color: #3498db; }
        .log-entry.warning { color: #f39c12; }
        .log-entry.error { color: #e74c3c; }
        .log-entry.alert { color: #e74c3c; background: rgba(231,76,60,0.15); font-weight: bold; }
        .log-entry.paused { color: #7f8c8d; font-style: italic; }
        .log-time { color: #888; margin-right: 10px; }
        .anomaly-list { min-height: 100px; }
        .anomaly-item { background: #fff3cd; border-left: 4px solid #f39c12; padding: 8px 12px; margin-bottom: 6px; border-radius: 4px; font-size: 13px; animation: fadeIn 0.3s; }
        .anomaly-item.critical { background: #f8d7da; border-left-color: #e74c3c; }
        .btn-success { background: #27ae60; }
        .btn-success:hover { background: #2ecc71; }
        .btn-info { background: #3498db; }
        .btn-info:hover { background: #5dade2; }
        .btn-group { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 15px; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th, td { padding: 8px 12px; text-align: center; border-bottom: 1px solid var(--border); }
        th { background: #34495e; color: white; }
        .status-normal { color: #27ae60; font-weight: bold; }
        .status-warning { color: #f39c12; font-weight: bold; }
        .status-critical { color: #e74c3c; font-weight: bold; }
        .status-paused { color: #7f8c8d; font-weight: bold; }
        .component-row { cursor: pointer; transition: background 0.2s; }
        .component-row:hover { background: rgba(102,126,234,0.1); }
        .footer { text-align: center; margin-top: 20px; color: var(--text2); font-size: 12px; }
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.6); justify-content: center; align-items: center; z-index: 1000; }
        .modal-content { background: white; border-radius: 15px; padding: 30px; max-width: 400px; width: 90%; box-shadow: 0 20px 60px rgba(0,0,0,0.3); }
        .modal-content h3 { margin-bottom: 15px; color: #2c3e50; }
        .modal-content p { margin: 8px 0; color: #555; }
        .modal-close { background: #e74c3c; border: none; color: white; padding: 8px 20px; border-radius: 20px; cursor: pointer; margin-top: 15px; float: right; }
        .paused-overlay { opacity: 0.6; filter: grayscale(0.3); }
        .status-badge { display: inline-block; padding: 2px 12px; border-radius: 12px; font-size: 12px; font-weight: bold; }
        .status-badge.running { background: #27ae60; color: white; }
        .status-badge.stopped { background: #e74c3c; color: white; }
        @media (max-width: 768px) { .grid { grid-template-columns: 1fr; } .header { flex-direction: column; align-items: stretch; } .header-controls { justify-content: center; } .nav { flex-direction: column; align-items: stretch; } .nav-controls { margin-left: 0; justify-content: center; } }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <div><h1>📊 СИСТЕМА ПРОГНОЗИРОВАНИЯ ОТКАЗОВ</h1><p>Анализ временных рядов метрик и логов</p></div>
        <div class="header-controls">
            <button class="theme-toggle" onclick="toggleTheme()">🌓 Тема</button>
            <button class="speed-toggle" onclick="toggleSpeed()">⏱️ Скорость: 1.8с</button>
        </div>
    </div>
    <div class="nav">
        <a href="/" class="active">📊 Дашборд</a>
        <a href="/history">📈 История</a>
        <a href="/docs">📖 Документация</a>
        <div class="nav-controls">
            <button class="btn btn-start" id="btnStart" onclick="controlSimulation('start')">▶️ Старт</button>
            <button class="btn btn-stop" id="btnStop" onclick="controlSimulation('stop')" disabled>⏹️ Стоп</button>
            <button class="btn btn-reset" onclick="resetSystem()">🔄 Сброс</button>
        </div>
        <span class="status-indicator">
            <span class="indicator-dot green" id="indicatorDot"></span>
            <span style="color:var(--text);font-size:13px;" id="indicatorText">НОРМА</span>
            <span class="status-badge running" id="statusBadge">▶️ РАБОТАЕТ</span>
        </span>
    </div>
    
    <div class="grid">
        <div class="card" id="metricsCard">
            <h3>📈 ТЕКУЩИЕ МЕТРИКИ</h3>
            <div class="metrics">
                <div class="metric"><div class="metric-label">CPU</div><div class="metric-value" id="cpu">--%</div></div>
                <div class="metric"><div class="metric-label">RAM</div><div class="metric-value" id="ram">--%</div></div>
                <div class="metric"><div class="metric-label">ОШИБКИ</div><div class="metric-value" id="errors">--</div></div>
                <div class="metric"><div class="metric-label">ШАГ</div><div class="metric-value" id="step">0</div></div>
            </div>
        </div>
        <div class="card prediction-card">
            <h3>⚠️ ПРОГНОЗ ОТКАЗА</h3>
            <div class="prediction-value" id="probability">0%</div>
            <div class="progress-bar"><div class="progress-fill" id="probFill"></div></div>
            <div style="display:flex; justify-content:space-between; font-size:12px; opacity:0.8;">
                <span>🟢 НОРМА</span><span>🟡 ВНИМАНИЕ</span><span>🔴 КРИТИЧЕСКИЙ</span>
            </div>
            <div class="rul-value" id="rul">RUL: &gt; 60 мин</div>
            <div style="text-align:center; margin-top:10px; font-size:13px; opacity:0.9;" id="statusText">Статус: НОРМА</div>
        </div>
    </div>
    
    <div class="grid">
        <div class="card">
            <h3>🔍 ОБНАРУЖЕННЫЕ АНОМАЛИИ</h3>
            <div class="anomaly-list" id="anomalyList"><div style="color:#999; text-align:center; padding:20px;">Мониторинг активен...</div></div>
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
        <table id="componentsTable"><thead><tr><th>Компонент</th><th>CPU</th><th>RAM</th><th>Ошибки</th><th>Статус</th></tr></thead><tbody></tbody></table>
        <div class="btn-group">
            <button class="btn btn-success" onclick="exportData()">📥 ЭКСПОРТ CSV</button>
        </div>
    </div>
    <div class="footer">Инфокоммуникационная система | Предиктивная аналитика | © 2026</div>
</div>

<div class="modal" id="componentModal">
    <div class="modal-content">
        <h3 id="modalTitle">Компонент</h3>
        <p id="modalInfo">Информация о компоненте</p>
        <button class="modal-close" onclick="closeModal()">Закрыть</button>
    </div>
</div>

<script>
    let alertTriggered = false;
    let speed = 1.8;
    let darkTheme = true;
    let isRunning = true;
    
    function toggleTheme() {
        darkTheme = !darkTheme;
        document.documentElement.setAttribute('data-theme', darkTheme ? '' : 'light');
        localStorage.setItem('theme', darkTheme ? 'dark' : 'light');
    }
    if (localStorage.getItem('theme') === 'light') { darkTheme = false; document.documentElement.setAttribute('data-theme', 'light'); }
    
    function toggleSpeed() {
        const speeds = [0.8, 1.8, 3.0];
        let idx = speeds.indexOf(speed);
        idx = (idx + 1) % speeds.length;
        speed = speeds[idx];
        fetch('/api/speed?speed=' + speed);
        document.querySelector('.speed-toggle').textContent = '⏱️ Скорость: ' + speed + 'с';
    }
    
    function exportData() { window.location.href = '/api/export'; }
    
    function openModal(name, cpu, ram, errors, status) {
        document.getElementById('modalTitle').textContent = '🔧 ' + name;
        document.getElementById('modalInfo').innerHTML = `
            <p><strong>CPU:</strong> ${cpu}</p>
            <p><strong>RAM:</strong> ${ram}</p>
            <p><strong>Ошибки:</strong> ${errors}</p>
            <p><strong>Статус:</strong> ${status}</p>
            <p style="margin-top:10px;font-size:12px;color:#888;">Кликните для детальной диагностики</p>
        `;
        document.getElementById('componentModal').style.display = 'flex';
    }
    function closeModal() { document.getElementById('componentModal').style.display = 'none'; }
    document.getElementById('componentModal').addEventListener('click', function(e) { if (e.target === this) closeModal(); });
    
    function addLog(msg, type='info') {
        const c = document.getElementById('logsContainer');
        const d = document.createElement('div');
        d.className = 'log-entry ' + type;
        d.innerHTML = `<span class="log-time">[${new Date().toLocaleTimeString()}]</span> ${msg}`;
        c.insertBefore(d, c.firstChild);
        while (c.children.length > 50) c.removeChild(c.lastChild);
    }
    
    function addAnomaly(msg, critical=false) {
        const c = document.getElementById('anomalyList');
        if (c.innerHTML.includes('Мониторинг активен')) c.innerHTML = '';
        const d = document.createElement('div');
        d.className = 'anomaly-item' + (critical ? ' critical' : '');
        d.innerHTML = `<strong>🕒 ${new Date().toLocaleTimeString()}</strong><br>${msg}`;
        c.insertBefore(d, c.firstChild);
        while (c.children.length > 10) c.removeChild(c.lastChild);
    }
    
    function updateComponents(cpu, ram, errors, running) {
        const comps = [
            {name:'api-gateway-01', cpuMod:0, ramMod:0, errMod:0, desc:'Основной шлюз API'},
            {name:'auth-service-01', cpuMod:-5, ramMod:-4, errMod:-1, desc:'Сервис аутентификации'},
            {name:'database-01', cpuMod:12, ramMod:14, errMod:3, desc:'База данных (нагружена)'},
            {name:'cache-01', cpuMod:-8, ramMod:-9, errMod:-1, desc:'Кэш-сервер'}
        ];
        const tbody = document.querySelector('#componentsTable tbody');
        tbody.innerHTML = '';
        comps.forEach(c => {
            let cc = Math.min(100, Math.max(0, cpu + c.cpuMod + (Math.sin(Date.now()/1000 + c.cpuMod) * 4)));
            let cr = Math.min(100, Math.max(0, ram + c.ramMod + (Math.cos(Date.now()/1000 + c.ramMod) * 3)));
            let ce = Math.max(0, errors + c.errMod + Math.floor(Math.random() * 2));
            let status = '', cls = '';
            if (!running) {
                status = 'ОСТАНОВЛЕН'; cls = 'status-paused';
            } else if (cc > 85 || cr > 90 || ce > 15) { status = 'КРИТИЧЕСКИЙ'; cls = 'status-critical'; }
            else if (cc > 70 || cr > 75 || ce > 8) { status = 'ВНИМАНИЕ'; cls = 'status-warning'; }
            else { status = 'НОРМА'; cls = 'status-normal'; }
            const row = tbody.insertRow();
            row.className = 'component-row';
            row.onclick = () => openModal(c.name, Math.round(cc)+'%', Math.round(cr)+'%', ce, status);
            row.insertCell(0).innerHTML = c.name;
            row.insertCell(1).innerHTML = Math.round(cc) + '%';
            row.insertCell(2).innerHTML = Math.round(cr) + '%';
            row.insertCell(3).innerHTML = ce;
            row.insertCell(4).innerHTML = `<span class="${cls}">${status}</span>`;
        });
    }
    
    function updateUI(data) {
        const running = data.running !== undefined ? data.running : true;
        isRunning = running;
        
        // Обновляем кнопки
        document.getElementById('btnStart').disabled = running;
        document.getElementById('btnStop').disabled = !running;
        
        // Обновляем статусный бейдж
        const badge = document.getElementById('statusBadge');
        if (running) {
            badge.textContent = '▶️ РАБОТАЕТ';
            badge.className = 'status-badge running';
        } else {
            badge.textContent = '⏸️ ОСТАНОВЛЕНА';
            badge.className = 'status-badge stopped';
        }
        
        // Обновляем значения
        document.getElementById('cpu').innerHTML = data.cpu + '%';
        document.getElementById('ram').innerHTML = data.ram + '%';
        document.getElementById('errors').innerHTML = data.errors;
        document.getElementById('step').innerHTML = data.step;
        document.getElementById('probability').innerHTML = data.probability + '%';
        document.getElementById('probFill').style.width = data.probability + '%';
        document.getElementById('rul').innerHTML = 'RUL: ' + data.rul;
        
        // Цвета метрик при остановке
        const cpuEl = document.getElementById('cpu');
        const ramEl = document.getElementById('ram');
        const errEl = document.getElementById('errors');
        const stepEl = document.getElementById('step');
        if (!running) {
            cpuEl.className = 'metric-value paused';
            ramEl.className = 'metric-value paused';
            errEl.className = 'metric-value paused';
            stepEl.className = 'metric-value paused';
        } else {
            cpuEl.className = 'metric-value';
            ramEl.className = 'metric-value';
            errEl.className = 'metric-value';
            stepEl.className = 'metric-value';
        }
        
        const st = document.getElementById('statusText');
        const dot = document.getElementById('indicatorDot');
        const it = document.getElementById('indicatorText');
        
        if (!running) {
            st.innerHTML = '⏸️ Система остановлена'; st.style.color = '#7f8c8d';
            dot.className = 'indicator-dot gray'; it.textContent = 'ОСТАНОВЛЕНА';
        } else if (data.status === 'CRITICAL') {
            st.innerHTML = '🔴 Статус: КРИТИЧЕСКИЙ РИСК!'; st.style.color = '#e74c3c';
            dot.className = 'indicator-dot red'; it.textContent = 'КРИТИЧЕСКИЙ';
        } else if (data.status === 'WARNING') {
            st.innerHTML = '🟡 Статус: ВНИМАНИЕ!'; st.style.color = '#f39c12';
            dot.className = 'indicator-dot yellow'; it.textContent = 'ВНИМАНИЕ';
        } else {
            st.innerHTML = '🟢 Статус: НОРМАЛЬНАЯ РАБОТА'; st.style.color = '#27ae60';
            dot.className = 'indicator-dot green'; it.textContent = 'НОРМА';
        }
        
        const pe = document.getElementById('probability');
        if (!running) {
            pe.style.color = '#7f8c8d';
        } else {
            pe.style.color = data.probability > 70 ? '#e74c3c' : data.probability > 40 ? '#f39c12' : '#27ae60';
        }
        
        if (data.status === 'CRITICAL' && running && !alertTriggered) {
            alertTriggered = true;
            addLog('🔴 КРИТИЧЕСКОЕ ОПОВЕЩЕНИЕ! Вероятность отказа ' + data.probability + '%', 'alert');
            addAnomaly('🚨 КРИТИЧЕСКОЕ ОПОВЕЩЕНИЕ: требуется вмешательство оператора', true);
        } else if (data.status !== 'CRITICAL' || !running) {
            alertTriggered = false;
        }
        
        if (running) {
            if (data.cpu > 85) { addLog('⚠️ Аномалия: загрузка CPU ' + data.cpu + '%', 'error'); addAnomaly('Загрузка CPU достигла ' + data.cpu + '%'); }
            if (data.ram > 85) { addLog('⚠️ Аномалия: использование RAM ' + data.ram + '%', 'error'); addAnomaly('Использование RAM достигло ' + data.ram + '%'); }
            if (data.errors > 12) { addLog('⚠️ Аномалия: частота ошибок ' + data.errors + '/мин', 'warning'); addAnomaly('Частота ошибок ' + data.errors + '/мин'); }
            if (data.step % 10 === 0 && data.status === 'NORMAL') { addLog('Сбор метрик: CPU ' + data.cpu + '%, RAM ' + data.ram + '%, ошибки ' + data.errors, 'info'); }
        }
        
        updateComponents(data.cpu, data.ram, data.errors, running);
    }
    
    function fetchData() {
        fetch('/api/data').then(r=>r.json()).then(updateUI).catch(e => console.log('Error:', e));
    }
    
    function controlSimulation(action) {
        fetch('/api/' + action).then(r => r.json()).then(() => {
            if (action === 'start') {
                addLog('▶️ Симуляция запущена', 'info');
            } else if (action === 'stop') {
                addLog('⏸️ Симуляция остановлена оператором', 'paused');
            }
            fetchData();
        });
    }
    
    function resetSystem() {
        if (!confirm('Сбросить все данные и остановить симуляцию?')) return;
        fetch('/api/reset').then(() => {
            alertTriggered = false;
            document.getElementById('anomalyList').innerHTML = '<div style="color:#999;text-align:center;padding:20px;">Мониторинг активен...</div>';
            document.getElementById('logsContainer').innerHTML = '<div class="log-entry info"><span class="log-time">[' + new Date().toLocaleTimeString() + ']</span> Система перезапущена</div>';
            document.getElementById('btnStart').disabled = false;
            document.getElementById('btnStop').disabled = true;
            addLog('🔄 Система сброшена', 'info');
            fetchData();
        });
    }
    
    fetchData();
    setInterval(fetchData, 1500);
</script>
</body>
</html>
"""


# ============= СТРАНИЦА ИСТОРИИ (без изменений) =============
HISTORY_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>История метрик</title>
    <style>
        :root {
            --bg: #0f0c29;
            --card-bg: rgba(255,255,255,0.95);
            --text: #fff;
            --text2: #ccc;
            --nav-bg: rgba(255,255,255,0.1);
            --shadow: rgba(0,0,0,0.2);
        }
        [data-theme="light"] {
            --bg: #f0f2f5;
            --card-bg: #ffffff;
            --text: #2c3e50;
            --text2: #555;
            --nav-bg: rgba(44,62,80,0.08);
            --shadow: rgba(0,0,0,0.1);
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Times New Roman', Times, serif; background: var(--bg); transition: background 0.3s; min-height: 100vh; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; margin-bottom: 20px; }
        .header h1 { font-size: 26px; color: var(--text); }
        .header p { color: var(--text2); font-size: 13px; }
        .theme-toggle { background: var(--nav-bg); border: none; color: var(--text); padding: 8px 16px; border-radius: 20px; cursor: pointer; font-family: 'Times New Roman', Times, serif; transition: all 0.3s; }
        .theme-toggle:hover { background: #667eea; color: #fff; }
        .nav { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 20px; }
        .nav a { color: var(--text); text-decoration: none; padding: 8px 22px; background: var(--nav-bg); border-radius: 25px; transition: all 0.3s; font-size: 14px; }
        .nav a:hover, .nav a.active { background: #667eea; color: #fff; }
        .card { background: var(--card-bg); border-radius: 15px; padding: 20px; box-shadow: 0 8px 30px var(--shadow); }
        .card h3 { margin-bottom: 15px; color: #2c3e50; border-left: 4px solid #e74c3c; padding-left: 12px; }
        .chart-container { position: relative; height: 350px; }
        canvas { width: 100%; height: 100%; background: #f8f9fa; border-radius: 10px; }
        .controls { display: flex; gap: 15px; flex-wrap: wrap; margin-top: 15px; align-items: center; }
        .controls label { cursor: pointer; }
        .btn { background: #2c3e50; border: none; color: white; padding: 8px 20px; border-radius: 20px; cursor: pointer; font-family: 'Times New Roman', Times, serif; transition: all 0.3s; }
        .btn:hover { background: #667eea; }
        .footer { text-align: center; margin-top: 20px; color: var(--text2); font-size: 12px; }
        @media (max-width: 768px) { .header { flex-direction: column; align-items: stretch; } }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <div><h1>📈 ИСТОРИЯ МЕТРИК</h1><p>Динамика изменения показателей системы</p></div>
        <button class="theme-toggle" onclick="toggleTheme()">🌓 Тема</button>
    </div>
    <div class="nav">
        <a href="/">📊 Дашборд</a>
        <a href="/history" class="active">📈 История</a>
        <a href="/docs">📖 Документация</a>
    </div>
    <div class="card">
        <h3>📊 ГРАФИКИ МЕТРИК</h3>
        <div class="chart-container"><canvas id="historyChart"></canvas></div>
        <div class="controls">
            <label><input type="checkbox" checked onchange="toggleMetric('cpu')"> 🟥 CPU</label>
            <label><input type="checkbox" checked onchange="toggleMetric('ram')"> 🟦 RAM</label>
            <label><input type="checkbox" checked onchange="toggleMetric('errors')"> 🟨 Ошибки</label>
            <label><input type="checkbox" checked onchange="toggleMetric('probability')"> 🟪 Вероятность</label>
            <button class="btn" onclick="loadHistory()">🔄 Обновить</button>
            <button class="btn" onclick="exportData()">📥 Экспорт CSV</button>
        </div>
    </div>
    <div class="footer">Инфокоммуникационная система | Предиктивная аналитика | © 2026</div>
</div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
    let chart = null;
    let darkTheme = true;
    let visible = { cpu: true, ram: true, errors: true, probability: true };
    const colors = { cpu: '#e74c3c', ram: '#3498db', errors: '#f39c12', probability: '#9b59b6' };
    
    function toggleTheme() {
        darkTheme = !darkTheme;
        document.documentElement.setAttribute('data-theme', darkTheme ? '' : 'light');
        localStorage.setItem('theme', darkTheme ? 'dark' : 'light');
    }
    if (localStorage.getItem('theme') === 'light') { darkTheme = false; document.documentElement.setAttribute('data-theme', 'light'); }
    
    function toggleMetric(name) { visible[name] = !visible[name]; if (chart) loadHistory(); }
    function exportData() { window.location.href = '/api/export'; }
    
    function loadHistory() {
        fetch('/api/history').then(r => r.json()).then(data => {
            const steps = data.steps || [];
            const datasets = [];
            if (visible.cpu) datasets.push({ label: 'CPU (%)', data: data.cpu || [], borderColor: colors.cpu, backgroundColor: 'rgba(231,76,60,0.1)', fill: true, tension: 0.3 });
            if (visible.ram) datasets.push({ label: 'RAM (%)', data: data.ram || [], borderColor: colors.ram, backgroundColor: 'rgba(52,152,219,0.1)', fill: true, tension: 0.3 });
            if (visible.errors) datasets.push({ label: 'Ошибки', data: data.errors || [], borderColor: colors.errors, backgroundColor: 'rgba(243,156,18,0.1)', fill: true, tension: 0.3 });
            if (visible.probability) datasets.push({ label: 'Вероятность (%)', data: data.probability || [], borderColor: colors.probability, backgroundColor: 'rgba(155,89,182,0.1)', fill: true, tension: 0.3 });
            
            if (chart) { chart.destroy(); }
            const ctx = document.getElementById('historyChart').getContext('2d');
            chart = new Chart(ctx, {
                type: 'line',
                data: { labels: steps, datasets: datasets },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    plugins: { legend: { position: 'top' } },
                    scales: { y: { beginAtZero: true } }
                }
            });
        });
    }
    loadHistory();
    setInterval(loadHistory, 5000);
</script>
</body>
</html>
"""

# ============= СТРАНИЦА ДОКУМЕНТАЦИИ (без изменений) =============
DOCS_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Документация</title>
    <style>
        :root {
            --bg: #0f0c29;
            --card-bg: rgba(255,255,255,0.95);
            --text: #fff;
            --text2: #ccc;
            --nav-bg: rgba(255,255,255,0.1);
            --shadow: rgba(0,0,0,0.2);
        }
        [data-theme="light"] {
            --bg: #f0f2f5;
            --card-bg: #ffffff;
            --text: #2c3e50;
            --text2: #555;
            --nav-bg: rgba(44,62,80,0.08);
            --shadow: rgba(0,0,0,0.1);
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Times New Roman', Times, serif; background: var(--bg); transition: background 0.3s; min-height: 100vh; padding: 20px; }
        .container { max-width: 1000px; margin: 0 auto; }
        .header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; margin-bottom: 20px; }
        .header h1 { font-size: 26px; color: var(--text); }
        .header p { color: var(--text2); font-size: 13px; }
        .theme-toggle { background: var(--nav-bg); border: none; color: var(--text); padding: 8px 16px; border-radius: 20px; cursor: pointer; font-family: 'Times New Roman', Times, serif; transition: all 0.3s; }
        .theme-toggle:hover { background: #667eea; color: #fff; }
        .nav { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 20px; }
        .nav a { color: var(--text); text-decoration: none; padding: 8px 22px; background: var(--nav-bg); border-radius: 25px; transition: all 0.3s; font-size: 14px; }
        .nav a:hover, .nav a.active { background: #667eea; color: #fff; }
        .card { background: var(--card-bg); border-radius: 15px; padding: 25px; margin-bottom: 20px; box-shadow: 0 8px 30px var(--shadow); }
        .card h3 { margin-bottom: 15px; color: #2c3e50; border-left: 4px solid #e74c3c; padding-left: 12px; }
        .card h4 { margin: 15px 0 8px; color: #2c3e50; }
        .card ul, .card ol { padding-left: 25px; line-height: 1.8; }
        .card code { background: #ecf0f1; padding: 2px 8px; border-radius: 4px; font-family: monospace; font-size: 13px; }
        .footer { text-align: center; margin-top: 20px; color: var(--text2); font-size: 12px; }
        .badge { display: inline-block; background: #27ae60; color: white; padding: 2px 12px; border-radius: 12px; font-size: 12px; }
        @media (max-width: 768px) { .header { flex-direction: column; align-items: stretch; } }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <div><h1>📖 ДОКУМЕНТАЦИЯ</h1><p>Описание системы прогнозирования отказов</p></div>
        <button class="theme-toggle" onclick="toggleTheme()">🌓 Тема</button>
    </div>
    <div class="nav">
        <a href="/">📊 Дашборд</a>
        <a href="/history">📈 История</a>
        <a href="/docs" class="active">📖 Документация</a>
    </div>
    <div class="card"><h3>📌 О СИСТЕМЕ</h3><p>Система прогнозирования отказов предназначена для автоматического обнаружения аномалий в работе инфокоммуникационных систем и прогнозирования вероятности отказов на основе анализа временных рядов метрик.</p><p style="margin-top:10px;"><span class="badge">Реальное время</span> Система анализирует поступающие метрики производительности и логи в реальном времени./p></div>
    <div class="card"><h3>🔄 АЛГОРИТМ РАБОТЫ</h3><ol><li><strong>Сбор метрик</strong> — каждые 1.8 секунды генерируются CPU, RAM и ошибки.</li><li><strong>Обработка</strong> — метрики проходят через модель вероятности отказа.</li><li><strong>Обнаружение аномалий</strong> — при превышении порогов (CPU > 85%, RAM > 85%, ошибки > 12).</li><li><strong>Прогнозирование</strong> — расчёт вероятности отказа.</li><li><strong>Оповещение</strong> — при вероятности > 70% генерируется критическое оповещение.</li></ol></div>
    <div class="card"><h3>📊 МЕТРИКИ</h3><ul><li><strong>CPU</strong> — загрузка процессора (0-100%)</li><li><strong>RAM</strong> — использование памяти (0-100%)</li><li><strong>Ошибки</strong> — частота ошибок в минуту</li><li><strong>Вероятность отказа</strong> — расчётная вероятность (0-100%)</li><li><strong>RUL</strong> — остаточный полезный ресурс</li></ul></div>
    <div class="card"><h3>🔧 API ENDPOINTS</h3><ul><li><code>GET /api/data</code> — текущие данные</li><li><code>GET /api/history</code> — история метрик</li><li><code>GET /api/export</code> — экспорт CSV</li><li><code>GET /api/reset</code> — полный сброс</li><li><code>GET /api/start</code> — запуск симуляции</li><li><code>GET /api/stop</code> — остановка симуляции</li><li><code>GET /api/status</code> — статус симуляции</li><li><code>GET /api/speed?speed=X</code> — скорость обновления</li></ul></div>
    <div class="card"><h3>⚙️ ТЕХНОЛОГИИ</h3><ul><li><strong>Backend:</strong> Python 3.14 + Flask + Gunicorn</li><li><strong>Frontend:</strong> HTML + CSS + JavaScript + Chart.js</li><li><strong>Анализ данных:</strong> Математические модели обработки временных рядов</li></ul></div>
    <div class="footer">Инфокоммуникационная система | Предиктивная аналитика | © 2026</div>
</div>
<script>
    let darkTheme = true;
    function toggleTheme() {
        darkTheme = !darkTheme;
        document.documentElement.setAttribute('data-theme', darkTheme ? '' : 'light');
        localStorage.setItem('theme', darkTheme ? 'dark' : 'light');
    }
    if (localStorage.getItem('theme') === 'light') { darkTheme = false; document.documentElement.setAttribute('data-theme', 'light'); }
</script>
</body>
</html>
"""

if __name__ == '__main__':
    # Запуск фонового потока обновления данных
    thread_running = True
    update_thread = threading.Thread(target=update_system)
    update_thread.daemon = True
    update_thread.start()
    
    # Запуск веб-сервера
    app.run(host='0.0.0.0', port=5000, debug=False)
