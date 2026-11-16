/** @typedef {{id:number,branch:string,day:string,volume:number,note:string,source:string,publication_id:number|null,published_event_seq:number|null}} DailyVolume */
/** @typedef {{id:number,name:string,branch:string,backtest_days:number,alpha:number,beta:number,state:string,result:object}} ForecastRun */
/** @typedef {{id:number,run_id:number,capacity:number,model:string,schedule:object[],status:string}} Staffing */
/** @typedef {{id:number,order_no:string,version:number,accepted_date:string,branch:string,cancelled:boolean,status:string,conflict_id:number|null}} WorkOrderEvent */
/** @typedef {{branch:string,day:string,event_volume:number,current_volume:number|null,source:string,kind:string,conflict_status:string|null,conflict_id:number|null}} StreamDifference */
/** @typedef {{id:number,published_seq:number,actor:string,created:string,stats:object}} DailyPublication */
