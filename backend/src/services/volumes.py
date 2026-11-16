from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from src.models.entities import DailyVolume
def save_volume(s,data,id=None):
 r=s.get(DailyVolume,id) if id else DailyVolume()
 if not r:raise HTTPException(404,'日量不存在')
 for k,v in data.items():setattr(r,k,v)
 s.add(r)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'该网点日期已有日量，请修订原记录')
 return r
