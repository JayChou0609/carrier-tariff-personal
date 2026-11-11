/* Shared, pure data transformations for the personal tariff page. */
(function (root) {
  'use strict';
  const carriers = {mobile: '移动', telecom: '电信', unicom: '联通', gb: '广电'};
  const regions = {jiangsu:'江苏',shanghai:'上海',zhejiang:'浙江',hebei:'河北',henan:'河南',sichuan:'四川',guangdong:'广东'};
  const defaults = ['telecom:jiangsu','mobile:jiangsu','unicom:jiangsu','gb:jiangsu','mobile:shanghai','telecom:shanghai','unicom:shanghai','telecom:zhejiang','unicom:hebei','unicom:henan','unicom:sichuan','unicom:guangdong'];
  const labels = {name:'名称',reportNo:'方案编号',codeType:'类型',feesStandard:'资费标准',feeUnit:'计费单位',minute:'国内通话',commonData:'通用流量',dataUnit:'流量单位',sms:'短信',orientTraffic:'定向流量',iptv:'电视',broadBand:'宽带',extraFees:'超出资费',serviceContent:'服务内容',useScope:'适用范围',validPeriod:'有效期限',saleChnl:'销售渠道',onDate:'上线日期',offDate:'下线日期',unsubscribe:'退订方式',responsibility:'违约责任',inNetReq:'在网要求',otherNotes:'其他说明',firstLevelType:'一级类型',secondLevelType:'二级类型',onlinePeriod:'在网期限',state:'销售状态'};
  function price(text, unit, carrier) {
    const s=String(text == null ? '' : text).trim(), u=String(unit || '');
    // Only compare an explicit monthly base fee. Discounts, annual fees, mixed tiers and
    // unknown units are deliberately left unpriced; an unknown fee is never zero.
    if (/优惠|减免|抵扣|返|起|至|~|～|按|每次|元\/年|元\/天|元\/GB|元\/分钟/.test(s)) return null;
    const m=s.match(/^(\d+(?:\.\d+)?)\s*(?:元\s*(?:\/|每)\s*(?:月|个月)|元\s*月费)$/);
    if (m) return Number(m[1]);
    if (/^\d+(?:\.\d+)?$/.test(s) && /^(?:元\s*\/\s*月|元每月|元\/个月)$/.test(u.trim())) return Number(s);
    return null;
  }
  const saleLabels={onsale:'在售业务',stopped:'停售业务',upcoming:'待开售',unknown:'状态未明确'};
  function beijingDay() {return new Date(Date.now()+8*60*60*1000).toISOString().slice(0,10);}
  function dateDay(value) {
    const text=String(value == null ? '' : value).trim();
    const m=text.match(/^(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})(?:日|\b)/) || text.match(/^(\d{4})(\d{2})(\d{2})$/);
    if(!m)return '';
    const year=Number(m[1]),month=Number(m[2]),day=Number(m[3]),d=new Date(Date.UTC(year,month-1,day));
    if(d.getUTCFullYear()!==year||d.getUTCMonth()!==month-1||d.getUTCDate()!==day)return '';
    return String(year).padStart(4,'0')+'-'+String(month).padStart(2,'0')+'-'+String(day).padStart(2,'0');
  }
  function saleState(raw, asOf) {
    const f=raw.fields||raw.detail||{},today=asOf||beijingDay();
    const result=(value,reason)=>({value,label:saleLabels[value],reason});
    if(raw.manual)return result(Object.prototype.hasOwnProperty.call(saleLabels,raw.saleStatus)?raw.saleStatus:'unknown','本机自定义记录，由用户标注');
    const types=[raw.firstLevel,f.codeType,f['资费类型']].map(x=>String(x||'').trim());
    if(types.some(x=>/^停售(?:套餐|业务|资费)?$/.test(x)))return result('stopped','源站分类标记为停售');
    const explicit=String(f['销售状态']||f['停售状态']||f.state||raw.state||'').trim();
    if(/^(?:已)?停售$|^停止销售$|^(?:已)?下架$/.test(explicit))return result('stopped','源站销售状态：'+explicit);
    const off=offInfo(raw).date,on=launchInfo(raw).date;
    // Dates are Beijing calendar days. An end date stays active through that day.
    if(off&&off<today)return result('stopped','下线日期 '+off+' 已过（按北京时间 '+today+' 判断）');
    if(on&&on>today)return result('upcoming','尚未到上线日期 '+on+'（按北京时间 '+today+' 判断）');
    if(/^(?:在售|销售中|正常销售|已上架)$/.test(explicit))return result('onsale','源站销售状态：'+explicit);
    if(off&&(!on||on<=today))return result('onsale','下线日期 '+off+' 尚未过去（按北京时间 '+today+' 判断）');
    if(on&&on<=today&&/^(?:长期|长期有效|永久|无期限)$/.test(String(f['下线日期']||f.offDate||'').trim()))return result('onsale','已上线，源站标注长期有效');
    return result('unknown','源站未提供可判断的销售状态或下线日期');
  }
  function officialDateInfo(raw, keys, label) {
    if(raw.manual)return {date:'',source:'未提供官方日期'};
    const fields=raw.fields||raw.detail||{};
    const groups=[[label,keys]];
    for(const [source,keys] of groups)for(const field of keys)for(const data of [fields,raw]){
      const value=data[field];
      if(value===null||value===undefined||value==='')continue;
      let date=dateDay(value);
      // Explicit timestamp offsets are converted to Beijing; date-only business
      // fields retain the official calendar date exactly as displayed.
      if(typeof value==='string'&&/T.*(?:Z|[+-]\d{2}:?\d{2})$/i.test(value)){
        const time=Date.parse(value);date=Number.isFinite(time)?new Date(time+8*3600000).toISOString().slice(0,10):'';
      }
      if(date)return {date,source};
    }
    return {date:'',source:'未提供可解析的'+label};
  }
  function launchInfo(raw) {return officialDateInfo(raw,['上线日期','onDate','onlineDay','startDate'],'官方上线日期');}
  function offInfo(raw) {return officialDateInfo(raw,['下线日期','offDate','offineDay','offlineDay','endDate'],'官方下线日期');}
  function confirmationInfo(raw) {
    const f=raw.fields||raw.detail||{},value=f.firstConfirmTimeStr||raw.firstConfirmTimeStr||'';
    const info=officialDateInfo(raw,['firstConfirmTimeStr'],'官方确认时间 firstConfirmTimeStr');
    return {...info,time:info.date?String(value):''};
  }
  function lifecycleKey(raw) {
    const f=raw.fields||raw.detail||{};
    return JSON.stringify([String(raw.id||''),String(raw.fields?raw.name||'':raw.title||raw.name||''),String(raw.fields?f['归属']||'':raw.firstLevel||''),String(raw.fields?f['资费类型']||'':raw.secondLevel||'')]);
  }
  function applyLifecycle(item, registry) {
    const events=registry&&registry.sources&&registry.sources[item.source]&&registry.sources[item.source].items[item.lifecycleKey];
    const latest=Array.isArray(events)?events[events.length-1]:null;
    item.reonlineDate=latest?dateDay(latest.date):'';
    item.reonlineBasis=latest?String(latest.basis||''):'';
    item.reonlineDates=Array.isArray(events)?events.map(x=>dateDay(x.date)).filter(Boolean):[];
    if(latest&&item.reonlineDate)item.details.push(['重新上线日期 / 恢复确认日期',item.reonlineDate],['重新上线判断依据',item.reonlineBasis],['此前下线日期 / 停售确认日期',String(latest.previousStopDate||'')],['恢复在售确认时间',String(latest.confirmedAt||'')]);
    return item;
  }
  function lifecycleMatch(item,state,today) {
    const period=state.lifecyclePeriod||'',day=today||beijingDay();
    if(!period)return true;
    if(item.manual)return false;
    if(period==='todayOff')return !!item.offDate&&item.offDate===day;
    const yesterday=new Date(Date.parse(day+'T00:00:00Z')-86400000).toISOString().slice(0,10);
    if(period==='todayReonline')return item.saleStatus==='onsale'&&(item.reonlineDates||[item.reonlineDate]).includes(day);
    // Yesterday is an event-date query; a later withdrawal must not hide it.
    if(period==='yesterdayReonline')return (item.reonlineDates||[item.reonlineDate]).includes(yesterday);
    if(period==='todayConfirmed'||period==='yesterdayConfirmed')return item.carrier==='mobile'&&!!item.confirmDate&&item.confirmDate===(period==='todayConfirmed'?day:yesterday);
    return false;
  }
  function addedMatch(item,state,today) {
    const period=state.addedPeriod||'';
    if(!period)return true;
    if(item.manual||!item.launchDate)return false;
    const day=today||beijingDay(),date=item.launchDate;
    if(period==='date')return !!state.addedDate&&date===state.addedDate;
    if(period==='today')return date===day;
    const shift=n=>new Date(Date.parse(day+'T00:00:00Z')+n*86400000).toISOString().slice(0,10);
    if(period==='yesterday')return date===shift(-1);
    if(period==='week')return date>=shift(-6)&&date<=day;
    return false;
  }
  function normalize(raw, source, index) {
    const mobile=!!raw.fields, fields=raw.fields || raw.detail || {};
    const title=String(raw.name || raw.title || fields.name || '未命名资费');
    const fee=String(mobile ? (fields['资费标准'] || '') : (raw.fee == null ? fields.feesStandard || '' : raw.fee));
    const unit=mobile ? '' : String(fields.feeUnit || '');
    const category=String(mobile ? fields['资费类型'] || '其他' : raw.firstLevel || fields.codeType || '其他');
    const id=String(raw.id || fields['方案编号'] || fields.reportNo || (title+'|'+index));
    const details=Object.entries(fields).filter(([,v])=>v!==null && v!==undefined && String(v)!=='').map(([k,v])=>[labels[k] || k, String(v)+(k==='commonData' && fields.dataUnit ? ' '+fields.dataUnit : k==='minute' && /^\d+(?:\.\d+)?$/.test(String(v)) ? ' 分钟' : '')]);
    const sale=saleState(raw);
    const launched=launchInfo(raw),ended=offInfo(raw),confirmed=confirmationInfo(raw);
    const offDate=ended.date,offSource=ended.source;
    const launchDate=launched.date,launchSource=launched.source;
    details.unshift(['资费上线日期',launchDate||'未提供'],['上线日期来源',launchSource],['资费下线日期',offDate||'未提供'],['下线日期来源',offSource]);
    if(confirmed.time)details.unshift(['官方确认时间（firstConfirmTimeStr）',confirmed.time]);
    details.unshift(['销售状态',sale.label],['状态判断依据',sale.reason]);
    return {confirmDate:confirmed.date,confirmTime:confirmed.time,offDate,offSource,reonlineDate:'',reonlineBasis:'',lifecycleKey:lifecycleKey(raw),launchDate,launchSource,saleStatus:sale.value,saleLabel:sale.label,saleReason:sale.reason,key:source.id+':'+id,id,title,fee,unit,category,details,carrier:source.carrier,region:source.region,source:source.id,label:source.name,timestamp:source.timestamp || '',official:source.official || '',monthly:price(fee,unit,source.carrier),manual:!!raw.manual,search:(title+' '+category+' '+details.map(x=>x.join(' ')).join(' ')).toLowerCase()};
  }
  function filter(items, state, favorites) {
    const q=String(state.q || '').trim().toLowerCase();
    const lo=state.min==='' || state.min==null ? null : Number(state.min);
    const hi=state.max==='' || state.max==null ? null : Number(state.max);
    return items.filter(x=>(!q || (state.nameOnly ? x.title.toLowerCase() : x.search).includes(q)) && (!state.carrier || x.carrier===state.carrier) && (!state.region || x.region===state.region) && (!state.category || x.category===state.category) && (!state.saleStatus || x.saleStatus===state.saleStatus) && addedMatch(x,state) && lifecycleMatch(x,state) && (!state.favOnly || favorites.has(x.key)) && ((lo===null && hi===null) || (x.monthly!==null && (lo===null || x.monthly>=lo) && (hi===null || x.monthly<=hi))));
  }
  function sort(items, order) {
    return items.slice().sort((a,b)=>{
      if(order==='addedDesc'&&a.launchDate!==b.launchDate)return (b.launchDate||'').localeCompare(a.launchDate||'');
      if (order==='priceAsc' || order==='priceDesc') {
        if(a.monthly===null && b.monthly!==null)return 1;
        if(b.monthly===null && a.monthly!==null)return -1;
        if(a.monthly!==null && b.monthly!==null && a.monthly!==b.monthly)return (a.monthly-b.monthly)*(order==='priceAsc'?1:-1);
      }
      return a.title.localeCompare(b.title,'zh-CN') || a.label.localeCompare(b.label,'zh-CN') || a.key.localeCompare(b.key);
    });
  }
  function escape(s) {return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  function csvCell(s) {const v=String(s==null?'':s);return '"'+(/^[\s]*[=+@-]/.test(v)?"'":'')+v.replace(/"/g,'""')+'"';}
  function safeURL(s) {try {const u=new URL(s);return u.protocol==='https:'?u.href:'';}catch(e){return '';}}
  root.TariffModel={carriers,regions,defaults,labels,launchInfo,offInfo,confirmationInfo,lifecycleKey,applyLifecycle,lifecycleMatch,addedMatch,saleLabels,dateDay,beijingDay,saleState,price,normalize,filter,sort,escape,csvCell,safeURL};
  if(typeof module!=='undefined')module.exports=root.TariffModel;
})(typeof globalThis!=='undefined'?globalThis:this);
