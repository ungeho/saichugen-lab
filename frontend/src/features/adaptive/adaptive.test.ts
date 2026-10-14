import {describe,it,expect} from 'vitest';
import {adaptiveExperimentId,adaptiveInitial} from './AdaptivePanel';
describe('適応Labの事前設定と直接リンク',()=>{
 it('URLから実験IDだけを読取り、実行指示にしない',()=>{expect(adaptiveExperimentId('?experiment=a%2Fb&run=true')).toBe('a/b');expect(adaptiveExperimentId('?run=true')).toBeNull();});
 it('小規模な開発用設定と独立参照・最終標本を指定する',()=>{expect(adaptiveInitial.partition).toBe('development');expect(adaptiveInitial.budgets).toEqual([16,32]);expect(adaptiveInitial.reference_worlds).toBe(32);expect(adaptiveInitial.final_worlds).toBe(32);expect(adaptiveInitial.max_derived_games).toBeLessThanOrEqual(80000);});
});
