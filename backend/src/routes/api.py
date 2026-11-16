import os,json
from datetime import date
import redis
from fastapi import APIRouter,Depends,HTTPException,Response
from src.config.database import db
from src.models.entities import User,DailyVolume,ForecastRun,Staffing,Audit,WorkOrderEvent,WorkOrderConflict,VolumeConflict
from src.schemas.business import Branch,Login,DailyInput,ForecastInput,StaffingInput,WorkOrderEventBatch,ConflictResolveInput
from src.middlewares.auth import current,editor,admin
from src.utils.security import verify,token
from src.services.business import audit,dump
from src.services.volumes import save_volume
from src.services.staffing import draft
from src.controllers.business import ensure_run
from src.services import events
router=APIRouter()


def stream_status(s):
    summary=events.stream_summary(s)
    plan=events.analyze(s)
    summary['differences']=plan['differences']
    summary['counts']=plan['counts']
    summary['work_order_conflicts']=plan['work_order_conflicts']
    summary['recent_publications']=plan['recent_publications']
    return summary


@router.post('/auth/login')
def login(data:Login,s=Depends(db)):
 u=s.query(User).filter_by(email=data.email).first()
 if not u or not verify(data.password,u.password):raise HTTPException(401,'账号或密码错误')
 return {'token':token(u),'user':dump(u)}
@router.get('/me')
def me(u=Depends(current)):return dump(u)
@router.get('/volumes')
def volumes(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(DailyVolume).order_by(DailyVolume.day,DailyVolume.branch).all()]
@router.post('/volumes')
def create(data:DailyInput,u=Depends(editor),s=Depends(db)):
 r=save_volume(s,data.model_dump(mode='json'));audit(s,u,'录入日量 '+str(r['id']));return r
@router.put('/volumes/{i}')
def edit(i:int,data:DailyInput,u=Depends(editor),s=Depends(db)):
 r=save_volume(s,data.model_dump(mode='json'),i);audit(s,u,'修订日量 '+str(r['id']));return r
@router.get('/runs')
def runs(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(ForecastRun).order_by(ForecastRun.id.desc()).all()]
@router.post('/runs')
def run(data:ForecastInput,u=Depends(editor),s=Depends(db)):
 # 只冻结已发布生效的日量；未发布事件不在快照内。
 rows=[dump(r) for r in s.query(DailyVolume).filter_by(branch=data.branch).order_by(DailyVolume.day).all()]
 r=ForecastRun(**data.model_dump(),result={'snapshot':rows,'snapshot_meta':{'published_seq':events.stream_summary(s)['published_seq'],'taken_at':events.now_iso()}});s.add(r);s.commit()
 try:redis.Redis.from_url(os.environ['REDIS_URL']).rpush('demand:runs',r.id)
 except redis.RedisError:r.state='failed';r.error='队列暂不可用，请恢复后重试';s.commit();raise HTTPException(503,r.error)
 audit(s,u,'提交预测 '+str(r.id));return dump(r)
@router.get('/runs/{i}')
def detail(i:int,u=Depends(current),s=Depends(db)):return dump(ensure_run(s,i))
@router.get('/runs/{i}/export')
def export(i:int,u=Depends(current),s=Depends(db)):
 r=ensure_run(s,i)
 if r.state!='done':raise HTTPException(409,'仅成功预测可导出')
 return Response(json.dumps(dump(r),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="branch-demand-{i}.json"'})
@router.get('/staffings')
def staffings(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Staffing).order_by(Staffing.id.desc()).all()]
@router.post('/staffings')
def staffing(data:StaffingInput,u=Depends(editor),s=Depends(db)):
 r=draft(s,ensure_run(s,data.run_id),data);audit(s,u,'起草排班 '+str(r.id));return dump(r)
@router.post('/staffings/{i}/approve')
def approve(i:int,u=Depends(admin),s=Depends(db)):
 r=s.get(Staffing,i)
 if not r:raise HTTPException(404,'排班建议不存在')
 if r.status!='draft':raise HTTPException(409,'不可重复签核')
 r.status='approved';s.commit();audit(s,u,'签核排班 '+str(i));return dump(r)
@router.get('/audits')
def audits(u=Depends(admin),s=Depends(db)):return [dump(r) for r in s.query(Audit).order_by(Audit.id.desc()).limit(100)]


# ---- 工单变更流 ----
@router.post('/events')
def receive_events(data:WorkOrderEventBatch,u=Depends(editor),s=Depends(db)):
 results=events.ingest_events(s,data.events,u)
 audit(s,u,'接收工单事件 '+str(len(results))+' 条')
 counts={}
 for r in results:counts[r['status']]=counts.get(r['status'],0)+1
 return {'results':results,'counts':counts,'stream':stream_status(s)}

@router.get('/events')
def list_events(u=Depends(current),s=Depends(db),limit:int=200):
 rows=s.query(WorkOrderEvent).order_by(WorkOrderEvent.id.desc()).limit(min(max(limit,1),500)).all()
 return [dump(r) for r in rows]

@router.get('/stream')
def stream(u=Depends(current),s=Depends(db)):return stream_status(s)

@router.get('/stream/differences')
def differences(u=Depends(current),s=Depends(db)):
 plan=events.analyze(s)
 return {k:plan[k] for k in ('target_seq','published_seq','pending_events','differences','counts','blockers','can_publish','work_order_conflicts','recent_publications')}

@router.post('/stream/publish')
def publish_stream(u=Depends(editor),s=Depends(db)):
 try:stats=events.publish(s,u)
 except events.PublishBlocked as e:
  raise HTTPException(409,{'message':e.payload['message'],'blockers':e.payload['blockers'],'differences':e.payload['differences']})
 audit(s,u,'发布事件日量 seq='+str(stats['target_seq'])+' 发布号='+str(stats['publication_id']))
 return {'publication':stats,'stream':stream_status(s)}

@router.get('/publications')
def publications(u=Depends(current),s=Depends(db)):
 from src.models.entities import DailyPublication
 return [events.dump_publication(p) for p in s.query(DailyPublication).order_by(DailyPublication.id.desc()).limit(50).all()]

@router.get('/conflicts')
def conflicts(u=Depends(current),s=Depends(db)):
 wo=[events.dump_work_order_conflict(c) for c in s.query(WorkOrderConflict).order_by(WorkOrderConflict.id.desc()).all()]
 vols=[dump(c) for c in s.query(VolumeConflict).order_by(VolumeConflict.id.desc()).all()]
 return {'work_orders':wo,'volumes':vols}

@router.post('/conflicts/work-orders/{i}/resolve')
def resolve_work_order(i:int,data:ConflictResolveInput,u=Depends(editor),s=Depends(db)):
 c=s.get(WorkOrderConflict,i)
 if not c:raise HTTPException(404,'工单差异不存在')
 result=events.resolve_work_order_conflict(s,c,data.action,data.note,u)
 audit(s,u,f'核对工单差异 {c.order_no} v{c.version} → {result["status"]}')
 return result

@router.post('/conflicts/volumes/{branch}/{day}/resolve')
def resolve_volume(branch:Branch,day:date,data:ConflictResolveInput,u=Depends(editor),s=Depends(db)):
 if data.action not in ('adopt_event','keep_manual'):raise HTTPException(422,'日量差异只能采用事件结果或保留人工值')
 iso=day.isoformat()
 result=events.resolve_volume_conflict(s,branch,iso,data.action,data.note,u)
 audit(s,u,f'核对日量差异 {branch} {iso} → {result["status"]}')
 return result
