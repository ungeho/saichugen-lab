import {describe,it,expect} from 'vitest';
import {medianPlayers,label} from './model';
describe('公開表示の判定',()=>{
 it('同点の中位者全員を強調する',()=>{expect(medianPlayers([7,7,2])).toEqual([0,1]);expect(medianPlayers([0,12,0])).toEqual([0,2]);});
 it('カードラベルを表示する',()=>{expect(label({rank:1,suit:3})).toBe('♠A');expect(label({rank:13,suit:0})).toBe('♣K');});
});
