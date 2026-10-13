export type TheorySpec={id:string;version?:string;enabled:boolean;weight:number;params:Record<string,string|number|boolean>};
export type TheoryConfig={theories:TheorySpec[]};
export type TheoryDefinition={id:string;name:string;description:string;rationale:string;information:string[];applicability:string;parameters:Record<string,{default:string|number|boolean;choices?:(string|boolean)[];min?:number;max?:number;meaning:string}>;relationship:string;limitations:string[];evaluation:string;version:string;status:string;scale:string};
export function theoryVariants(config:TheoryConfig,mode:string,budget:number,baseline:string){
 const active=config.theories.filter(s=>s.enabled&&s.weight!==0);
 const build=(theories:TheorySpec[])=>({method:mode,total_budget:mode==='theory'?null:budget,continuation:'Random',theory_config:{theories}});
 const settings:Record<string,unknown>[]=[build(config.theories.map(s=>({...s,enabled:false})))];
 for(const spec of active)settings.push(build(config.theories.map(s=>({...s,enabled:s.id===spec.id}))));
 if(active.length>1)settings.push(build(config.theories));
 if(baseline!=='none')settings.push(mode==='theory'?{method:'baseline',baseline_name:baseline}:{method:baseline,total_budget:budget,continuation:'Random'});
 if(settings.length>8)throw new Error('最大8設定です。有効な仮説か比較戦略を減らしてください。');
 return settings;
}
export const partitionStarts:Record<string,number>={development:0,validation:1000000,final:2000000};
