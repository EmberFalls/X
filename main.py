from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from pathlib import Path
from typing import Optional, Literal, Dict, Any
import pandas as pd

import backtester
from market_data import MarketDataProvider, YFinanceProvider
from strategy_assistant import suggest_strategy_from_prompt, validate_strategy_payload
from llm_mapper import suggest_strategy_llm, VALID_STRATEGY_IDS
from interpretability import build_interpretability_layer
from experiment_logger import log_technical, log_trading, log_usability, TimedBlock

app = FastAPI(title="SimuTrade Research Backend v2")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
provider: MarketDataProvider = YFinanceProvider()

_latest_assistant_payload: Dict[str, Any] = {}


@app.post('/api/state/latest-assistant')
def set_latest_assistant_payload(payload: Dict[str, Any]):
    """
    Backend-backed handoff store for the assistant payload.
    Replaces sessionStorage entirely — persists across full page reloads
    and works even if the live-chart dashboard is opened in a separate tab.
    """
    global _latest_assistant_payload
    _latest_assistant_payload = payload
    return {"ok": True}


@app.get('/api/state/latest-assistant')
def get_latest_assistant_payload():
    if not _latest_assistant_payload:
        raise HTTPException(status_code=404, detail="No assistant payload stored yet.")
    return _latest_assistant_payload


# NOTE: EntryLogic / ExitLogic / ExecutionRules / StrategyPayload used to be
# defined here. They now live in schemas.py so that llm_mapper.py can import
# StrategyPayload directly (without a circular import back through main.py)
# and validate the LLM's raw output against it. main.py doesn't need to
# import them itself since it only handles the already-validated payload
# dict returned by suggest_strategy_llm().


class BacktestRequest(BaseModel):
    strategy: str
    ticker: str
    startDate: str
    endDate: str
    fastMA: float = 50.0
    slowMA: float = 200.0
    mrK: float = 2.0
    initialCapital: float = 100000.0
    riskPercent: float = 2.0
    atrPeriod: float = 14.0
    stopLoss: float = 2.0
    takeProfit: float = 6.0
    slippage: float = 0.1
    transactionCost: float = 0.05
    interval: str = '1d'


class OptimizeRequest(BaseModel):
    strategy: str
    ticker: str
    startDate: str
    endDate: str
    fastMAList: str = "20,50,100"
    slowMAList: str = "150,200,250"
    topN: int = 10
    initialCapital: float = 100000
    riskPercent: float = 2.0
    interval: str = "1d"


class AssistantRequest(BaseModel):
    prompt: str = Field(min_length=3)
    ticker: str = 'RELIANCE.NS'
    interval: str = '1d'


class UsabilityLogRequest(BaseModel):
    flow_type: Literal['manual', 'heuristic_fallback', 'llm']
    prompt: str
    time_to_submit_sec: float
    form_errors: int = 0
    apply_button_used: bool = True
    backtest_triggered: bool = False
    user_id: Optional[str] = None


@app.get('/api/health')
def health():
    return {'ok': True, 'provider': provider.name, 'version': 'v2'}


