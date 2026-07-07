const API = "http://127.0.0.1:8000";
let lastAssistantPayload = null;
let equityChartInstance = null;

function id(x) {
  return document.getElementById(x);
}

function setValue(idName, val) {
  const el = id(idName);
  if (el && val !== undefined && val !== null) el.value = val;
}

function setMetric(idName, val, isPercent) {
  const el = id(idName);
  if (!el) return;
  el.textContent = isPercent ? `${val}%` : val;
  el.className = `metric-value ${typeof val === 'number' ? (val > 0 ? 'positive' : val < 0 ? 'negative' : 'neutral') : ''}`;
}

function formatStrategyLabel(idName) {
  return {
    golden_cross: 'Golden Cross',
    mean_reversion: 'Mean Reversion',
    rsi_strategy: 'RSI Bounce',
    macd_crossover: 'MACD Crossover',
    momentum_breakout: 'Momentum Breakout',
  }[idName] || idName;
}

/* Persist the assistant payload on the backend instead of sessionStorage.
   This survives full page reloads and works across separately opened tabs. */
async function persistAssistantPayload(data) {
  try {
    await fetch(`${API}/api/state/latest-assistant`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  } catch (err) {
    console.warn('Failed to persist assistant payload to backend:', err.message);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  bindStrategyVisibility();
  bindAssistant();
  bindBacktest();
  bindOptimize();
  bindTabSwitcher();
});

function bindTabSwitcher() {
  document.querySelectorAll('[data-tab-target]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const target = btn.dataset.tabTarget;
      document.querySelectorAll('[data-tab-target]').forEach((b) => b.classList.remove('active'));
      document.querySelectorAll('[data-tab]').forEach((p) => p.classList.toggle('hidden', p.dataset.tab !== target));
      btn.classList.add('active');
    });
  });
}

function bindStrategyVisibility() {
  const sel = id('strategy-select');
  if (!sel) return;
  const apply = () => {
    const isMR = sel.value === 'mean_reversion';
    const sg = id('slow-ma-group');
    const mk = id('mr-k-group');
    if (sg) sg.style.display = isMR ? 'none' : '';
    if (mk) mk.style.display = isMR ? '' : 'none';
  };
  sel.addEventListener('change', apply);
  apply();
}

function bindAssistant() {
  const btn = id('bt-ai-submit');
  const input = id('bt-ai-input');
  const apply = id('bt-ai-apply');
  if (btn) btn.addEventListener('click', () => runAssistant());
  if (input) input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') runAssistant();
  });
  if (apply) apply.addEventListener('click', applyAssistantPayloadToForm);
  document.querySelectorAll('.bt-ai-chip').forEach((chip) => chip.addEventListener('click', () => {
    if (input) input.value = chip.dataset.prompt;
    runAssistant(chip.dataset.prompt);
  }));
}

