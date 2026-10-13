import {it,expect} from 'vitest';
import {canPromote,stateLabels} from './evolutionModel';
it('検証だけの通過や少数配札の保留を採用可能と扱わない',()=>{
 expect(canPromote({evidence:{validation:{passed:true}}})).toBe(false);
 expect(canPromote({evidence:{validation:{passed:false},final:{passed:true}}})).toBe(false);
 expect(canPromote({evidence:{validation:{passed:true},final:{passed:true}}})).toBe(true);
 expect(stateLabels.Inconclusive).toContain('証拠不足');
});
