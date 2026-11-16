import os,time,json,logging
from pathlib import Path
import redis
from src.config.database import Session
from src.models.entities import ForecastRun
from src.services.analysis import forecast
ARTIFACTS=Path(os.environ.get('ARTIFACTS_DIR','/artifacts'))
try:ARTIFACTS.mkdir(parents=True,exist_ok=True)
except OSError:logging.exception('artifacts directory unavailable; results stay in database only')
r=redis.Redis.from_url(os.environ['REDIS_URL'])
with Session() as recovery:
 for pending in recovery.query(ForecastRun).filter(ForecastRun.state.in_(['queued','running'])).all():
  pending.state='queued';r.rpush('demand:runs',pending.id)
 recovery.commit()
while True:
 Path('/tmp/heartbeat').touch()
 try:
  item=r.blpop('demand:runs',timeout=3)
  if not item:continue
  with Session() as s:
   row=s.get(ForecastRun,int(item[1]))
   if not row or row.state!='queued':continue
   snapshot=row.result['snapshot'];meta=row.result.get('snapshot_meta',{});row.state='running';s.commit()
   try:
    row.result={**forecast(snapshot,row.backtest_days,row.alpha,row.beta),'snapshot':snapshot,'snapshot_meta':meta};row.state='done'
   except Exception as e:row.state='failed';row.error=str(e)
   s.commit()
  if row.state=='done':
   # 结果已冻结在数据库；产物文件写失败只记日志，不回滚已完成的预测。
   try:(ARTIFACTS/(str(row.id)+'.json')).write_text(json.dumps(row.result,ensure_ascii=False))
   except OSError:logging.exception('artifact write failed run=%s',row.id)
 except Exception:logging.exception('worker');time.sleep(2)
