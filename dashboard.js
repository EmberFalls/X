const API = "http://127.0.0.1:8000";

const state = {
  currentTicker: 'RELIANCE.NS',
  currentInterval: '5m',
  lastAssistantPayload: null,
  chart: null,
  candleSeries: null,
  volumeChart: null,
  volumeSeries: null,
  overlays: {},
  refreshTimer: null,
  countdown: 60,
  isPaused: false,
};

const REFRESH_PERIOD = { '1m': 30, '5m': 60, '15m': 120, '1h': 300, '1d': 600 };

document.addEventListener('DOMContentLoaded', () => {
  initCharts();
  bindLiveControls();
  bindAssistantLink();
  bindTheme();
  loadFromBackend();
  loadTicker(state.currentTicker, state.currentInterval);
  startRefreshTimer();
});

function getTheme() {
  const isLight = document.documentElement.getAttribute('data-theme') === 'light';
  return {
    layout: { background: { type: 'solid', color: isLight ? '#f9f9f8' : '#101418' }, textColor: isLight ? '#52525b' : '#a1a1aa' },
    grid: {
      vertLines: { color: isLight ? 'rgba(0,0,0,0.04)' : 'rgba(255,255,255,0.04)' },
      horzLines: { color: isLight ? 'rgba(0,0,0,0.04)' : 'rgba(255,255,255,0.04)' },
    },
  };
}

function initCharts() {
  const chartEl = document.getElementById('live-chart');
  const volEl = document.getElementById('volume-chart');
  if (!chartEl || typeof LightweightCharts === 'undefined') return;
  state.chart = LightweightCharts.createChart(chartEl, {
    width: chartEl.clientWidth,
    height: 420,
    ...getTheme(),
    timeScale: { timeVisible: true, secondsVisible: false },
    rightPriceScale: { borderVisible: false },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  });
  state.candleSeries = state.chart.addCandlestickSeries({
    upColor: '#10b981', downColor: '#ef4444', borderVisible: false, wickUpColor: '#10b981', wickDownColor: '#ef4444',
  });
  if (volEl) {
    state.volumeChart = LightweightCharts.createChart(volEl, {
      width: volEl.clientWidth,
      height: 80,
      ...getTheme(),
      timeScale: { visible: false },
      rightPriceScale: { visible: false },
      leftPriceScale: { visible: false },
      handleScroll: false,
      handleScale: false,
    });
    state.volumeSeries = state.volumeChart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: '' });
    state.volumeChart.priceScale('').applyOptions({ scaleMargins: { top: 0.1, bottom: 0 } });
    state.chart.timeScale().subscribeVisibleLogicalRangeChange((r) => {
      if (r) state.volumeChart.timeScale().setVisibleLogicalRange(r);
    });
  }
  window.addEventListener('resize', () => {
    state.chart?.resize(chartEl.clientWidth, 420);
    if (volEl) state.volumeChart?.resize(volEl.clientWidth, 80);
  });
}

function bindTheme() {
  window.addEventListener('themeChanged', () => {
    const t = getTheme();
    state.chart?.applyOptions(t);
    state.volumeChart?.applyOptions(t);
  });
}

function bindLiveControls() {
  document.querySelectorAll('[data-ticker]').forEach((btn) => btn.addEventListener('click', () => {
    state.currentTicker = btn.dataset.ticker;
    loadTicker(state.currentTicker, state.currentInterval);
  }));
  document.querySelectorAll('.tf-btn').forEach((btn) => btn.addEventListener('click', () => {
    document.querySelectorAll('.tf-btn').forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
    state.currentInterval = btn.dataset.tf;
    state.countdown = REFRESH_PERIOD[state.currentInterval] || 60;
    loadTicker(state.currentTicker, state.currentInterval);
  }));
  const intervalSel = document.getElementById('live-interval');
  if (intervalSel) intervalSel.addEventListener('change', () => {
    state.currentInterval = intervalSel.value;
    loadTicker(state.currentTicker, state.currentInterval);
  });
  const pauseBtn = document.getElementById('btn-pause-resume');
  if (pauseBtn) pauseBtn.addEventListener('click', () => {
    state.isPaused = !state.isPaused;
    pauseBtn.textContent = state.isPaused ? 'Resume' : 'Pause';
    const dot = document.getElementById('live-dot');
    if (dot) dot.classList.toggle('paused', state.isPaused);
  });
}

