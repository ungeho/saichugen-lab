import {describe,it,expect} from 'vitest';
import {definitionDocument,derivedDraft,type Definition} from './arenaModel';

const definition={id:'codex_test',version:'1.0.0',name:'テスト',definition_hash:'a'.repeat(64),reference:'codex_test@1.0.0',verification:'未検証',children:[],experiment_ids:[],parent:null,created_at:'2026-10-13T00:00:00Z',theory_config:{theories:[]},rules:[]} as unknown as Definition;
describe('宣言JSONの保存と派生',()=>{
 it('画面用の情報を定義JSONに混入させない',()=>{
  const data=definitionDocument(definition);
  expect(data).not.toHaveProperty('reference');expect(data).not.toHaveProperty('verification');
  expect(data).not.toHaveProperty('children');expect(data).not.toHaveProperty('experiment_ids');
  expect(data.definition_hash).toBe(definition.definition_hash);
 });
 it('元版を変更せず親hashを固定した別版を作る',()=>{
  const draft=derivedDraft(definition);
  expect(draft.version).toBe('1.0.1');expect(draft).not.toHaveProperty('definition_hash');
  expect(draft.parent).toEqual({id:'codex_test',version:'1.0.0',definition_hash:'a'.repeat(64)});
  expect(definition.version).toBe('1.0.0');expect(draft.change_reason).toContain('変更理由');
 });
});
