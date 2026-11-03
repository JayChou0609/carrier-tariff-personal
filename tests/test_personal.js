/* Run with Node; also supports macOS JavaScriptCore for local verification. */
(function(){
 'use strict';
 const isNode=typeof require==='function';
 if(!isNode)load('custom/model.js');
 const M=isNode?require('../custom/model.js'):globalThis.TariffModel;
 const say=isNode?console.log:print;
 let count=0;
 function check(ok,label){if(!ok)throw Error(label);count++;}
 const source={id:'mobile:jiangsu',carrier:'mobile',region:'jiangsu',name:'江苏移动'};
 check(M.price('0元/月','', 'mobile')===0,'explicit zero month');
 check(M.price('59.90','元/月','unicom')===59.9,'decimal monthly price');
 for(const p of ['','免费','20元/月优惠','20元/月减免','10元/GB','120元/年','29元起','10至30元/月','10/20元/月'])check(M.price(p,'','mobile')===null,'not a monthly base fee: '+p);
 check(M.price('59','','unicom')===null,'bare fee without unit is unknown');
 const a=M.normalize({name:'移动59元套餐',fields:{'资费标准':'59元/月','资费类型':'套餐','适用范围':'限江苏地区'}},source,0);
 check(a.monthly===59 && a.search.includes('江苏'),'mobile normalization');
 const b=M.normalize({id:'b',title:'联通套餐',fee:'9.9',firstLevel:'套餐',detail:{feeUnit:'元/月',commonData:'30',dataUnit:'GB',minute:'100'}},{id:'unicom:jiangsu',carrier:'unicom',region:'jiangsu',name:'江苏联通'},0);
 check(b.details.some(x=>x[0]==='通用流量'&&x[1]==='30 GB'),'preserve traffic unit');
 check(b.details.some(x=>x[0]==='国内通话'&&x[1]==='100 分钟'),'preserve voice unit');
 const unknown=M.normalize({id:'u',title:'年包',fee:'120',detail:{feeUnit:'元/年'}},source,1);
 check(M.filter([a,b,unknown],{min:'0',max:'20'},new Set()).length===1,'budget excludes unknown and annual fees');
 check(M.filter([a,b],{q:'限江苏地区'},new Set())[0]===a,'full text condition');
 check(M.filter([a,b],{q:'限江苏地区',nameOnly:true},new Set()).length===0,'name only');
 check(M.filter([a,b],{favOnly:true},new Set([b.key]))[0]===b,'favorite identity');
 check(M.sort([unknown,a,b],'priceDesc').map(x=>x.key).join() === [a,b,unknown].map(x=>x.key).join(),'unknown price sorted last');
 check(new Set(M.defaults).size===12,'12 requested sources');
 check(M.escape('<img src=x onerror=1>').includes('&lt;img'),'HTML escape');
 check(M.csvCell('=HYPERLINK("evil")').startsWith('"\''),'CSV formula protection');
 if(isNode){
  check(M.safeURL('javascript:alert(1)')==='','reject executable URLs');
  check(M.safeURL('https://www.189.cn/')==='https://www.189.cn/','allow official HTTPS');
 }
 say('Personal data model: '+count+' checks passed');
})();
