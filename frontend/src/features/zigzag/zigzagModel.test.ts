import {describe,it,expect} from 'vitest';
import {cardLabel} from './zigzagModel';
describe('Zigzag表示',()=>{it('数字とスートを変えず表示する',()=>{expect(cardLabel({rank:13,suit:3})).toBe('♠K');expect(cardLabel({rank:1,suit:0})).toBe('♣A');});});
