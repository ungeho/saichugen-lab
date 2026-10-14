import {describe,it,expect} from 'vitest';
import {initial,filterPositions,matrix,num,type ReliabilityPosition,type Row} from './reliabilityModel';
describe('信頼性表示モデル',()=>{
 it('予算列・反復・評価を別設定にする',()=>{
  expect(initial.budgets).toEqual([16,32,64,128,256]);expect(initial.repeats).toBe(2);expect(initial.evaluation_worlds).toBe(64);expect(initial.models).toEqual(['Random','Heuristic','ScoreAware']);
  expect('evaluation_trials' in initial).toBe(false);
 });
 it('診断集団を新規集団へ混ぜない',()=>{
  const p={population:'diagnostic',stratum:{class:'strict_middle',relation:'balanced',both_small:true}} as ReliabilityPosition;
  expect(filterPositions([p],'fresh','','','')).toEqual([]);expect(filterPositions([p],'diagnostic','strict_middle','balanced','both_small')).toEqual([p]);
 });
 it('行列は評価モデル列をまとめて平均しない',()=>{
  const rows=[{model:'Random',budget:16,evaluations:[{model:'Random',rules:[{rule:'Terminal-Value',value:1}]},{model:'Heuristic',rules:[{rule:'Terminal-Value',value:-1}]}]}] as Row[];
  const m=matrix(rows,16,['Random','Heuristic']);expect(m[0].values.map(v=>v.value)).toEqual([1,-1]);expect(m[1].values[0].value).toBeNull();
 });
 it('対象外を0として表示しない',()=>{expect(num(null)).toBe('対象外・未算出');expect(num(0)).toBe('0.000');});
});
