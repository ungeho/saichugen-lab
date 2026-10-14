import {describe,it,expect} from 'vitest';
import {filterPositions,type Position} from './middleModel';
describe('局面分類',()=>{it('事後分類による絞込だけを行う',()=>{const p={position_id:'abc',labels:['中間得点','相手差大(>=5)']} as Position;expect(filterPositions([p],'中間')).toEqual([p]);expect(filterPositions([p],'Zigzag')).toEqual([]);});});
