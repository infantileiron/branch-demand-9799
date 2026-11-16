from sqlalchemy import Column,Integer,String,Float,JSON,Text,ForeignKey,UniqueConstraint
from src.config.database import Base
class User(Base):
 __tablename__='users'
 id=Column(Integer,primary_key=True);email=Column(String(100),unique=True);password=Column(String(200));role=Column(String(20))
class DailyVolume(Base):
 __tablename__='daily_volumes';__table_args__=(UniqueConstraint('branch','day',name='uq_branch_day'),)
 id=Column(Integer,primary_key=True);branch=Column(String(30),nullable=False);day=Column(String(10),nullable=False);volume=Column(Integer,nullable=False);note=Column(Text,default='')
class ForecastRun(Base):
 __tablename__='forecast_runs'
 id=Column(Integer,primary_key=True);name=Column(String(100));branch=Column(String(30));backtest_days=Column(Integer);alpha=Column(Float);beta=Column(Float);state=Column(String(20),default='queued');result=Column(JSON);error=Column(Text,default='')
class Staffing(Base):
 __tablename__='staffings'
 id=Column(Integer,primary_key=True);run_id=Column(Integer,ForeignKey('forecast_runs.id'));capacity=Column(Integer);model=Column(String(30));schedule=Column(JSON);note=Column(Text);status=Column(String(20),default='draft')
class Audit(Base):
 __tablename__='audits'
 id=Column(Integer,primary_key=True);actor=Column(String(100));action=Column(String(200));created=Column(String(40))
