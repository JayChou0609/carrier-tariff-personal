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
  function normalize(raw, source, index) {
    const mobile=!!raw.fields, fields=raw.fields || raw.detail || {};
    const title=String(raw.name || raw.title || fields.name || '未命名资费');
    const fee=String(mobile ? (fields['资费标准'] || '') : (raw.fee == null ? fields.feesStandard || '' : raw.fee));
    const unit=mobile ? '' : String(fields.feeUnit || '');
    const category=String(mobile ? fields['资费类型'] || '其他' : raw.firstLevel || fields.codeType || '其他');
    const id=String(raw.id || fields['方案编号'] || fields.reportNo || (title+'|'+index));
    const details=Object.entries(fields).filter(([,v])=>v!==null && v!==undefined && String(v)!=='').map(([k,v])=>[labels[k] || k, String(v)+(k==='commonData' && fields.dataUnit ? ' '+fields.dataUnit : k==='minute' && /^\d+(?:\.\d+)?$/.test(String(v)) ? ' 分钟' : '')]);
    return {key:source.id+':'+id,id,title,fee,unit,category,details,carrier:source.carrier,region:source.region,source:source.id,label:source.name,timestamp:source.timestamp || '',official:source.official || '',monthly:price(fee,unit,source.carrier),manual:!!raw.manual,search:(title+' '+category+' '+details.map(x=>x.join(' ')).join(' ')).toLowerCase()};
  }
  function filter(items, state, favorites) {
    const q=String(state.q || '').trim().toLowerCase();
    const lo=state.min==='' || state.min==null ? null : Number(state.min);
    const hi=state.max==='' || state.max==null ? null : Number(state.max);
    return items.filter(x=>(!q || (state.nameOnly ? x.title.toLowerCase() : x.search).includes(q)) && (!state.carrier || x.carrier===state.carrier) && (!state.category || x.category===state.category) && (!state.favOnly || favorites.has(x.key)) && ((lo===null && hi===null) || (x.monthly!==null && (lo===null || x.monthly>=lo) && (hi===null || x.monthly<=hi))));
  }
  function sort(items, order) {
    return items.slice().sort((a,b)=>{
      if (order==='priceAsc' || order==='priceDesc') {
        if(a.monthly===null && b.monthly!==null)return 1;
        if(b.monthly===null && a.monthly!==null)return -1;
        if(a.monthly!==null && b.monthly!==null && a.monthly!==b.monthly)return (a.monthly-b.monthly)*(order==='priceAsc'?1:-1);
      }
      return a.label.localeCompare(b.label,'zh-CN') || a.title.localeCompare(b.title,'zh-CN') || a.key.localeCompare(b.key);
    });
  }
  function escape(s) {return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  function csvCell(s) {const v=String(s==null?'':s);return '"'+(/^[\s]*[=+@-]/.test(v)?"'":'')+v.replace(/"/g,'""')+'"';}
  function safeURL(s) {try {const u=new URL(s);return u.protocol==='https:'?u.href:'';}catch(e){return '';}}
  root.TariffModel={carriers,regions,defaults,labels,price,normalize,filter,sort,escape,csvCell,safeURL};
  if(typeof module!=='undefined')module.exports=root.TariffModel;
})(typeof globalThis!=='undefined'?globalThis:this);
