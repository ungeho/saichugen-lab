export type Card = {rank:number;suit:number};
export const names = ['Random','Greedy','Conservative','ScoreAware','Heuristic'];
export const label = (c:Card) => '♣♦♥♠'[c.suit]+({1:'A',11:'J',12:'Q',13:'K'}[c.rank]??c.rank);
export const medianPlayers = (scores:number[]) => {
  const middle=[...scores].sort((a,b)=>a-b)[1];
  return scores.flatMap((s,p)=>s===middle?[p]:[]);
};
export type Turn = {index:number;cards:Card[];winner:number;round_scores:number[];game_scores:number[]};
export type Decision = {card:Card;desire_to_win:number|null;estimated_turn_win:number|null;explanation:string};
export type Game = {id?:string;finished:boolean;winners:number[];strategies:string[];decisions:Decision[][];observation:{player:number;hand:Card[];history:Turn[];round_scores:number[];game_scores:number[];turn:number;hand_sizes:number[]}};
export type Metric = {games:number;wins:number;win_rate:number;ci95:number[]|null;turn_win_rate:number;scores:number[];recent_win_rate:number;mean_decision_ms:number;seat_win_rates:(number|null)[];cumulative_win_rates:number[];independent_deals:number};
export type Experiment = {id:string;summary:{games:number;strategies:Record<string,Metric>;confidence_method:string;win_definition:string}};
export async function api<T>(url:string, body?:unknown):Promise<T> {
  const response=await fetch(url,body===undefined?undefined:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(!response.ok) {const detail=await response.text();throw new Error(`操作に失敗しました (${response.status}) ${detail}`);}
  return response.json();
}
