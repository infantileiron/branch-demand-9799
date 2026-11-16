from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from src.models.entities import DailyVolume
from src.services import events


def save_volume(s,data,id=None):
 r=s.get(DailyVolume,id) if id else DailyVolume()
 if not r:raise HTTPException(404,'日量不存在')
 for k,v in data.items():setattr(r,k,v)
 # 人工写入/修订总是标记为 manual；若该网点日期已被事件覆盖，发布时会因差异被阻止。
 r.source='manual'
 s.add(r)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'该网点日期已有日量，请修订原记录')
 result=events.dump_row(r)
 covered,event_volume=events.has_event_coverage(s,r.branch,r.day)
 if covered and event_volume!=r.volume:
  result['event_notice']={'event_volume':event_volume,'message':'该网点日期已被工单事件覆盖且数值不同，发布前需核对差异'}
 return result
