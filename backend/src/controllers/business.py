from fastapi import HTTPException
from src.models.entities import ForecastRun
def ensure_run(s,i):
 r=s.get(ForecastRun,i)
 if not r:raise HTTPException(404,'预测版本不存在')
 return r