function startRefreshTimer() {
  if (state.refreshTimer) clearInterval(state.refreshTimer);
  state.countdown = REFRESH_PERIOD[state.currentInterval] || 60;
  state.refreshTimer = setInterval(() => {
    if (state.isPaused) return;
    state.countdown--;
    const el = document.getElementById('refresh-countdown');
    if (el) el.textContent = `Refreshing in ${state.countdown}s`;
    if (state.countdown <= 0) {
      state.countdown = REFRESH_PERIOD[state.currentInterval] || 60;
      loadTicker(state.currentTicker, state.currentInterval);
    }
  }, 1000);
}

/* Backend-backed handoff — replaces sessionStorage entirely.
   Works across full page reloads and separately opened tabs since the
   payload lives in the FastAPI server's memory, not the browser tab. */
async function loadFromBackend() {
  try {
    const res = await fetch(`${API}/api/state/latest-assistant`);
    if (!res.ok) return; // 404 = nothing stored yet, not an error
    const payload = await res.json();
    state.lastAssistantPayload = payload;
    renderAssistantContext();
  } catch (err) {
    console.warn('No assistant payload available yet:', err.message);
  }
}

function bindAssistantLink() {
  const applyBtn = document.getElementById('apply-assistant-live');
  if (!applyBtn) return;
  applyBtn.addEventListener('click', async () => {
    await loadFromBackend();
    const p = state.lastAssistantPayload;
    if (!p) return;
    if (p.ticker) state.currentTicker = p.ticker;
    if (p.interval) state.currentInterval = p.interval;
    loadTicker(state.currentTicker, state.currentInterval);
  });
}

