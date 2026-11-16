# 栖川 · 服务网点需求预估

让8个售后网点用连续日量比较周季节朴素与Holt趋势预测，并把未来7日工单量转成可签核的排班人数参考。

## 真实业务场景

栖川售后每天由8位网点值班员汇总工单到达量，排班组在 `栖川_网点日结_20261114.xlsx` 中复制上周星期分布，再手工加减人数。痛点：漏日常被当零量、趋势调整没有回测、排班人数和依据版本难追溯。上游是售后工单日结；本项目替代连续性核对、预测比较与人数换算；下游是网点负责人核对技能、休息和班次后安排人员。

五个模块：日量导入（逐条表单/API，含修订）、工单变更流（事件接收、差异核对、日量发布）、回测设置、预测对比、排班建议。三个核心实体为DailyVolume、ForecastRun、Staffing，分别贯穿数据库、模式、业务服务/控制、路由和前端；工单变更流另有WorkOrderEvent、WorkOrder、WorkOrderConflict、VolumeConflict、DailyPublication与单例水位EventStreamState；另有用户与审计。提交任务时冻结原始记录与参数，之后补录不改变旧预测。

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

1. 08:50 viewer查看川北等8网点昨日工单日结与工单变更流水位。
2. 09:00 analyst把上游工单变更逐条送入事件流：工单号、版本、受理日、归属网点、撤销标记；确认每网点日期连续。
3. 09:05 核对“事件与现行日量差异”：转派会冲减原网点，撤销归零，迟到旧版不回退；同版异内容进入隔离区。差异未核对外发布会被阻止。
4. 09:10 在日量导入补录/修订人工日结（如川北2026-11-15、42单）；缺日必须补真实值，不能静默填0。
5. 09:15 发布已接收事件：日量、归属与发布号在单事务内生效。人工日量与事件覆盖冲突时保留人工值并列差异，核对后再发布。
6. 09:20 选择川北，回测14日，固定α=.6、β=.2，命名“11月下周网点需求”。预测只取发布后已生效日量。
7. 09:30 提交worker任务；刷新预测对比，检查两个模型的MAE/MAPE与回测曲线。
8. 09:40 对比未来7日，选择与现场情况相符的模型；以每日单人12单生成排班参考。
9. 10:00 analyst写明轮休/技能约束；10:10 admin核对并签核，不能重复签核。
10. 10:20 viewer下载 `branch-demand-<id>.json`，作为下周排班会议的冻结证据。

## 工单变更流与日量发布

工单变更事件包含工单号、版本、受理日、归属网点和撤销标记。接收后按工单号聚合，**每单只取已采用事件中的最高版本**重建日量：

- 转派：新版本归属新网点，旧网点该受理日计数减一；减到0时原网点显式写0，不删行。
- 撤销：最高版本 `cancelled=true` 时不计数，该网点日期归零。
- 乱序/迟到旧版：仍记录在事件日志，但不参与重建，归属缓存保持最高版本，不回退。
- 重复投递：`delivery_id` 或“同工单+同版本+同内容”判重，只返回 duplicate，水位不变。
- 同版异内容：新内容放入隔离区 `work_order_conflicts`，原归属不动，发布被阻止；人工选择采用新内容或保留原内容后才可发布。若该工单已有更高版本生效，该差异只保留待查，不阻塞。
- 全量重跑：每次发布都按事件日志从头重建并覆盖事件来源日量，重复执行结果一致。

三阶段都与“处理中→生效”一致：`POST /events` 在一个事务内写事件并更新 `work_orders` 归属缓存；`POST /stream/publish` 在事件水位行锁内取快照、重建、写 `daily_volumes` 并记 `daily_publications`，任一步失败整体回退，不留半成品。发布并发接收新事件时，新事件落在下一个发布水位之后，不丢不重。

人工日量（`source=manual`）与事件覆盖同网点日期冲突时，发布返回409并列出差异；`GET /stream/differences` 可查差异。`POST /conflicts/volumes/{branch}/{day}/resolve` 选择 `adopt_event` 或 `keep_manual`：采用事件则下次发布覆盖为事件值；保留人工则后续发布跳过该日期。核对结论绑定当时的两个数值，任一再次变化即失效并要求重核。工单差异用 `GET /conflicts` 查看、`POST /conflicts/work-orders/{id}/resolve` 处理。

预测提交时冻结的是当时 `daily_volumes` 中的已生效日量（未发布事件不在内），并记录 `snapshot_meta.published_seq`；之后补录、转派、撤销或重跑发布都不改旧预测的 `result.snapshot`，历史版本保留原依据。

页面“工单变更流”一页可送事件（含撤销勾选）、查差异、核对工单/日量差异并发布；发布按钮与页面刷新会重新拉取水位，因此可以在发布期间继续送事件。

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

环境变量见.env.example：COMPOSE_PROJECT_NAME、FRONTEND_PORT、BACKEND_PORT、DB_PORT、DB_PASSWORD、JWT_SECRET、SEED_DEMO、NETWORK_SUBNET。显式10.253.109.0/24用于规避当前机默认网络池耗尽，移机可调整。演示凭据/JWT密钥部署时替换。本地开发可先起db/redis，在backend安装requirements，设置DATABASE_URL/REDIS_URL/JWT_SECRET，再`uvicorn src.main:app --reload`；前端沿用Nginx或同源代理。ORM建初表，`src/config/schema.py`会为旧库补齐新增列，migrations保留DDL，无在线版本迁移器。

共享枚举：ROLES、STATES、BRANCHES、MODELS，后端src/constants/enums.py和schemas/business.py，前端src/constants/enums.js；存储列见models/entities.py。所有计算和人数换算在后端，前端只展示。事件流接口：`POST /events`（批量≤500，`delivery_id`可选）、`GET /events`、`GET /stream`、`GET /stream/differences`、`POST /stream/publish`、`GET /publications`、`GET /conflicts`、`POST /conflicts/work-orders/{id}/resolve`、`POST /conflicts/volumes/{branch}/{day}/resolve`。

## 范围与证据

小型演示为逐条录入/修订，无CSV批量上传、删除、分页、自动超参搜索或外部排班发布。无置信区间或节假日外生变量；单worker，不宣称多worker exactly-once。时间序列按业务日，不涉及小时时区换算。工单事件为HTTP批量推送（每批≤500条），无消息中间件或回放订阅；隔离区与日量差异需人工核对，不做自动裁决。字体依赖Google Fonts，断网回退serif/sans-serif。

后端测试：`cd backend && pip install -r requirements-dev.txt && pytest tests -q`；并发用例需 PostgreSQL，SQLite 下自动跳过。真实测试、截图和已知差异放在 `../../test-artifacts/gb-3109/`，源码不放证据。测试包含算法已知值、零MAPE、缺日拒绝、无未来泄漏、种子幂等、三角色与浏览器完整流程；`backend/tests/test_events.py` 另覆盖乱序转派、撤销重放、重复投递、同版异内容隔离、人工/事件冲突阻止、发布失败回退与预测快照冻结。许可证MIT，见LICENSE。
