from pydantic import BaseModel
from typing import Optional


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