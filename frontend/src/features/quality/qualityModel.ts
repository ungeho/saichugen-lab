import type {TheoryConfig} from '../theory/theoryModel';
export type StudySetting={trials:number;continuation:string;time_limit_ms?:number|null;method?:string;total_budget?:number|null;min_trials?:number;theory_config?:TheoryConfig|null;baseline_name?:string|null};
export const methodNames:Record<string,string>={uniform:'Baseline 均等',heuristic:'Hybrid A Heuristic優先',adaptive:'Hybrid B 適応型',combined:'Hybrid C 組み合わせ'};
export const settingLabel=(s:StudySetting)=>s.method==='baseline'?`比較戦略 ${s.baseline_name}`:s.method?.startsWith('theory')?`${s.method} · ${s.theory_config?.theories.filter(t=>t.enabled&&t.weight!==0).map(t=>t.id).join('+')||'仮説なし'}${s.total_budget?' · 総予算'+s.total_budget:''}`:s.method&&s.method!=='legacy'?`${methodNames[s.method]??s.method} · 総予算${s.total_budget} · ${s.continuation}`:`${s.trials}試行 · ${s.continuation}`;
export function choiceAgreement(choices:{selected_card:{rank:number;suit:number}}[]){
 let same=0,total=0;
 for(let i=0;i<choices.length;i++)for(let j=i+1;j<choices.length;j++){
  total++;if(choices[i].selected_card.rank===choices[j].selected_card.rank&&choices[i].selected_card.suit===choices[j].selected_card.suit)same++;
 }
 return {same,total,rate:total?same/total:null};
}
export type Uncertainty={status:string;reason:string;independent_deals:number;ci95:number[]|null};
export type StudyConfig={baseline_commit:string;name:string;deal_seeds:number[];policy_seed:number;opponents:string[];settings:StudySetting[];analyze_position:boolean;timeout_seconds:number;seed_partition?:string};
export type StudySummary={setting:string;parameters:StudySetting;games:number;recorded_games:number;excluded_partial_games:number;independent_deals:number;average_terminal_reward:number|null;reward_ci95:number[]|null;uncertainty?:Uncertainty;sole_win_rate:number|null;joint_win_rate:number|null;average_score:number|null;decision_ms:{mean:number|null;median:number|null;p95:number|null;max:number|null};game_seconds_mean:number|null;executed_rollouts:number;started_rollouts:number;accepted_rollouts:number;timeout_decisions:number;heuristic_ms_mean?:number|null;allocation_ms_mean?:number|null;unused_budget?:number;decision_trends?:{dimension:string;group:string;decisions:number;mean_selected_rank:number}[]};
export type QualityStudy={id:string;status:string;config:StudyConfig;baseline_commit:string;completed_games:number;estimate:{games:number;independent_deals:number;rollout_upper_bound:number;note:string;settings_count?:number;estimated_seconds?:number|null;estimated_seconds_range?:number[]|null;estimated_storage_bytes?:number;resource_note?:string;timing_sources?:unknown};elapsed_seconds:number;error:string|null;summary:{settings:StudySummary[];baseline:string;differences:{setting:string;baseline:string;difference:number|null;ci95:number[]|null;independent_deals:number;comparable?:boolean;reasons?:string[];uncertainty?:Uncertainty}[];method:string;warning:string};positions:{snapshot_id:string;changed:boolean;generation:string;observation:unknown;choices:{setting:string;selected_card:{rank:number;suit:number};candidates:unknown;seed:string;search_metadata?:Record<string,unknown>}[]}[]};
export const studyActive=(status:string)=>['running','cancelling'].includes(status);
export const studyStatus:Record<string,string>={running:'実行中',cancelling:'停止要求中',completed:'完了',cancelled:'中断',timed_out:'時間制限で中断',interrupted:'再起動等で中断',failed:'失敗'};
export const intervalText=(ci:number[]|null)=>ci?ci.map(v=>v.toFixed(3)).join('〜'):'独立配札不足・未提供';
