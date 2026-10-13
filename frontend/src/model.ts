export type Card = {rank:number;suit:number};
export const names = ['Random','Greedy','Conservative','ScoreAware','Heuristic'];
export const label = (c:Card) => '♣♦♥♠'[c.suit]+({1:'A',11:'J',12:'Q',13:'K'}[c.rank]??c.rank);
export const medianPlayers = (scores:number[]) => {
  const middle=[...scores].sort((a,b)=>a-b)[1];
  return scores.flatMap((s,p)=>s===middle?[p]:[]);
};
export type Turn = {index:number;cards:Card[];winner:number;round_scores:number[];game_scores:number[]};
export type CandidateEvaluation = {card:Card;score:number|null;explanation:string;components:Record<string,number>|null};
export type DecisionDetails = {candidates:CandidateEvaluation[];reasoning:string[];score_label:string;information_used:string[];estimates:string[];optional_metadata:Record<string,unknown>|null;origin:string};
export type Decision = {card:Card;desire_to_win:number|null;estimated_turn_win:number|null;explanation:string;details?:DecisionDetails|null;details_status?:'available'|'disabled'|'not_provided'|'hidden';context?:{player:number;turn:number;round_scores:number[];game_scores:number[];hand_sizes:number[];public_history_length:number;unseen_count:number;origin:string}};
export type Game = {id?:string;finished:boolean;winners:number[];strategies:string[];strategy_versions?:string[];capture_details?:boolean;analysis_visible?:boolean;decisions:Decision[][];observation:{player:number;hand:Card[];history:Turn[];round_scores:number[];game_scores:number[];turn:number;hand_sizes:number[]}};
export type Algorithm = {name:string;version:string;description_available:boolean;description_origin:string;tagline:string;overview:string;steps:string[];information:string[];strengths:string[];weaknesses:string[];randomness:string;implementation:string;parameters:{name:string;meaning:string;default:string}[];examples:string[];notes:string[]};
export type AlgorithmStatistics = {name:string;note:string;unclassified_experiments:number;groups:{rule_version:string;information_condition:string;strategy_version:string;parameters:Record<string,unknown>|null;opponents:{name:string;version:string}[];participations:number;match_count:number;wins:number;win_rate:number;average_score:number;score_distribution:{score:number;count:number}[];experiment_ids:string[]}[]};
export type Metric = {games:number;wins:number;win_rate:number;ci95:number[]|null;turn_win_rate:number;scores:number[];recent_win_rate:number;mean_decision_ms:number;seat_win_rates:(number|null)[];cumulative_win_rates:number[];independent_deals:number};
export type Experiment = {id:string;summary:{games:number;strategies:Record<string,Metric>;confidence_method:string;win_definition:string}};
export type ComparisonPosition = {schema_version:number;rule_version:string;information_condition:string;snapshot_id:string;observation:Game['observation'];legal_actions:Card[];game_reference?:{id:string;turn:number;player:number}};
export type ComparedStrategy = {name:string;version:string|null;status:'ok'|'error';decision:Decision|null;state_source:string|null;state_note:string;elapsed_ns:number|null;derived_seed:string|null;error?:string};
export type PositionComparison = {position:ComparisonPosition;seed:number;results:ComparedStrategy[];randomness_note:string};
export async function api<T>(url:string, body?:unknown):Promise<T> {
  const response=await fetch(url,body===undefined?undefined:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(!response.ok) {const detail=await response.text();throw new Error(`操作に失敗しました (${response.status}) ${detail}`);}
  return response.json();
}
