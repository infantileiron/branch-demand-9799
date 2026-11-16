import math
from fastapi import HTTPException
from src.models.entities import Staffing
def draft(s,run,data):
 if run.state!='done':raise HTTPException(409,'预测完成后才能生成排班建议')
 schedule=[{**p,'staff':math.ceil(p['prediction']/data.capacity)} for p in run.result['future'][data.model]]
 row=Staffing(**data.model_dump(),schedule=schedule);s.add(row);s.commit();return row
