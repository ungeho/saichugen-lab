import {describe,it,expect} from 'vitest';
import {filtered,initial,type Position} from './stratificationModel';
describe('層別局面フィルター',()=>{
 const row={stratum:{class:'strict_middle',relation:'upper_close',both_small:true},origins:[{source:'Random'},{source:'Heuristic'}],period:'final_round_start'} as Position;
 it('別名の収集元と時点・上下差を検索する',()=>{
  expect(filtered([row],'strict_middle','upper_close','Heuristic','final_round_start')).toEqual([row]);
  expect(filtered([row],'tie','','','')).toEqual([]);
  expect(filtered([row],'','lower_close','','')).toEqual([]);
 });
 it('小差・大差と空データを区別する',()=>{
  expect(filtered([row],'','','','','both_small')).toEqual([row]);
  expect(filtered([row],'','','','','both_large')).toEqual([]);
  expect(filtered([],'','','','')).toEqual([]);
 });
 it('閾値・収集元・計算予算を明示する',()=>{
  expect(initial.definition).toEqual({version:'strict-middle-v1',small:5,large:10,balance_tolerance:0});
  expect(initial.collectors).toHaveLength(5);expect(initial.reproduce).toBe(false);
 });
});
