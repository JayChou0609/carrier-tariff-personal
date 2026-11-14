(function(){
const node=typeof require==='function';
if(!node){load('custom/area-names.js');load('custom/model.js');}
const A=node?require('../custom/area-names.js'):globalThis.TariffAreas;
const M=node?require('../custom/model.js'):globalThis.TariffModel;
function eq(a,b){if(a!==b)throw Error(a+' != '+b);}
eq(A.display('5160','mobile'),'徐州');
eq(A.display('5160,GS，0210','mobile'),'徐州、甘肃、上海');
eq(A.display('5160','unicom'),'适用地区待核验');
eq(A.display('JS00','gb'),'江苏');
eq(A.display('600103','telecom'),'江苏');
eq(A.display('!AH','mobile'),'适用地区待核验');
const raw={name:'测试',fields:{'方案编号':'26JS201985','适用地区':'5160','资费标准':'0元/月'}};
const result=M.normalize(raw,{id:'mobile:jiangsu',carrier:'mobile',region:'jiangsu'},0);
eq(result.details.find(x=>x[0]==='适用地区')[1],'徐州');
eq(raw.fields['适用地区'],'5160');
eq(result.id,'26JS201985');
(node?console.log:print)('Area display: 9 checks passed');
})();
