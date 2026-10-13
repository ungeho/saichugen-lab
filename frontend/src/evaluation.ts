export type RewardMetrics={sole_win_rate?:number|null;joint_win_rate?:number|null;average_score?:number|null;average_terminal_reward?:number|null;reward_games?:number;reward_unknown_games?:number;reward_sources?:Record<string,number>;reward_version?:string|null};
export const metricValue=(value:number|null|undefined,digits=2)=>typeof value==='number'&&Number.isFinite(value)?value.toFixed(digits):'不明';
export const metricPercent=(value:number|null|undefined)=>typeof value==='number'&&Number.isFinite(value)?(value*100).toFixed(1)+'%':'不明';
export const signedReward=(value:number|null|undefined)=>typeof value==='number'&&Number.isFinite(value)?(value>0?'+':'')+value:'不明';

