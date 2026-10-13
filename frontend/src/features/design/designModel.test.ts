import {it,expect} from 'vitest';
import {revisedPlan,canStart} from './designModel';
it('同じ版を上書きせず新しい草案を作り、登録hashなしでは実行できない',()=>{
 const original={plan_id:'test',version:2,reason:'事前仮説'};
 const next=revisedPlan(original);expect(next.version).toBe(3);expect(next.parent_version).toBe(2);expect(original.version).toBe(2);
 expect(canStart('Draft',null)).toBe(false);expect(canStart('Completed','hash')).toBe(false);expect(canStart('Registered','hash')).toBe(true);
});
