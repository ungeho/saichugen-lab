import {describe,it,expect} from 'vitest';
import {stoppingInitial,stoppingPrimary} from './StoppingPanel';
import type {AdaptiveJob} from '../adaptive/AdaptivePanel';
describe('停止検証の主分析',()=>{
 it('Phase32の停止閾値を固定し検証配札を指定する',()=>{expect(stoppingInitial.partition).toBe('validation');expect(stoppingInitial.start_offset).toBeGreaterThanOrEqual(1000000);expect(stoppingInitial.initial_worlds).toBe(16);expect(stoppingInitial.batch_worlds).toBe(16);expect(stoppingInitial.gap_threshold).toBe(.5);expect(stoppingInitial.uncertainty_z).toBe(2);expect(stoppingInitial.minimum_gap).toBe(.05);});
 it('計算削減局面だけの副次集約を主分析へ混ぜない',()=>{const job={cluster_summary:[{stratum:'all',method:'Fixed'},{stratum:'reduced_only',method:'Gap-Adaptive'}]} as unknown as AdaptiveJob;expect(stoppingPrimary(job)).toHaveLength(1);expect(stoppingPrimary({...job,cluster_summary:null})).toEqual([]);});
});
