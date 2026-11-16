import math,json,hashlib
from datetime import date,timedelta
def holt(values,horizon,alpha,beta):
 if len(values)<2:raise ValueError('Holt至少需要2天数据')
 level=float(values[0]);trend=float(values[1]-values[0])
 for value in values[1:]:
  previous=level;level=alpha*value+(1-alpha)*(level+trend);trend=beta*(level-previous)+(1-beta)*trend
 return [level+h*trend for h in range(1,horizon+1)]
def seasonal(values,horizon):return [float(values[-7+i%7]) for i in range(horizon)]
def scores(actual,predicted):
 errors=[abs(a-p) for a,p in zip(actual,predicted)];pairs=[(a,p) for a,p in zip(actual,predicted) if a!=0]
 return {'mae':sum(errors)/len(errors),'mape':sum(abs(a-p)/a for a,p in pairs)/len(pairs)*100 if pairs else None,'mape_used':len(pairs),'zero_actual':len(actual)-len(pairs)}
def forecast(rows,backtest_days,alpha,beta):
 rows=sorted(rows,key=lambda r:r['day']);days=[date.fromisoformat(r['day']) for r in rows]
 if len(rows)<backtest_days+28:raise ValueError(f'至少需要{backtest_days+28}个连续日量，保证回测前28天训练窗口')
 if len(set(days))!=len(days):raise ValueError('同网点存在重复日期，请先核对')
 gaps=[(a.isoformat(),b.isoformat()) for a,b in zip(days,days[1:]) if b-a!=timedelta(days=1)]
 if gaps:raise ValueError('日期不连续，缺口：'+str(gaps[:3])+'；不可将缺日当作零量')
 values=[r['volume'] for r in rows];start=len(values)-backtest_days;predictions={'seasonal_naive':[],'holt':[]};clipped={'seasonal_naive':0,'holt':0}
 for i in range(start,len(values)):
  train=values[:i]
  for model,raw in [('seasonal_naive',seasonal(train,1)[0]),('holt',holt(train,1,alpha,beta)[0])]:
   if raw<0:clipped[model]+=1
   predictions[model].append(max(0,raw))
 metrics={m:scores(values[start:],ps) for m,ps in predictions.items()}
 selected=min(metrics,key=lambda m:(metrics[m]['mae'],m!='seasonal_naive'))
 future={m:[] for m in predictions}
 for model,raw in [('seasonal_naive',seasonal(values,7)),('holt',holt(values,7,alpha,beta))]:
  for h,p in enumerate(raw,1):future[model].append({'day':(days[-1]+timedelta(days=h)).isoformat(),'raw':p,'prediction':max(0,int(math.floor(p+.5))),'clipped':p<0})
 return dict(branch=rows[0]['branch'],n=len(rows),train_initial=start,backtest_days=backtest_days,alpha=alpha,beta=beta,metrics=metrics,selected_model=selected,backtest=[{'day':rows[i]['day'],'actual':values[i],**{m:predictions[m][i-start] for m in predictions}} for i in range(start,len(values))],future=future,history=[{'day':r['day'],'volume':r['volume']} for r in rows],backtest_clipped=clipped,checksum=hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),warning='按时间顺序滚动一步回测，每个预测只用此前数据；α/β为提交前指定，不用回测真值调参。回测MAE用于选模，不是独立最终泛化估计。MAPE跳过实际值0并报告数量；全部为0时MAPE未定义。负预测先截为0，未来值四舍五入为非负整数。')