@app.post('/api/assistant/suggest')
def assistant_suggest(req: AssistantRequest):
    try:
        payload = suggest_strategy_from_prompt(req.prompt, req.ticker, req.interval)
        validate_strategy_payload(payload)
        return payload
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/api/backtest')
def run_backtest(req: BacktestRequest):
    try:
        raw = provider.get_history(req.ticker, req.startDate, req.endDate, req.interval)
        if raw.empty:
            raise HTTPException(status_code=400, detail=f"No data for '{req.ticker}'.")

        params = req.dict()
        data = backtester.add_indicators(raw.copy(), params).dropna(subset=['Close'])

        if len(data) < 20:
            raise HTTPException(status_code=400, detail='Not enough data after calculating indicators.')

        equity, trades, final_cash, bh_shares, last_price = backtester.run_strategy(req.strategy, data, params)
        metrics = backtester.calculate_metrics(equity, trades, req.initialCapital, bh_shares, last_price)

        return {
            'chartData': equity,
            'trades': trades,
            'metrics': metrics,
            'ticker': req.ticker,
            'strategy': req.strategy,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/api/optimize')
def run_optimization(req: OptimizeRequest):
    try:
        raw = provider.get_history(req.ticker, req.startDate, req.endDate, req.interval)
        if raw.empty:
            raise HTTPException(status_code=400, detail=f"No data for '{req.ticker}'.")

        fast_mas = [int(x.strip()) for x in req.fastMAList.split(',') if x.strip().isdigit()]
        slow_mas = [int(x.strip()) for x in req.slowMAList.split(',') if x.strip().isdigit()]

        results = []
        for f in fast_mas:
            for s in slow_mas:
                if f >= s:
                    continue
                params = {
                    'fastMA': f,
                    'slowMA': s,
                    'mrK': 2.0,
                    'atrPeriod': 14.0,
                    'initialCapital': req.initialCapital,
                    'riskPercent': req.riskPercent,
                    'stopLoss': 2.0,
                    'takeProfit': 6.0,
                    'slippage': 0.1,
                    'transactionCost': 0.05,
                    'ticker': req.ticker,
                    'startDate': req.startDate,
                    'endDate': req.endDate,
                    'interval': req.interval,
                }
                data = backtester.add_indicators(raw.copy(), params).dropna(subset=['Close'])
                if len(data) < 20:
                    continue
                equity, trades, final_cash, bh_shares, last_price = backtester.run_strategy(req.strategy, data, params)
                metrics = backtester.calculate_metrics(equity, trades, req.initialCapital, bh_shares, last_price)
                results.append({"params": {"fastMA": f, "slowMA": s}, "metrics": metrics})

        results.sort(key=lambda x: x['metrics']['totalReturn'], reverse=True)
        return {"results": results[:req.topN]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/api/live-chart/{ticker}')
def get_live_chart(ticker: str, interval: str = '5m'):
    try:
        candles = provider.get_live_snapshot(ticker, interval)
        if not candles:
            raise HTTPException(status_code=400, detail=f"No data for '{ticker}'.")

        current_price = candles[-1]['close']
        prev_close = candles[-2]['close'] if len(candles) > 1 else current_price
        change = round(current_price - prev_close, 2)
        change_pct = round((change / prev_close) * 100, 2) if prev_close else 0

        return {
            'ticker': ticker,
            'candles': candles,
            'current_price': current_price,
            'change': change,
            'change_pct': change_pct,
            'interval': interval,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/api/assistant/suggest_llm')
def assistant_suggest_llm(req: AssistantRequest):
    try:
        with TimedBlock() as timer:
            payload = suggest_strategy_llm(req.prompt, req.ticker, req.interval)

        strategy_id = payload.get("strategy_id", "unknown")
        mapping_source = payload.get("mapping_source", "llm")

        # NOTE: schema_valid here just confirms the returned strategy_id is one
        # of the five known strategies for downstream routing/logging purposes.
        # The actual full-payload schema validation (required fields, enums,
        # nested entry/exit/execution types) already happened inside
        # llm_mapper.suggest_strategy_llm() via the StrategyPayload pydantic
        # model before this payload was ever returned.
        schema_valid = strategy_id in VALID_STRATEGY_IDS

        backtest_completed = False
        metrics: Dict[str, Any] = {}
        bt_error = None
        try:
            raw = provider.get_history(req.ticker, "2024-01-01", "2024-12-31", req.interval)
            if not raw.empty and schema_valid:
                entry = payload.get("entry_logic", {})
                exit_l = payload.get("exit_logic", {})
                exec_r = payload.get("execution_rules", {})
                params = {
                    'fastMA': entry.get('fast_ma') or 20,
                    'slowMA': entry.get('slow_ma') or 50,
                    'mrK': entry.get('mr_k') or 2.0,
                    'atrPeriod': 14,
                    'initialCapital': exec_r.get('initial_capital', 100000),
                    'riskPercent': exec_r.get('risk_percent', 2.0),
                    'stopLoss': exit_l.get('stop_loss_pct', 2.0),
                    'takeProfit': exit_l.get('take_profit_pct', 6.0),
                    'slippage': exec_r.get('slippage_pct', 0.1),
                    'transactionCost': exec_r.get('transaction_cost_pct', 0.05),
                    'ticker': req.ticker,
                    'startDate': '2024-01-01',
                    'endDate': '2024-12-31',
                    'interval': req.interval,
                    'rsiBuy': entry.get('rsi_buy', 30.0),
                    'rsiSell': entry.get('rsi_sell', 70.0),
                }
                data = backtester.add_indicators(raw.copy(), params).dropna(subset=['Close'])
                if len(data) >= 20:
                    equity, trades, final_cash, bh_shares, last_price = backtester.run_strategy(strategy_id, data, params)
                    metrics = backtester.calculate_metrics(equity, trades, params['initialCapital'], bh_shares, last_price)
                    backtest_completed = True
        except Exception as e:
            bt_error = str(e)

        record_id = log_technical(
            prompt=req.prompt,
            mapping_source=mapping_source,
            schema_valid=schema_valid,
            backtest_completed=backtest_completed,
            latency_ms=timer.ms,
            fallback_reason=payload.get("fallback_reason"),
            llm_model=payload.get("llm_model"),
            error=bt_error,
        )

        if backtest_completed:
            log_trading(
                record_id=record_id,
                ticker=req.ticker,
                strategy_id=strategy_id,
                mapping_source=mapping_source,
                metrics=metrics,
                params_snapshot=payload,
            )

        overlay: Dict[str, Any] = {}
        try:
            recent = provider.get_live_snapshot(req.ticker, req.interval)
            if recent:
                df = pd.DataFrame(recent)
                df.columns = [c.capitalize() for c in df.columns]
                overlay = build_interpretability_layer(df, payload)
        except Exception:
            pass

        return {
            **payload,
            "record_id": record_id,
            "latency_ms": round(timer.ms, 2),
            "backtest_completed": backtest_completed,
            "metrics_preview": metrics,
            "interpretability": overlay,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/api/live-chart-v2/{ticker}')
def get_live_chart_v2(ticker: str, interval: str = '5m', strategy_id: str = 'golden_cross'):
    try:
        candles = provider.get_live_snapshot(ticker, interval)
        if not candles:
            raise HTTPException(status_code=400, detail=f"No data for '{ticker}'.")

        current_price = candles[-1]['close']
        prev_close = candles[-2]['close'] if len(candles) > 1 else current_price
        change = round(current_price - prev_close, 2)
        change_pct = round((change / prev_close) * 100, 2) if prev_close else 0

        overlay: Dict[str, Any] = {}
        try:
            df = pd.DataFrame(candles)
            df.columns = [c.capitalize() for c in df.columns]
            stub_payload = {"strategy_id": strategy_id, "entry_logic": {}}
            overlay = build_interpretability_layer(df, stub_payload)
        except Exception:
            pass

        return {
            'ticker': ticker,
            'candles': candles,
            'current_price': current_price,
            'change': change,
            'change_pct': change_pct,
            'interval': interval,
            'interpretability': overlay,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/api/log/usability')
def log_usability_session(req: UsabilityLogRequest):
    try:
        log_usability(
            flow_type=req.flow_type,
            prompt=req.prompt,
            time_to_submit_sec=req.time_to_submit_sec,
            form_errors=req.form_errors,
            apply_button_used=req.apply_button_used,
            backtest_triggered=req.backtest_triggered,
            user_id=req.user_id,
        )
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/')
def root():
    file = BASE_DIR / 'index.html'
    if file.exists():
        return FileResponse(file)
    return {'message': 'SimuTrade v2 backend running.'}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)