function renderAssistantContext() {
  const box = document.getElementById('assistant-live-context');
  const s = state.lastAssistantPayload;
  if (!box || !s) return;
  box.innerHTML = `<div style="font-size:13px;line-height:1.8">
    <strong>${formatStrategyLabel(s.strategy_id)}</strong><br>
    <span style="color:var(--text-muted,#a1a1aa)">${s.assistant_rationale}</span><br>
    <span style="font-size:11px;color:var(--text-muted,#a1a1aa)">Risk ${s.risk_profile} &nbsp;&nbsp; Mode ${s.market_mode}</span>
  </div>`;
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

async function loadTicker(ticker, interval) {
  const statusEl = document.getElementById('live-status');
  try {
    if (statusEl) statusEl.textContent = `Loading ${ticker}...`;
    const res = await fetch(`${API}/api/live-chart/${encodeURIComponent(ticker)}?interval=${encodeURIComponent(interval)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Live chart load failed.');
    renderLiveData(data);
    if (statusEl) statusEl.textContent = `${ticker} • ${interval}`;
  } catch (err) {
    if (statusEl) statusEl.textContent = `Error: ${err.message}`;
  }
}

function renderLiveData(data) {
  const candles = data.candles;
  state.candleSeries?.setData(candles);
  state.volumeSeries?.setData(candles.map((c) => ({
    time: c.time,
    value: c.volume,
    color: c.close >= c.open ? 'rgba(16,185,129,0.5)' : 'rgba(239,68,68,0.5)',
  })));
  state.chart?.timeScale().fitContent();
  updateQuote(data);
  applyAssistantOverlay(candles);
}

function updateQuote(data) {
  const priceEl = document.getElementById('current-price');
  const changeEl = document.getElementById('price-change');
  if (priceEl) priceEl.textContent = Number(data.current_price || 0).toLocaleString('en-IN');
  if (changeEl) {
    const pos = (data.change ?? 0) >= 0;
    changeEl.textContent = `${pos ? '+' : ''}${data.change} (${data.change_pct}%)`;
    changeEl.style.color = pos ? '#10b981' : '#ef4444';
  }
}

function applyAssistantOverlay(candles) {
  const s = state.lastAssistantPayload;
  clearOverlays();
  if (!s || !candles.length || !state.chart) return;
  const fast = s.entry_logic?.fast_ma;
  const slow = s.entry_logic?.slow_ma;
  if (fast) addMALine(candles, fast, '#22d3ee', 'ema-fast');
  if (slow) addMALine(candles, slow, '#f59e0b', 'ema-slow');
  if (fast && slow) {
    const markers = buildCrossoverMarkers(candles, fast, slow);
    state.candleSeries?.setMarkers(markers);
    updateSignalSummary(markers, candles);
  }
}

function addMALine(candles, period, color, idName) {
  if (!state.chart) return;
  const k = 2 / (period + 1);
  let ema = candles[0].close;
  const data = candles.map((c, i) => {
    ema = i === 0 ? c.close : c.close * k + ema * (1 - k);
    return { time: c.time, value: parseFloat(ema.toFixed(2)) };
  });
  const series = state.chart.addLineSeries({ color, lineWidth: 1, lastValueVisible: false, priceLineVisible: false });
  series.setData(data);
  state.overlays[idName] = series;
}

function clearOverlays() {
  for (const [, s] of Object.entries(state.overlays)) {
    try { state.chart?.removeSeries(s); } catch {}
  }
  state.overlays = {};
  state.candleSeries?.setMarkers([]);
}

function buildCrossoverMarkers(candles, fastP, slowP) {
  const ema = (arr, p) => {
    const k = 2 / (p + 1);
    let e = arr[0].close;
    return arr.map((c, i) => {
      e = i === 0 ? c.close : c.close * k + e * (1 - k);
      return e;
    });
  };
  const fast = ema(candles, fastP);
  const slow = ema(candles, slowP);
  const markers = [];
  for (let i = 1; i < candles.length; i++) {
    if (fast[i - 1] <= slow[i - 1] && fast[i] > slow[i]) {
      markers.push({ time: candles[i].time, position: 'belowBar', color: '#22d3ee', shape: 'arrowUp', text: 'BUY' });
    } else if (fast[i - 1] >= slow[i - 1] && fast[i] < slow[i]) {
      markers.push({ time: candles[i].time, position: 'aboveBar', color: '#f43f5e', shape: 'arrowDown', text: 'SELL' });
    }
  }
  return markers;
}

function updateSignalSummary(markers, candles) {
  const last = markers[markers.length - 1];
  const sigEl = document.getElementById('live-last-signal');
  const trendEl = document.getElementById('live-trend');
  if (!last) {
    if (sigEl) sigEl.textContent = '--';
    if (trendEl) trendEl.textContent = '--';
    return;
  }
  if (sigEl) {
    sigEl.textContent = last.text;
    sigEl.style.color = last.text === 'BUY' ? '#10b981' : '#ef4444';
  }
  if (trendEl) {
    trendEl.textContent = last.text === 'BUY' ? 'BULLISH' : 'BEARISH';
    trendEl.style.color = last.text === 'BUY' ? '#10b981' : '#ef4444';
  }
  addToSignalFeed(last, candles);
}

function addToSignalFeed(marker, candles) {
  const feed = document.getElementById('signal-feed');
  if (!feed) return;
  const candle = candles.find((c) => c.time === marker.time);
  const time = new Date(marker.time * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const placeholder = feed.querySelector('p');
  if (placeholder) placeholder.remove();
  const div = document.createElement('div');
  div.style.cssText = `padding:12px;background:var(--bg-input,#1e2025);border-left:3px solid ${marker.color};border-radius:4px;font-size:13px;margin-bottom:6px;`;
  div.innerHTML = `<strong>${marker.text}</strong> <span style="color:#a1a1aa">${time} @ ${candle?.close ?? '--'}</span>`;
  feed.insertBefore(div, feed.firstChild);
  while (feed.children.length > 20) feed.removeChild(feed.lastChild);
}