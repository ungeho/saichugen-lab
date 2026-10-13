import {describe,it,expect} from 'vitest';
import {studyActive,intervalText,studyStatus} from './qualityModel';
describe('探索品質の未完了・不確実性表示',()=>{
 it('完了と中断を区別する',()=>{expect(studyActive('running')).toBe(true);expect(studyActive('cancelled')).toBe(false);expect(studyStatus.interrupted).toContain('中断');});
 it('1配札の未提供区間を0幅として表示しない',()=>{expect(intervalText(null)).toContain('未提供');expect(intervalText([0,0])).toBe('0.000〜0.000');});
});
