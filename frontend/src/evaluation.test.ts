import {describe,it,expect} from 'vitest';
import {metricValue,metricPercent,signedReward} from './evaluation';

describe('終局指標の表示',()=>{
 it('負報酬・0報酬を累計得点や不明と区別する',()=>{
  expect(signedReward(2)).toBe('+2');
  expect(signedReward(-2)).toBe('-2');
  expect(signedReward(0)).toBe('0');
  expect(metricValue(-.25)).toBe('-0.25');
 });
 it('欠損・非有限値を0にしない',()=>{
  for(const value of [null,undefined,NaN,Infinity]){
   expect(metricValue(value)).toBe('不明');
   expect(metricPercent(value)).toBe('不明');
   expect(signedReward(value)).toBe('不明');
  }
 });
 it('勝利率の表示単位を報酬と分ける',()=>{
  expect(metricPercent(.25)).toBe('25.0%');
  expect(metricValue(.25)).toBe('0.25');
 });
});

