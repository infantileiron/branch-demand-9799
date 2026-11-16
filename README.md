# 栖川 · 服务网点需求预估

让8个售后网点用连续日量比较周季节朴素与Holt趋势预测，并把未来7日工单量转成可签核的排班人数参考。

## 真实业务场景

栖川售后每天由8位网点值班员汇总工单到达量，排班组在 `栖川_网点日结_20261114.xlsx` 中复制上周星期分布，再手工加减人数。痛点：漏日常被当零量、趋势调整没有回测、排班人数和依据版本难追溯。上游是售后工单日结；本项目替代连续性核对、预测比较与人数换算；下游是网点负责人核对技能、休息和班次后安排人员。

四个模块：日量导入（逐条表单/API，含修订）、回测设置、预测对比、排班建议。三个核心实体为DailyVolume、ForecastRun、Staffing，分别贯穿数据库、模式、业务服务/控制、路由和前端；另有用户与审计。提交任务时冻结原始记录与参数，之后补录不改变旧预测。

|角色|可访问|典型动作|
|---|---|---|
|admin|全部，独占审计和签核|签核下周排班建议|
|analyst|业务读写、计算、导出|补录日量、固定参数后提交预测、起草排班|
|viewer|业务只读、导出；服务器拒绝写入/计算|下载冻结预测JSON|

## 启动与演示账号

```sh
cp .env.example .env
docker compose config --quiet
docker compose up -d --build
docker compose exec -T backend python -m scripts.seed_demo
```

前端 [localhost:18208](http://localhost:18208)，API [localhost:19208/docs](http://localhost:19208/docs)，数据库映射17708。账号 `admin@demo.local`、`analyst@demo.local`、`viewer@demo.local`，密码均 `Demo123!`。`SEED_DEMO=true`使后端启动时自动seed；自然键为网点+日期，重复执行不新增也不覆盖人工修订。种子包含8网点各70日（2026-09-06至2026-11-14），合计560条，固定随机seed=3109；三账号。

## 一天的操作剧本

1. 08:50 viewer查看川北等8网点昨日工单日结。
2. 09:00 analyst核对CSV上游记录，确认每个网点日期连续。
3. 09:10 在日量导入补录川北2026-11-15、42单，说明“周末日结”；缺日必须补真实值，不能静默填0。
4. 09:20 选择川北，回测14日，固定α=.6、β=.2，命名“11月下周网点需求”。
5. 09:30 提交worker任务；刷新预测对比，检查两个模型的MAE/MAPE与回测曲线。
6. 09:40 对比未来7日，选择与现场情况相符的模型；以每日单人12单生成排班参考。
7. 10:00 analyst写明轮休/技能约束；10:10 admin核对并签核，不能重复签核。
8. 10:20 viewer下载 `branch-demand-<id>.json`，作为下周排班会议的冻结证据。

## 核心算法与边界

输入为一个网点的连续非负整数日量（上限100000）。重复网点+日期返回409，无效日期/负数返回422。预测前要求至少`回测天数+28`个连续日量；日期缺口、重复日期、样本不足置任务failed，指出缺口并允许补录后重新提交。

周季节朴素预测下一日使用最近第7日前的实际值，未来7日重复最后一周。Holt初始水平为首值，趋势为第二值减首值，之后：`l_t=α y_t+(1−α)(l_(t−1)+b_(t−1))`，`b_t=β(l_t−l_(t−1))+(1−β)b_(t−1)`；未来h步为`l_t+h b_t`。α、β在提交前指定，不使用回测真值调参。

末7–21日作滚动一步回测，每个回测日只用此前历史重新拟合。较早验证日的实际值在后续日成为过去数据，这是walk-forward，不用未来信息。MAE=平均绝对误差（包括实际为0的日）；MAPE仅对实际非0的日计算百分比，同时报告使用日数/零实际日数，全部为0则MAPE为null。以回测MAE较低者作参考选择，同分选季节朴素。该回测同时用于选模，不能宣称独立最终泛化精度。

回测预测先截负为0；未来预测同样截断，再用floor(raw+0.5)四舍五入成非负整数，保留raw及clipped标记。最后用全部历史拟合两个未来7日序列。结果保存冻结记录、参数、checksum、回测逐日明细与两组未来预测。排班人数=`ceil(预测单量/单人日容量)`；容量需1–1000，由业务输入。不处理技能、休息、缺勤、轮班组合优化；不自动替代现场排班决定。

## 工程结构与环境

|部分|技术|
|---|---|
|后端/计算|Python3.11、FastAPI、SQLAlchemy；纯Python确定性Holt/季节法|
|前端|原生HTML/CSS/ES modules、SVG真实回测曲线|
|运行|Nginx1.27、PostgreSQL16、Redis7、单Python worker|

`frontend/src`按api、stores、types、components/common、hooks、pages、router、utils、constants分工；backend/src按routes、controllers、services、models、schemas、middlewares、utils、constants、config分工。表格/字段/状态标签在多页共用；表单hooks和HTML转义工具分离。请求ID、安全响应头两个中间件，写操作审计、全局异常恢复提示。JWT默认有效8小时。

恰好五服务：backend等待db/redis健康，worker还等待backend，frontend等待backend。所有服务有healthcheck；worker每轮更新`/tmp/heartbeat`，Redis队列处理真实预测并在`/artifacts`共享卷写JSON。数据库、Redis、结果各有命名卷。Nginx `/api/`转发后端根路由；worker启动恢复queued/running任务。清理：`docker compose down -v --remove-orphans`。

环境变量见.env.example：COMPOSE_PROJECT_NAME、FRONTEND_PORT、BACKEND_PORT、DB_PORT、DB_PASSWORD、JWT_SECRET、SEED_DEMO、NETWORK_SUBNET。显式10.253.109.0/24用于规避当前机默认网络池耗尽，移机可调整。演示凭据/JWT密钥部署时替换。本地开发可先起db/redis，在backend安装requirements，设置DATABASE_URL/REDIS_URL/JWT_SECRET，再`uvicorn src.main:app --reload`；前端沿用Nginx或同源代理。ORM建初表，migrations保留DDL，无在线版本迁移器。

共享枚举：ROLES、STATES、BRANCHES、MODELS，后端src/constants/enums.py和schemas/business.py，前端src/constants/enums.js；存储列见models/entities.py。所有计算和人数换算在后端，前端只展示。

## 范围与证据

小型演示为逐条录入/修订，无CSV批量上传、删除、分页、自动超参搜索或外部排班发布。无置信区间或节假日外生变量；单worker，不宣称多worker exactly-once。时间序列按业务日，不涉及小时时区换算。字体依赖Google Fonts，断网回退serif/sans-serif。

真实测试、截图和已知差异放在 `../../test-artifacts/gb-3109/`，源码不放证据。测试包含算法已知值、零MAPE、缺日拒绝、无未来泄漏、种子幂等、三角色与浏览器完整流程。许可证MIT，见LICENSE。
