import {describe,it,expect} from 'vitest';
import {noiseInitial,divergenceInitial,mainD} from './NoisePanel';
describe('時間と判断の分離',()=>{
 it('Rは固定反復・warmup、Dは別Planで判断分岐を評価する',()=>{expect(noiseInitial.series).toBe('R');expect(noiseInitial.measurement_repeats).toBe(3);expect(noiseInitial.warmups).toBe(1);expect(divergenceInitial.series).toBe('D');expect(divergenceInitial.warmups).toBe(0);expect(divergenceInitial.start_offset).not.toBe(noiseInitial.start_offset);expect(divergenceInitial.budgets).toEqual([128]);});
 it('時間反復・分岐層だけをDの主表示に混ぜない',()=>{const rows=[{series:'D',stratum:'all'},{series:'R',stratum:'all'},{series:'D',stratum:'tie'}];expect(mainD(rows as unknown as Parameters<typeof mainD>[0])).toEqual([rows[0]]);});
});