async function runAssistant(promptOverride) {
  const input = id('bt-ai-input');
  const result = id('bt-ai-result');
  const status = id('bt-ai-status');
  const btn = id('bt-ai-submit');
  const prompt = promptOverride || input?.value?.trim();
  if (!prompt) {
    if (status) status.textContent = 'Enter a strategy prompt first.';
    return;
  }
  try {
    if (btn) btn.disabled = true;
    if (status) status.textContent = 'Generating strategy suggestion...';
    const res = await fetch(`${API}/api/assistant/suggest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt,
        ticker: id('ticker')?.value?.trim() || 'RELIANCE.NS',
        interval: id('interval')?.value || '1d',
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Assistant request failed.');
    lastAssistantPayload = data;
    await persistAssistantPayload(data);
    renderAssistantSuggestion(data);
    if (result) result.style.display = 'block';
    if (status) status.textContent = 'Suggestion ready — review and apply it.';
  } catch (err) {
    if (status) status.textContent = `Assistant error: ${err.message}`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

function renderAssistantSuggestion(s) {
  const label = id('bt-ai-label');
  const desc = id('bt-ai-description');
  const meta = id('bt-ai-meta');
  const schema = id('bt-ai-schema');
  if (label) label.textContent = formatStrategyLabel(s.strategy_id);
  if (desc) desc.textContent = s.assistant_rationale;
  if (meta) meta.textContent = `Ticker ${s.ticker} • Interval ${s.interval} • Risk ${s.risk_profile} • Mode ${s.market_mode}`;
  if (schema) schema.textContent = JSON.stringify(s, null, 2);
}

function applyAssistantPayloadToForm() {
  const s = lastAssistantPayload;
  if (!s) return;
  setValue('strategy-select', s.strategy_id);
  setValue('ticker', s.ticker);
  setValue('interval', s.interval);
  setValue('fast-ma', s.entry_logic?.fast_ma ?? 20);
  setValue('slow-ma', s.entry_logic?.slow_ma ?? 50);
  setValue('mr-k', s.entry_logic?.mr_k ?? 2.0);
  setValue('capital', s.execution_rules?.initial_capital ?? 100000);
  setValue('risk', s.execution_rules?.risk_percent ?? 2.0);
  setValue('stop-loss', s.exit_logic?.stop_loss_pct ?? 2.0);
  setValue('take-profit', s.exit_logic?.take_profit_pct ?? 6.0);
  setValue('slippage', s.execution_rules?.slippage_pct ?? 0.1);
  setValue('transaction-cost', s.execution_rules?.transaction_cost_pct ?? 0.05);
  bindStrategyVisibility();
  const rationale = id('assistant-rationale');
  if (rationale) rationale.textContent = s.assistant_rationale;
}

function bindBacktest() {
  const form = id('backtest-form');
  if (!form) return;
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    runBacktest();
  });
}

async function runBacktest() {
  const statusEl = id('results-status');
  const btn = document.querySelector('#backtest-form button[type="submit"]');
  if (statusEl) statusEl.textContent = 'Running backtest...';
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Running...';
  }
  try {
    const payload = {
      strategy: id('strategy-select')?.value,
      ticker: id('ticker')?.value?.trim().toUpperCase(),
      startDate: id('start-date')?.value,
      endDate: id('end-date')?.value,
      fastMA: parseFloat(id('fast-ma')?.value || 20),
      slowMA: parseFloat(id('slow-ma')?.value || 50),
      mrK: parseFloat(id('mr-k')?.value || 2.0),
      initialCapital: parseFloat(id('capital')?.value || 100000),
      riskPercent: parseFloat(id('risk')?.value || 2.0),
      atrPeriod: parseFloat(id('atr-period')?.value || 14),
      stopLoss: parseFloat(id('stop-loss')?.value || 2.0),
      takeProfit: parseFloat(id('take-profit')?.value || 6.0),
      slippage: parseFloat(id('slippage')?.value || 0.1),
      transactionCost: parseFloat(id('transaction-cost')?.value || 0.05),
      interval: id('interval')?.value || '1d',
    };
    const res = await fetch(`${API}/api/backtest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Backtest failed.');
    if (statusEl) {
      statusEl.textContent = `Backtest complete for ${data.ticker}.`;
      statusEl.style.color = 'var(--success, #10b981)';
    }
    renderMetrics(data.metrics);
    renderTradeTable(data.trades);
    renderEquityChart(data.chartData);
  } catch (err) {
    if (statusEl) {
      statusEl.textContent = err.message;
      statusEl.style.color = 'var(--danger, #ef4444)';
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Run Backtest';
    }
  }
}

function renderMetrics(m) {
  setMetric('metric-total-return', m.totalReturn, true);
  setMetric('metric-max-dd', m.maxDrawdown, true);
  setMetric('metric-sharpe', m.sharpeRatio, false);
  setMetric('metric-winrate', m.winRate, true);
  setMetric('metric-trades', m.totalTrades, false);
  const fin = id('metric-final');
  if (fin) fin.textContent = Number(m.finalValue || 0).toLocaleString('en-IN');
}

function renderTradeTable(trades) {
  const tbody = id('trade-table-body');
  if (!tbody) return;
  if (!trades.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:24px;color:var(--text-muted)">No completed trades found.</td></tr>';
    return;
  }
  tbody.innerHTML = trades.map((t) => {
    const win = (t.pnl ?? 0) >= 0;
    return `<tr>
      <td>${t.date ?? '--'}</td>
      <td style="color:${t.signal === 'BUY' ? '#22d3ee' : '#f43f5e'};font-weight:600">${t.signal ?? '--'}</td>
      <td>${t.entryPrice ?? '--'}</td>
      <td>${t.exitPrice ?? '--'}</td>
      <td style="color:${win ? '#10b981' : '#ef4444'}">${t.pnl ?? '--'}</td>
      <td style="color:${win ? '#10b981' : '#ef4444'}">${t.pnlPct ?? '--'}</td>
    </tr>`;
  }).join('');
}

function renderEquityChart(points) {
  const canvas = id('equity-chart');
  if (!canvas || typeof Chart === 'undefined' || !points.length) return;
  if (equityChartInstance) equityChartInstance.destroy();
  const tickCol = '#a1a1aa';
  const gridCol = 'rgba(255,255,255,0.06)';
  equityChartInstance = new Chart(canvas.getContext('2d'), {
    type: 'line',
    data: {
      labels: points.map((p) => p.date),
      datasets: [
        {
          label: 'Strategy',
          data: points.map((p) => p.strategy),
          borderColor: '#22d3ee',
          borderWidth: 2,
          pointRadius: 0,
          fill: true,
          backgroundColor: 'rgba(34,211,238,0.07)',
          tension: 0.3,
        },
        {
          label: 'Buy Hold',
          data: points.map((p) => p.buyHold),
          borderColor: '#f59e0b',
          borderWidth: 1.5,
          pointRadius: 0,
          borderDash: [5, 4],
          tension: 0.3,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: { legend: { labels: { color: tickCol, boxWidth: 16 } } },
      scales: {
        x: { ticks: { color: tickCol, maxTicksLimit: 8 }, grid: { color: gridCol } },
        y: { ticks: { color: tickCol }, grid: { color: gridCol } },
      },
    },
  });
}

function bindOptimize() {
  const form = id('optimize-form');
  if (form) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      runOptimize();
    });
  }
}

