import {describe,it,expect,vi,afterEach} from 'vitest';
import {pages,screenComponents,validateRegistry,findPage,matchPages,type ResearchPage} from './registry';
import {readRecent,remember,recentKey} from './navigation';
afterEach(()=>vi.unstubAllGlobals());
describe('研究画面レジストリ',()=>{
  it('全18コンポーネントを一度ずつ登録する',()=>{expect(pages).toHaveLength(18);expect(()=>validateRegistry(pages)).not.toThrow();expect(pages.map(p=>p.id).sort()).toEqual(Object.keys(screenComponents).sort());});
  it('ID・URLの重複を拒否する',()=>{expect(()=>validateRegistry([...pages,pages[0]])).toThrow();expect(()=>validateRegistry(pages.map((p,i)=>i===1?{...p,path:pages[0].path}:p))).toThrow();});
  it('未知のカテゴリ・グループ・画面・コンポーネントを拒否する',()=>{
    for(const change of [{category:'unknown'},{group:'unknown'},{group:'middle',category:'reference'},{component:undefined},{id:'unknown'}])expect(()=>validateRegistry([{...pages[0],...change} as ResearchPage,...pages.slice(1)])).toThrow();
    expect(()=>validateRegistry(pages.slice(1))).toThrow();
  });
  it('旧ルートと全固有URLを解決し不正URLを誤実行しない',()=>{expect(findPage('/')?.id).toBe('game');for(const p of pages){expect(findPage(p.path)?.id).toBe(p.id);expect(findPage(p.path+'/')?.id).toBe(p.id);}expect(findPage('/unknown')).toBeUndefined();});
  it('日本語・英語で検索して4つの中間順位Labを保持する',()=>{expect(matchPages('信頼性').map(p=>p.id)).toEqual(['reliability']);expect(matchPages('THEORY').map(p=>p.id)).toEqual(['theory']);expect(pages.filter(p=>p.group==='middle')).toHaveLength(4);});
  it('最近の画面には既知のIDだけを最大6件保存する',()=>{
    const values=new Map([[recentKey,JSON.stringify(['secret','game','game',42])]]);vi.stubGlobal('localStorage',{getItem:(k:string)=>values.get(k),setItem:(k:string,v:string)=>values.set(k,v)});
    expect(readRecent()).toEqual(['game']);for(const p of pages)remember(p.id);expect(readRecent()).toHaveLength(6);expect(readRecent()[0]).toBe('catalog');const before=values.get(recentKey);remember('private');expect(values.get(recentKey)).toBe(before);
  });
  it('壊れた保存値と保存禁止環境でも動く',()=>{vi.stubGlobal('localStorage',{getItem:()=>'{bad',setItem:()=>{throw new Error('blocked');}});expect(readRecent()).toEqual([]);expect(()=>remember('game')).not.toThrow();});
});
