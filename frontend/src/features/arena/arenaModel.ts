import type {Decision,Game} from '../../model';
import type {StudySummary} from '../quality/qualityModel';
export type Definition={change_summary?:string;change_reason?:string;id:string;name:string;version:string;reference:string;creator:string;description:string;hypothesis:string;rationale:string;expected_strengths:string[];expected_weaknesses:string[];difference_from_existing:string;theory_config:unknown;rules:unknown[];selection:string;total_budget:number|null;continuation:string;parent:null|{id:string;version:string;definition_hash:string};created_at:string;definition_hash:string;verification:string;children:string[];experiment_ids:string[]};
export type ArenaCatalog={builtins:string[];definitions:Definition[]};
export type ArenaRequest={participants:string[];opponents:string[];deals:number;seed_partition:string;start_offset:number;policy_seed:number;include_expensive:boolean;timeout_seconds:number};
export type ArenaResult={id:string;status:string;completed_games:number;elapsed_seconds:number;error:string|null;config:{deal_seeds:number[];seed_partition:string;policy_seed:number;baseline_commit:string;opponent_entries:{reference:string}[]};summary:{settings:(StudySummary&{reference:string;loss_rate:number|null;opponents:string[];seats:{seat:number;games:number;average_terminal_reward:number}[]})[];differences:{setting:string;difference:number|null;ci95:number[]|null;independent_deals:number;comparable:boolean;reasons:string[];uncertainty?:{reason:string}}[];method:string;warning:string};positions:{generation:string;observation:Game['observation'];choices:{setting:string;selected_card:Game['observation']['hand'][number];decision:Decision}[]}[]};
export function definitionDocument(definition:Definition){
 const {reference,verification,children,experiment_ids,...data}=definition;
 return data;
}
export function derivedDraft(definition:Definition){
 const {definition_hash,...data}=definitionDocument(definition);
 const parts=data.version.split('.').map(Number);
 return {...data,version:`${parts[0]}.${parts[1]}.${parts[2]+1}`,parent:{id:data.id,version:data.version,definition_hash},created_at:new Date().toISOString(),change_summary:'変更内容を記入',change_reason:'変更理由を記入'};
}
