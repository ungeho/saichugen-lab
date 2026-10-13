import {describe,it,expect} from 'vitest';
import {curveRows} from './evidenceModel';
describe('Evidence curve',()=>{it('小標本の区間を0へ置き換えない',()=>{expect(curveRows([{n:1,mean:1,sd:null,interval:null,elapsed_seconds:1,deal_id:'a',mean_change:null}])).toEqual([[1,1,null,null]]);});});
