import {describe,it,expect} from 'vitest';
import {horizonInitial,mainHorizonRows} from './HorizonPanel';
describe('予算上限研究',()=>{
 it('16〜256の固定規則と未使用検証配札を初期設定にする',()=>{expect(horizonInitial.budgets).toEqual([16,32,64,128,256]);expect(horizonInitial.initial_worlds).toBe(16);expect(horizonInitial.batch_worlds).toBe(16);expect(horizonInitial.gap_threshold).toBe(.5);expect(horizonInitial.uncertainty_z).toBe(2);expect(horizonInitial.minimum_gap).toBe(.05);expect(horizonInitial.partition).toBe('validation');expect([1900000,1900001]).not.toContain(horizonInitial.start_offset);});
 it('停止した層だけを主表示にせず予算・モデルを保持する',()=>{const rows=[{stratum:'all',model:'Random',budget:128},{stratum:'tie',model:'Heuristic',budget:32}];expect(mainHorizonRows(rows as Parameters<typeof mainHorizonRows>[0])).toEqual([rows[0]]);});
});
