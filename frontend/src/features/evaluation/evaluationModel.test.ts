import {it,expect} from 'vitest';
import {planningLabel,decisions,type Planning} from './evaluationModel';
it('2配札の予備評価と固定標本の保留を精密な判断として表示しない',()=>{
 expect(planningLabel({status:'pilot_required'} as Planning)).toBe('予備評価が必要');
 expect(planningLabel({status:'approximate',estimated_additional:32} as Planning)).toContain('概算');
 expect(decisions.hold).toBe('判定保留');
});
