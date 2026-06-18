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
    'running': True
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

thread_running = False
update_thread = None


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
    global thread_running
    step = 0
    alert_triggered = False
    
    while thread_running:
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
    return render_template_string(HTML_TEMPLATE)


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
    global thread_running
    thread_running = False
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
    global thread_running
    thread_running = False
    state['running'] = False
    return jsonify({'status': 'stopped'})


@app.route('/api/status')
def get_status_info():
    return jsonify({
        'running': state.get('running', False),
        'step': state['step']
    })


@app.route('/api/speed')
def set_speed():
    speed = request.args.get('speed', 1.8)
    try:
        CONFIG['step_interval'] = float(speed)
        return jsonify({'status': 'ok', 'speed': CONFIG['step_interval']})
    except:
        return jsonify({'status': 'error'}), 400


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Система прогнозирования отказов</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0a0a1a;
            --sidebar-bg: #111128;
            --card-bg: #1a1a3e;
            --card-hover: #222255;
            --text: #ffffff;
            --text-secondary: #8888bb;
            --text-muted: #555577;
            --accent: #6c5ce7;
            --accent-glow: rgba(108, 92, 231, 0.3);
            --border: #2a2a5a;
            --shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
            --success: #00b894;
            --warning: #fdcb6e;
            --danger: #e17055;
            --menu-hover: rgba(108, 92, 231, 0.15);
        }
        
        [data-theme="light"] {
            --bg: #f0f2f8;
            --sidebar-bg: #ffffff;
            --card-bg: #ffffff;
            --card-hover: #f8f9fc;
            --text: #2d3436;
            --text-secondary: #636e72;
            --text-muted: #b2bec3;
            --border: #dfe6e9;
            --shadow: 0 8px 32px rgba(0, 0, 0, 0.08);
            --menu-hover: rgba(108, 92, 231, 0.08);
        }
        
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'Inter', 'Segoe UI', sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
            transition: background 0.3s, color 0.3s;
            display: flex;
        }
        
        /* ============ SIDEBAR ============ */
        .sidebar {
            width: 260px;
            min-height: 100vh;
            background: var(--sidebar-bg);
            padding: 30px 20px;
            border-right: 1px solid var(--border);
            position: sticky;
            top: 0;
            height: 100vh;
            overflow-y: auto;
            transition: background 0.3s, border-color 0.3s;
            flex-shrink: 0;
        }
        
        .sidebar-logo {
            font-size: 22px;
            font-weight: 800;
            color: var(--text);
            margin-bottom: 40px;
            display: flex;
            align-items: center;
            gap: 10px;
            letter-spacing: -0.5px;
        }
        
        .sidebar-logo span {
            color: var(--accent);
        }
        
        .sidebar-menu {
            list-style: none;
        }
        
        .sidebar-menu li {
            margin-bottom: 4px;
        }
        
        .sidebar-menu a {
            display: flex;
            align-items: center;
            gap: 14px;
            padding: 12px 16px;
            border-radius: 12px;
            color: var(--text-secondary);
            text-decoration: none;
            font-size: 14px;
            font-weight: 500;
            transition: all 0.2s;
            cursor: pointer;
        }
        
        .sidebar-menu a:hover {
            background: var(--menu-hover);
            color: var(--text);
        }
        
        .sidebar-menu a.active {
            background: var(--accent);
            color: #fff;
            box-shadow: 0 4px 20px var(--accent-glow);
        }
        
        .sidebar-menu a .icon {
            font-size: 18px;
            width: 24px;
            text-align: center;
        }
        
        .sidebar-menu .divider {
            height: 1px;
            background: var(--border);
            margin: 16px 16px;
        }
        
        .sidebar-footer {
            margin-top: 40px;
            padding: 16px;
            border-top: 1px solid var(--border);
            font-size: 12px;
            color: var(--text-muted);
        }
        
        /* ============ MAIN CONTENT ============ */
        .main {
            flex: 1;
            padding: 30px 40px;
            overflow-y: auto;
            transition: background 0.3s;
        }
        
        .main-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
            flex-wrap: wrap;
            gap: 15px;
        }
        
        .main-header h1 {
            font-size: 24px;
            font-weight: 700;
        }
        
        .main-header .greeting {
            font-size: 14px;
            color: var(--text-secondary);
        }
        
        .header-controls {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .theme-toggle {
            background: var(--card-bg);
            border: 1px solid var(--border);
            color: var(--text);
            padding: 8px 14px;
            border-radius: 10px;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.2s;
        }
        
        .theme-toggle:hover {
            background: var(--accent);
            color: #fff;
        }
        
        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 6px 16px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        
        .status-badge.running {
            background: rgba(0, 184, 148, 0.2);
            color: var(--success);
        }
        
        .status-badge.stopped {
            background: rgba(225, 112, 85, 0.2);
            color: var(--danger);
        }
        
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            display: inline-block;
        }
        
        .status-dot.green { background: var(--success); }
        .status-dot.red { background: var(--danger); }
        .status-dot.yellow { background: var(--warning); }
        .status-dot.gray { background: var(--text-muted); }
        
        /* ============ CARDS ============ */
        .cards-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .stat-card {
            background: var(--card-bg);
            padding: 20px 24px;
            border-radius: 16px;
            border: 1px solid var(--border);
            transition: all 0.3s;
            box-shadow: var(--shadow);
        }
        
        .stat-card:hover {
            transform: translateY(-4px);
            box-shadow: 0 12px 40px rgba(0, 0, 0, 0.15);
        }
        
        .stat-card .label {
            font-size: 12px;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-weight: 600;
        }
        
        .stat-card .value {
            font-size: 28px;
            font-weight: 700;
            margin-top: 6px;
        }
        
        .stat-card .value.green { color: var(--success); }
        .stat-card .value.yellow { color: var(--warning); }
        .stat-card .value.red { color: var(--danger); }
        .stat-card .value.gray { color: var(--text-muted); }
        
        /* ============ PREDICTION CARD ============ */
        .prediction-card {
            background: linear-gradient(135deg, var(--card-bg), var(--card-hover));
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 24px 30px;
            margin-bottom: 30px;
            box-shadow: var(--shadow);
        }
        
        .prediction-card .header-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }
        
        .prediction-card .title {
            font-size: 16px;
            font-weight: 600;
        }
        
        .prediction-value {
            font-size: 42px;
            font-weight: 800;
        }
        
        .progress-bar {
            width: 100%;
            height: 8px;
            background: var(--border);
            border-radius: 4px;
            overflow: hidden;
            margin: 12px 0 8px;
        }
        
        .progress-fill {
            height: 100%;
            border-radius: 4px;
            transition: width 0.5s ease;
            background: linear-gradient(90deg, var(--success), var(--warning), var(--danger));
        }
        
        .rul-text {
            font-size: 14px;
            color: var(--text-secondary);
        }
        
        /* ============ COMPONENTS TABLE ============ */
        .components-card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 20px 24px;
            box-shadow: var(--shadow);
            margin-bottom: 30px;
        }
        
        .components-card .card-title {
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 16px;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }
        
        th {
            text-align: left;
            padding: 12px 8px;
            color: var(--text-secondary);
            font-weight: 600;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 1px solid var(--border);
        }
        
        td {
            padding: 12px 8px;
            border-bottom: 1px solid var(--border);
        }
        
        .component-row {
            cursor: pointer;
            transition: background 0.15s;
        }
        
        .component-row:hover {
            background: var(--menu-hover);
        }
        
        .status-tag {
            display: inline-block;
            padding: 3px 12px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
        }
        
        .status-tag.normal { background: rgba(0, 184, 148, 0.15); color: var(--success); }
        .status-tag.warning { background: rgba(253, 203, 110, 0.15); color: var(--warning); }
        .status-tag.critical { background: rgba(225, 112, 85, 0.15); color: var(--danger); }
        .status-tag.paused { background: rgba(100, 100, 130, 0.2); color: var(--text-muted); }
        
        /* ============ BUTTONS ============ */
        .btn-group {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-top: 16px;
        }
        
        .btn {
            padding: 10px 24px;
            border: none;
            border-radius: 12px;
            font-weight: 600;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.2s;
            font-family: 'Inter', sans-serif;
        }
        
        .btn-start {
            background: var(--success);
            color: #fff;
        }
        .btn-start:hover:not(:disabled) { background: #00a381; transform: scale(1.02); }
        .btn-start:disabled { opacity: 0.4; cursor: not-allowed; }
        
        .btn-stop {
            background: var(--danger);
            color: #fff;
        }
        .btn-stop:hover:not(:disabled) { background: #c0392b; transform: scale(1.02); }
        .btn-stop:disabled { opacity: 0.4; cursor: not-allowed; }
        
        .btn-reset {
            background: var(--warning);
            color: #2d3436;
        }
        .btn-reset:hover { background: #fdcb6e; transform: scale(1.02); }
        
        .btn-export {
            background: var(--accent);
            color: #fff;
        }
        .btn-export:hover { background: #5a4bd1; transform: scale(1.02); }
        
        /* ============ ANOMALIES & LOGS ============ */
        .two-col {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .log-card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 20px 24px;
            box-shadow: var(--shadow);
        }
        
        .log-card .card-title {
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 12px;
        }
        
        .logs-container {
            height: 180px;
            overflow-y: auto;
            font-size: 12px;
            font-family: 'Courier New', monospace;
        }
        
        .log-entry {
            padding: 4px 0;
            border-bottom: 1px solid var(--border);
            display: flex;
            gap: 8px;
        }
        
        .log-entry .time { color: var(--text-muted); min-width: 70px; }
        .log-entry.info { color: #74b9ff; }
        .log-entry.warning { color: var(--warning); }
        .log-entry.error { color: var(--danger); }
        .log-entry.alert { color: var(--danger); font-weight: 700; }
        
        .anomaly-item {
            padding: 8px 12px;
            background: rgba(253, 203, 110, 0.08);
            border-left: 3px solid var(--warning);
            border-radius: 6px;
            margin-bottom: 6px;
            font-size: 13px;
        }
        
        .anomaly-item.critical {
            background: rgba(225, 112, 85, 0.08);
            border-left-color: var(--danger);
        }
        
        .anomaly-item .time {
            color: var(--text-muted);
            font-size: 11px;
        }
        
        /* ============ RESPONSIVE ============ */
        @media (max-width: 968px) {
            .two-col { grid-template-columns: 1fr; }
        }
        
        @media (max-width: 768px) {
            .sidebar { width: 72px; padding: 20px 10px; }
            .sidebar-logo { font-size: 18px; justify-content: center; }
            .sidebar-logo span { display: none; }
            .sidebar-menu a span { display: none; }
            .sidebar-menu a { justify-content: center; padding: 12px; }
            .sidebar-footer { display: none; }
            .main { padding: 20px; }
            .cards-grid { grid-template-columns: 1fr 1fr; }
        }
        
        @media (max-width: 480px) {
            .cards-grid { grid-template-columns: 1fr; }
            .main-header { flex-direction: column; align-items: stretch; }
            .header-controls { flex-wrap: wrap; }
        }
    </style>
</head>
<body>

<!-- ===== SIDEBAR ===== -->
<nav class="sidebar">
    <div class="sidebar-logo">
        📊 <span>Система</span>
    </div>
    <ul class="sidebar-menu">
        <li><a href="#" class="active" onclick="switchTab('dashboard')"><span class="icon">📊</span> <span>Дашборд</span></a></li>
        <li><a href="#" onclick="switchTab('history')"><span class="icon">📈</span> <span>История</span></a></li>
        <li><a href="#" onclick="switchTab('docs')"><span class="icon">📖</span> <span>Документация</span></a></li>
        <li class="divider"></li>
        <li><a href="#" onclick="switchTab('settings')"><span class="icon">⚙️</span> <span>Настройки</span></a></li>
    </ul>
    <div class="sidebar-footer">
        v2.0 · Предиктивная аналитика
    </div>
</nav>

<!-- ===== MAIN ===== -->
<div class="main">

    <!-- HEADER -->
    <header class="main-header">
        <div>
            <h1 id="pageTitle">📊 Дашборд</h1>
            <div class="greeting" id="statusText">🟢 Система активна</div>
        </div>
        <div class="header-controls">
            <span class="status-badge running" id="statusBadge">
                <span class="status-dot green" id="indicatorDot"></span>
                <span id="indicatorText">НОРМА</span>
            </span>
            <button class="theme-toggle" onclick="toggleTheme()">🌓</button>
        </div>
    </header>

    <!-- ===== TAB: DASHBOARD ===== -->
    <div id="tab-dashboard">

        <!-- STAT CARDS -->
        <div class="cards-grid">
            <div class="stat-card">
                <div class="label">CPU</div>
                <div class="value" id="cpu">--%</div>
            </div>
            <div class="stat-card">
                <div class="label">RAM</div>
                <div class="value" id="ram">--%</div>
            </div>
            <div class="stat-card">
                <div class="label">Ошибки</div>
                <div class="value" id="errors">--</div>
            </div>
            <div class="stat-card">
                <div class="label">Шаг</div>
                <div class="value" id="step">0</div>
            </div>
        </div>

        <!-- PREDICTION -->
        <div class="prediction-card">
            <div class="header-row">
                <span class="title">⚠️ Прогноз отказа</span>
                <span class="rul-text" id="rul">RUL: &gt; 60 мин</span>
            </div>
            <div class="prediction-value" id="probability">0%</div>
            <div class="progress-bar"><div class="progress-fill" id="probFill" style="width:0%"></div></div>
            <div style="display:flex; justify-content:space-between; font-size:12px; color:var(--text-secondary); margin-top:4px;">
                <span>🟢 НОРМА</span>
                <span>🟡 ВНИМАНИЕ</span>
                <span>🔴 КРИТИЧЕСКИЙ</span>
            </div>
            <div class="btn-group">
                <button class="btn btn-start" id="btnStart" onclick="controlSimulation('start')">▶️ Старт</button>
                <button class="btn btn-stop" id="btnStop" onclick="controlSimulation('stop')" disabled>⏹️ Стоп</button>
                <button class="btn btn-reset" onclick="resetSystem()">🔄 Сброс</button>
                <button class="btn btn-export" onclick="exportData()">📥 CSV</button>
            </div>
        </div>

        <!-- TWO COLUMN: ANOMALIES + LOGS -->
        <div class="two-col">
            <div class="log-card">
                <div class="card-title">🔍 Аномалии</div>
                <div id="anomalyList"><div style="color:var(--text-muted); padding:10px 0; font-size:13px;">Мониторинг активен...</div></div>
            </div>
            <div class="log-card">
                <div class="card-title">📋 Логи</div>
                <div class="logs-container" id="logsContainer">
                    <div class="log-entry info"><span class="time">[--:--:--]</span> Система запущена</div>
                </div>
            </div>
        </div>

        <!-- COMPONENTS -->
        <div class="components-card">
            <div class="card-title">🖥️ Состояние компонентов ИКС</div>
            <table>
                <thead><tr><th>Компонент</th><th>CPU</th><th>RAM</th><th>Ошибки</th><th>Статус</th></tr></thead>
                <tbody id="componentsTable"></tbody>
            </table>
        </div>
    </div>

    <!-- ===== TAB: HISTORY ===== -->
    <div id="tab-history" style="display:none;">
        <div class="components-card">
            <div class="card-title">📈 История метрик</div>
            <div style="height:350px; background:var(--card-hover); border-radius:12px; padding:10px; position:relative;">
                <canvas id="historyChart" style="width:100%; height:100%;"></canvas>
            </div>
            <div style="display:flex; gap:16px; flex-wrap:wrap; margin-top:16px; align-items:center;">
                <label><input type="checkbox" checked onchange="toggleMetric('cpu')"> 🔴 CPU</label>
                <label><input type="checkbox" checked onchange="toggleMetric('ram')"> 🔵 RAM</label>
                <label><input type="checkbox" checked onchange="toggleMetric('errors')"> 🟡 Ошибки</label>
                <label><input type="checkbox" checked onchange="toggleMetric('probability')"> 🟣 Вероятность</label>
                <button class="btn btn-export" onclick="loadHistory()">🔄 Обновить</button>
                <button class="btn btn-export" onclick="exportData()">📥 CSV</button>
            </div>
        </div>
    </div>

    <!-- ===== TAB: DOCS ===== -->
    <div id="tab-docs" style="display:none;">
        <div class="components-card">
            <div class="card-title">📖 О системе</div>
            <p style="color:var(--text-secondary); line-height:1.8; margin-bottom:16px;">
                Система прогнозирования отказов предназначена для автоматического обнаружения аномалий 
                в работе инфокоммуникационных систем и прогнозирования вероятности отказов на основе 
                анализа временных рядов метрик.
            </p>
            <h4 style="margin:16px 0 8px;">🔄 Алгоритм работы</h4>
            <ol style="color:var(--text-secondary); line-height:2; padding-left:20px;">
                <li><strong>Сбор метрик</strong> — каждые 1.8 секунды анализируются CPU, RAM и ошибки</li>
                <li><strong>Обработка</strong> — метрики проходят через модель вероятности отказа</li>
                <li><strong>Обнаружение аномалий</strong> — при превышении порогов (CPU > 85%, RAM > 85%, ошибки > 12)</li>
                <li><strong>Прогнозирование</strong> — расчёт вероятности отказа</li>
                <li><strong>Оповещение</strong> — при вероятности > 70% генерируется критическое оповещение</li>
            </ol>
            <h4 style="margin:16px 0 8px;">🔧 API</h4>
            <ul style="color:var(--text-secondary); line-height:2; padding-left:20px;">
                <li><code style="background:var(--menu-hover); padding:2px 8px; border-radius:4px;">GET /api/data</code> — текущие данные</li>
                <li><code style="background:var(--menu-hover); padding:2px 8px; border-radius:4px;">GET /api/history</code> — история метрик</li>
                <li><code style="background:var(--menu-hover); padding:2px 8px; border-radius:4px;">GET /api/export</code> — экспорт CSV</li>
                <li><code style="background:var(--menu-hover); padding:2px 8px; border-radius:4px;">GET /api/start</code> / <code>/api/stop</code> / <code>/api/reset</code></li>
            </ul>
            <h4 style="margin:16px 0 8px;">⚙️ Технологии</h4>
            <ul style="color:var(--text-secondary); line-height:2; padding-left:20px;">
                <li><strong>Backend:</strong> Python 3.14 + Flask + Gunicorn</li>
                <li><strong>Frontend:</strong> HTML + CSS + JavaScript + Chart.js</li>
            </ul>
        </div>
    </div>

    <!-- ===== TAB: SETTINGS ===== -->
    <div id="tab-settings" style="display:none;">
        <div class="components-card">
            <div class="card-title">⚙️ Настройки</div>
            <div style="display:flex; flex-direction:column; gap:20px;">
                <div>
                    <label style="display:block; margin-bottom:6px; font-weight:600;">Скорость обновления</label>
                    <button class="btn btn-export" onclick="setSpeed(0.8)">0.8с (быстро)</button>
                    <button class="btn btn-export" onclick="setSpeed(1.8)">1.8с (средне)</button>
                    <button class="btn btn-export" onclick="setSpeed(3.0)">3.0с (медленно)</button>
                    <span style="margin-left:16px; color:var(--text-secondary);" id="currentSpeed">Текущая: 1.8с</span>
                </div>
                <div>
                    <label style="display:block; margin-bottom:6px; font-weight:600;">Тема</label>
                    <button class="btn btn-export" onclick="toggleTheme()">🌓 Переключить тему</button>
                </div>
                <div>
                    <label style="display:block; margin-bottom:6px; font-weight:600;">Управление</label>
                    <button class="btn btn-start" onclick="controlSimulation('start')">▶️ Старт</button>
                    <button class="btn btn-stop" onclick="controlSimulation('stop')">⏹️ Стоп</button>
                    <button class="btn btn-reset" onclick="resetSystem()">🔄 Сброс</button>
                </div>
            </div>
        </div>
    </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
    // ============ STATE ============
    let darkTheme = true;
    let alertTriggered = false;
    let chart = null;
    let visible = { cpu: true, ram: true, errors: true, probability: true };
    const colors = { cpu: '#e17055', ram: '#74b9ff', errors: '#fdcb6e', probability: '#6c5ce7' };
    
    // ============ THEME ============
    function toggleTheme() {
        darkTheme = !darkTheme;
        document.documentElement.setAttribute('data-theme', darkTheme ? '' : 'light');
        localStorage.setItem('theme', darkTheme ? 'dark' : 'light');
    }
    if (localStorage.getItem('theme') === 'light') { darkTheme = false; document.documentElement.setAttribute('data-theme', 'light'); }
    
    // ============ TABS ============
    function switchTab(tab) {
        document.querySelectorAll('#tab-dashboard, #tab-history, #tab-docs, #tab-settings').forEach(el => el.style.display = 'none');
        document.getElementById('tab-' + tab).style.display = 'block';
        document.querySelectorAll('.sidebar-menu a').forEach(el => el.classList.remove('active'));
        const titles = { dashboard:'📊 Дашборд', history:'📈 История', docs:'📖 Документация', settings:'⚙️ Настройки' };
        document.getElementById('pageTitle').textContent = titles[tab] || '📊 Дашборд';
        document.querySelectorAll('.sidebar-menu a')[['dashboard','history','docs','settings'].indexOf(tab)].classList.add('active');
        if (tab === 'history') loadHistory();
    }
    
    // ============ SPEED ============
    function setSpeed(s) {
        fetch('/api/speed?speed=' + s);
        document.getElementById('currentSpeed').textContent = 'Текущая: ' + s + 'с';
    }
    
    // ============ EXPORT ============
    function exportData() { window.location.href = '/api/export'; }
    
    // ============ LOGS & ANOMALIES ============
    function addLog(msg, type='info') {
        const c = document.getElementById('logsContainer');
        const d = document.createElement('div');
        d.className = 'log-entry ' + type;
        d.innerHTML = `<span class="time">[${new Date().toLocaleTimeString()}]</span> ${msg}`;
        c.insertBefore(d, c.firstChild);
        while (c.children.length > 50) c.removeChild(c.lastChild);
    }
    
    function addAnomaly(msg, critical=false) {
        const c = document.getElementById('anomalyList');
        if (c.innerHTML.includes('Мониторинг активен')) c.innerHTML = '';
        const d = document.createElement('div');
        d.className = 'anomaly-item' + (critical ? ' critical' : '');
        d.innerHTML = `<span class="time">🕒 ${new Date().toLocaleTimeString()}</span><br>${msg}`;
        c.insertBefore(d, c.firstChild);
        while (c.children.length > 10) c.removeChild(c.lastChild);
    }
    
    // ============ COMPONENTS TABLE ============
    function updateComponents(cpu, ram, errors, running) {
        const comps = [
            {name:'API Gateway', cpuMod:0, ramMod:0, errMod:0},
            {name:'Auth Service', cpuMod:-5, ramMod:-4, errMod:-1},
            {name:'Database', cpuMod:12, ramMod:14, errMod:3},
            {name:'Cache Server', cpuMod:-8, ramMod:-9, errMod:-1}
        ];
        const tbody = document.getElementById('componentsTable');
        tbody.innerHTML = '';
        comps.forEach(c => {
            let cc = Math.min(100, Math.max(0, cpu + c.cpuMod + (Math.sin(Date.now()/1000 + c.cpuMod) * 4)));
            let cr = Math.min(100, Math.max(0, ram + c.ramMod + (Math.cos(Date.now()/1000 + c.ramMod) * 3)));
            let ce = Math.max(0, errors + c.errMod + Math.floor(Math.random() * 2));
            let status = '', cls = '';
            if (!running) { status = 'ОСТАНОВЛЕН'; cls = 'paused'; }
            else if (cc > 85 || cr > 90 || ce > 15) { status = 'КРИТИЧЕСКИЙ'; cls = 'critical'; }
            else if (cc > 70 || cr > 75 || ce > 8) { status = 'ВНИМАНИЕ'; cls = 'warning'; }
            else { status = 'НОРМА'; cls = 'normal'; }
            const row = tbody.insertRow();
            row.className = 'component-row';
            row.insertCell(0).textContent = c.name;
            row.insertCell(1).textContent = Math.round(cc) + '%';
            row.insertCell(2).textContent = Math.round(cr) + '%';
            row.insertCell(3).textContent = ce;
            row.insertCell(4).innerHTML = `<span class="status-tag ${cls}">${status}</span>`;
        });
    }
    
    // ============ HISTORY CHART ============
    function toggleMetric(name) { visible[name] = !visible[name]; loadHistory(); }
    
    function loadHistory() {
        fetch('/api/history').then(r => r.json()).then(data => {
            const steps = data.steps || [];
            const datasets = [];
            if (visible.cpu) datasets.push({ label: 'CPU (%)', data: data.cpu || [], borderColor: colors.cpu, backgroundColor: 'rgba(225,112,85,0.1)', fill: true, tension: 0.3 });
            if (visible.ram) datasets.push({ label: 'RAM (%)', data: data.ram || [], borderColor: colors.ram, backgroundColor: 'rgba(116,185,255,0.1)', fill: true, tension: 0.3 });
            if (visible.errors) datasets.push({ label: 'Ошибки', data: data.errors || [], borderColor: colors.errors, backgroundColor: 'rgba(253,203,110,0.1)', fill: true, tension: 0.3 });
            if (visible.probability) datasets.push({ label: 'Вероятность (%)', data: data.probability || [], borderColor: colors.probability, backgroundColor: 'rgba(108,92,231,0.1)', fill: true, tension: 0.3 });
            if (chart) { chart.destroy(); }
            const ctx = document.getElementById('historyChart').getContext('2d');
            chart = new Chart(ctx, {
                type: 'line',
                data: { labels: steps, datasets: datasets },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'top' } }, scales: { y: { beginAtZero: true } } }
            });
        });
    }
    
    // ============ UPDATE UI ============
    function updateUI(data) {
        const running = data.running !== undefined ? data.running : true;
        
        document.getElementById('cpu').textContent = data.cpu + '%';
        document.getElementById('ram').textContent = data.ram + '%';
        document.getElementById('errors').textContent = data.errors;
        document.getElementById('step').textContent = data.step;
        document.getElementById('probability').textContent = data.probability + '%';
        document.getElementById('probFill').style.width = data.probability + '%';
        document.getElementById('rul').textContent = 'RUL: ' + data.rul;
        
        document.getElementById('btnStart').disabled = running;
        document.getElementById('btnStop').disabled = !running;
        
        const badge = document.getElementById('statusBadge');
        if (running) {
            badge.className = 'status-badge running';
            badge.innerHTML = '<span class="status-dot green" id="indicatorDot"></span><span id="indicatorText">НОРМА</span>';
        } else {
            badge.className = 'status-badge stopped';
            badge.innerHTML = '<span class="status-dot gray" id="indicatorDot"></span><span id="indicatorText">ОСТАНОВЛЕНА</span>';
        }
        
        const st = document.getElementById('statusText');
        const dot = document.getElementById('indicatorDot');
        const it = document.getElementById('indicatorText');
        if (!running) {
            st.textContent = '⏸️ Система остановлена';
            dot.className = 'status-dot gray';
            it.textContent = 'ОСТАНОВЛЕНА';
        } else if (data.status === 'CRITICAL') {
            st.textContent = '🔴 КРИТИЧЕСКИЙ РИСК!';
            dot.className = 'status-dot red';
            it.textContent = 'КРИТИЧЕСКИЙ';
        } else if (data.status === 'WARNING') {
            st.textContent = '🟡 ВНИМАНИЕ!';
            dot.className = 'status-dot yellow';
            it.textContent = 'ВНИМАНИЕ';
        } else {
            st.textContent = '🟢 Система активна';
            dot.className = 'status-dot green';
            it.textContent = 'НОРМА';
        }
        
        const pe = document.getElementById('probability');
        if (!running) pe.style.color = 'var(--text-muted)';
        else if (data.probability > 70) pe.style.color = '#e17055';
        else if (data.probability > 40) pe.style.color = '#fdcb6e';
        else pe.style.color = '#00b894';
        
        if (data.status === 'CRITICAL' && running && !alertTriggered) {
            alertTriggered = true;
            addLog('🔴 КРИТИЧЕСКОЕ ОПОВЕЩЕНИЕ! Вероятность отказа ' + data.probability + '%', 'alert');
            addAnomaly('🚨 КРИТИЧЕСКОЕ ОПОВЕЩЕНИЕ: требуется вмешательство оператора', true);
        } else if (data.status !== 'CRITICAL' || !running) { alertTriggered = false; }
        
        if (running) {
            if (data.cpu > 85) { addLog('⚠️ Аномалия: CPU ' + data.cpu + '%', 'error'); addAnomaly('Загрузка CPU достигла ' + data.cpu + '%'); }
            if (data.ram > 85) { addLog('⚠️ Аномалия: RAM ' + data.ram + '%', 'error'); addAnomaly('Использование RAM достигло ' + data.ram + '%'); }
            if (data.errors > 12) { addLog('⚠️ Аномалия: ошибки ' + data.errors + '/мин', 'warning'); addAnomaly('Частота ошибок ' + data.errors + '/мин'); }
            if (data.step % 10 === 0 && data.status === 'NORMAL') {
                addLog('📊 CPU ' + data.cpu + '%, RAM ' + data.ram + '%, ошибки ' + data.errors, 'info');
            }
        }
        updateComponents(data.cpu, data.ram, data.errors, running);
    }
    
    // ============ API CALLS ============
    function fetchData() {
        fetch('/api/data').then(r => r.json()).then(updateUI).catch(e => console.log('Error:', e));
    }
    
    function controlSimulation(action) {
        fetch('/api/' + action).then(r => r.json()).then(() => {
            if (action === 'start') addLog('▶️ Симуляция запущена', 'info');
            else if (action === 'stop') addLog('⏸️ Симуляция остановлена', 'paused');
            fetchData();
        });
    }
    
    function resetSystem() {
        if (!confirm('Сбросить все данные и остановить симуляцию?')) return;
        fetch('/api/reset').then(() => {
            alertTriggered = false;
            document.getElementById('anomalyList').innerHTML = '<div style="color:var(--text-muted); padding:10px 0; font-size:13px;">Мониторинг активен...</div>';
            document.getElementById('logsContainer').innerHTML = '<div class="log-entry info"><span class="time">[' + new Date().toLocaleTimeString() + ']</span> Система перезапущена</div>';
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

if __name__ == '__main__':
    global thread_running
    thread_running = True
    update_thread = threading.Thread(target=update_system)
    update_thread.daemon = True
    update_thread.start()
    app.run(host='0.0.0.0', port=5000, debug=False)
