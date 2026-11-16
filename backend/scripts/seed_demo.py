import random
from datetime import date,timedelta
from src.config.database import Base,engine,Session
from src.models.entities import User,DailyVolume
from src.constants.enums import BRANCHES
from src.utils.security import hash_password
def seed():
 Base.metadata.create_all(engine);rng=random.Random(3109)
 with Session() as s:
  for role in ('admin','analyst','viewer'):
   email=role+'@demo.local'
   if not s.query(User).filter_by(email=email).first():s.add(User(email=email,role=role,password=hash_password('Demo123!')))
  for b,branch in enumerate(BRANCHES):
   for i in range(70):
    day=(date(2026,9,6)+timedelta(days=i)).isoformat();weekday=date.fromisoformat(day).weekday();volume=max(0,round(24+b*4+i*.12+(10 if weekday<5 else -8)+rng.gauss(0,3)))
    if not s.query(DailyVolume).filter_by(branch=branch,day=day).first():s.add(DailyVolume(branch=branch,day=day,volume=volume,note='栖川网点日结工单到达量'))
  s.commit();print({'users':s.query(User).count(),'volumes':s.query(DailyVolume).count()})
if __name__=='__main__':seed()
