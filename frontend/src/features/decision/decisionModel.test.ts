import {describe,it,expect} from 'vitest';
import {initial,rules,filterPositions,interval,type DecisionPosition} from './decisionModel';
describe('意思決定比較の表示モデル',()=>{
 const row={stratum:{class:'strict_middle',relation:'balanced',both_small:true,both_large:false},period:'final_round_start',origins:[{source:'Heuristic'}],decision:{self_terminal_disagree:true}} as DecisionPosition;
 it('不一致と層・時間・収集元を区別する',()=>{
  expect(filterPositions([row],'strict_middle','balanced','both_small','final_round_start','Heuristic',true)).toEqual([row]);
  expect(filterPositions([row],'','','both_large','','',false)).toEqual([]);
 });
 it('一致局面を不一致として数えない',()=>{
  expect(filterPositions([{...row,decision:{...row.decision,self_terminal_disagree:false}}],'','','','','',true)).toEqual([]);
  expect(filterPositions([],'','','','','',true)).toEqual([]);
 });
 it('未算出を0の区間と区別する',()=>{
  expect(interval({mean:0,interval:[0,0],method:'同一札'})).toBe('[0.000, 0.000]');
  expect(interval({mean:null,interval:null,method:'未完了'})).toBe('未算出');
 });
 it('4規則と独立評価・固定タイブレーク予算を保持する',()=>{
  expect(rules).toHaveLength(4);expect(initial.evaluation_trials).toBe(32);expect(initial.safety_tolerance).toBe(0);expect(initial.max_validate).toBe(0);
 });
});
