import {describe,it,expect} from 'vitest';
import {studyActive,intervalText,studyStatus,settingLabel,choiceAgreement} from './qualityModel';
describe('探索品質の未完了・不確実性表示',()=>{
 it('完了と中断を区別する',()=>{expect(studyActive('running')).toBe(true);expect(studyActive('cancelled')).toBe(false);expect(studyStatus.interrupted).toContain('中断');});
 it('1配札の未提供区間を0幅として表示しない',()=>{expect(intervalText(null)).toContain('未提供');expect(intervalText([0,0])).toBe('0.000〜0.000');});
 it('総予算と候補あたり試行数を別表記にする',()=>{
  expect(settingLabel({trials:8,continuation:'Random'})).toBe('8試行 · Random');
  expect(settingLabel({trials:8,method:'combined',total_budget:64,continuation:'Random'})).toContain('Hybrid C 組み合わせ · 総予算64');
 });
 it('同一局面だけの方式ペア一致率を数える',()=>{
  const choices=[{selected_card:{rank:2,suit:1}},{selected_card:{rank:2,suit:1}},{selected_card:{rank:2,suit:2}}];
  expect(choiceAgreement(choices)).toEqual({same:1,total:3,rate:1/3});
  expect(choiceAgreement([]).rate).toBeNull();
 });
});
