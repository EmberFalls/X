from pydantic import BaseModel, ConfigDict
from typing import Optional, Literal


class RegisterRequest(BaseModel):
    email: str
    username: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class BacktestRequest(BaseModel):
    strategy: str
    ticker: str
    startDate: str
    endDate: str
    fastMA: float = 50
    slowMA: float = 200
    mrK: float = 2.0
    initialCapital: float = 100000
    riskPercent: float = 2.0
    atrPeriod: float = 14
    stopLoss: float = 2.0
    takeProfit: float = 6.0
    slippage: float = 0.1
    transactionCost: float = 0.05
    interval: str = "1d"


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
    prompt: str
    ticker: str = "RELIANCE.NS"
    interval: str = "1d"


# ---------------------------------------------------------------------------
# StrategyPayload schema — used to validate the LLM mapper's output
# (moved here from main.py so llm_mapper.py can import it without creating
# a circular import with main.py, which itself imports from llm_mapper.py)
# ---------------------------------------------------------------------------
class EntryLogic(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fast_ma: Optional[int] = None
    slow_ma: Optional[int] = None
    rsi_buy: Optional[float] = None
    rsi_sell: Optional[float] = None
    mr_k: Optional[float] = None
    rsi_confirm: bool = False
    macd_confirm: bool = False


class ExitLogic(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stop_loss_pct: float = 2.0
    take_profit_pct: float = 6.0
    trailing_stop_pct: Optional[float] = None


class ExecutionRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    initial_capital: float = 100000
    risk_percent: float = 2.0
    slippage_pct: float = 0.1
    transaction_cost_pct: float = 0.05


class StrategyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_intent: str
    strategy_id: Literal['golden_cross', 'mean_reversion', 'rsi_strategy', 'macd_crossover', 'momentum_breakout']
    ticker: str
    exchange: Literal['NSE', 'BSE', 'AUTO'] = 'AUTO'
    interval: Literal['1m', '5m', '15m', '1h', '1d'] = '1d'
    market_mode: Literal['trend_following', 'mean_reversion', 'momentum', 'reversal'] = 'trend_following'
    risk_profile: Literal['low', 'medium', 'high'] = 'medium'
    entry_logic: EntryLogic
    exit_logic: ExitLogic
    execution_rules: ExecutionRules
    assistant_rationale: str
