import {describe,it,expect} from 'vitest';
import {runtimeInitial,runtimeMain} from './RuntimePanel';
describe('直接時間研究の条件',()=>{
 it('開発と検証を分離し全ゲーム時点の収集を指定する',()=>{expect(runtimeInitial.stage).toBe('development_pilot');expect(runtimeInitial.partition).toBe('development');expect(runtimeInitial.turns).toEqual([3,10,11,13]);expect(runtimeInitial.gap_threshold).toBe(.5);expect(runtimeInitial.batch_worlds).toBe(16);expect(runtimeInitial.uncertainty_z).toBe(2);});
 it('モデル・層を合算せず全事前局面の集約だけを主表示する',()=>{const rows=[{stratum:'all',model:'Random'},{stratum:'tie',model:'Random'},{stratum:'all',model:'Heuristic'}];expect(runtimeMain(rows as Parameters<typeof runtimeMain>[0],'Random')).toEqual([rows[0]]);});
});
