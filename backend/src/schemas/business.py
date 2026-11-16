from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
Branch=Literal['川北','川南','东河','西浦','新城','临港','山前','湖滨']
class Login(BaseModel):email:str;password:str
class DailyInput(BaseModel):
 branch:Branch;day:date;volume:int=Field(ge=0,le=100000);note:str=Field(default='',max_length=1000)
class ForecastInput(BaseModel):
 name:str=Field(min_length=2,max_length=100);branch:Branch;backtest_days:int=Field(default=14,ge=7,le=21);alpha:float=Field(default=.6,ge=.01,le=.99,allow_inf_nan=False);beta:float=Field(default=.2,ge=.01,le=.99,allow_inf_nan=False)
class StaffingInput(BaseModel):
 run_id:int=Field(gt=0);capacity:int=Field(ge=1,le=1000);model:Literal['seasonal_naive','holt'];note:str=Field(min_length=8,max_length=2000)
class WorkOrderEventInput(BaseModel):
 model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
 delivery_id:str|None=Field(default=None,max_length=100)
 order_no:str=Field(min_length=1,max_length=64)
 version:int=Field(ge=1)
 accepted_date:date
 branch:Branch
 cancelled:bool=False
 note:str=Field(default='',max_length=500)
 @field_validator('delivery_id')
 @classmethod
 def blank_delivery(cls,v):
  return v or None
 @field_validator('order_no')
 @classmethod
 def non_blank_order(cls,v):
  if not v.strip():raise ValueError('工单号不能为空')
  return v
class WorkOrderEventBatch(BaseModel):
 events:list[WorkOrderEventInput]=Field(min_length=1,max_length=500)
class ConflictResolveInput(BaseModel):
 action:Literal['adopt_incoming','keep_existing','adopt_event','keep_manual']
 note:str=Field(default='',max_length=1000)