async function runOptimize() {
  const statusEl = id('opt-status');
  const btn = document.querySelector('#optimize-form button[type="submit"]');
  if (statusEl) statusEl.textContent = 'Running optimization...';
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Running...';
  }
  try {
    const payload = {
      strategy: id('strategy-select')?.value,
      ticker: id('ticker')?.value?.trim().toUpperCase(),
      startDate: id('start-date')?.value,
      endDate: id('end-date')?.value,
      fastMAList: id('opt-fast-list')?.value || '20,50,100',
      slowMAList: id('opt-slow-list')?.value || '150,200,250',
      topN: parseInt(id('opt-topn')?.value || 10, 10),
      initialCapital: parseFloat(id('capital')?.value || 100000),
      riskPercent: parseFloat(id('risk')?.value || 2.0),
      interval: id('interval')?.value || '1d',
    };
    const res = await fetch(`${API}/api/optimize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Optimization failed.');
    renderOptTable(data.results);
    if (statusEl) statusEl.textContent = `Done. ${data.results.length} combinations tested.`;
  } catch (err) {
    if (statusEl) statusEl.textContent = err.message;
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Run Optimization';
    }
  }
}

function renderOptTable(results) {
  const tbody = id('opt-table-body');
  if (!tbody) return;
  if (!results.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:20px;color:var(--text-muted)">No results.</td></tr>';
    return;
  }
  tbody.innerHTML = results.map((r) => {
    const m = r.metrics;
    const p = r.params;
    return `<tr>
      <td>${p.fastMA}</td>
      <td>${p.slowMA}</td>
      <td style="color:${m.totalReturn >= 0 ? '#10b981' : '#ef4444'}">${m.totalReturn}</td>
      <td style="color:#ef4444">${-m.maxDrawdown}</td>
      <td>${m.sharpeRatio}</td>
      <td>${m.winRate}</td>
    </tr>`;
  }).join('');
}