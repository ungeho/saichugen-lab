import {useEffect,useRef,useState,type ReactNode} from 'react';
import {Button} from '../../components/ui/button';
import {categories,groups,matchPages,pages,type ResearchPage} from './registry';
import {groupKey,readRecent} from './navigation';

export function Workspace({page,navigate,children}:{page:ResearchPage|undefined;navigate:(id:string)=>void;children:ReactNode}){
  const [menu,setMenu]=useState(false),[search,setSearch]=useState('');
  const [open,setOpen]=useState(()=>{try{return localStorage.getItem(groupKey)!=='false';}catch{return true;}});
  const [recent,setRecent]=useState<string[]>(readRecent);
  const menuButton=useRef<HTMLButtonElement>(null),heading=useRef<HTMLHeadingElement>(null),previous=useRef(page?.id);
  useEffect(()=>{setRecent(readRecent());if(previous.current!==page?.id){heading.current?.focus();previous.current=page?.id;}},[page]);
  function go(id:string){navigate(id);setMenu(false);setSearch('');}
  function toggleGroup(){setOpen(v=>{try{localStorage.setItem(groupKey,String(!v));}catch{/* 任意のローカル保存 */}return !v;});}
  const filtered=matchPages(search);
  const item=(p:ResearchPage)=><Button key={p.id} aria-label={p.title} variant={page?.id===p.id?'default':'outline'} aria-current={page?.id===p.id?'page':undefined} onClick={()=>go(p.id)}>{p.title}{page?.id===p.id&&<span className="workspace-current">現在</span>}</Button>;
  return <div className="shell workspace-shell">
    <header className="workspace-header"><div className="brand"><span className="mark">中</span><div><small>RESEARCH WORKSPACE</small><h1>Saichugen Lab</h1></div></div><span className="badge">GPCC資料・公開二次資料に基づく実装</span></header>
    <nav className="workspace-categories" aria-label="上位カテゴリ">{Object.entries(categories).map(([id,title])=><Button key={id} variant={page?.category===id?'default':'outline'} aria-current={page?.category===id?'true':undefined} onClick={()=>go(pages.find(p=>p.category===id)!.id)}>{title}</Button>)}</nav>
    <Button ref={menuButton} className="workspace-menu" variant="outline" aria-expanded={menu} aria-controls="workspace-sidebar" onClick={()=>setMenu(v=>!v)}>{menu?'画面メニューを閉じる':'画面メニューを開く'}</Button>
    <div className="workspace-layout"><div id="workspace-sidebar" className={`workspace-sidebar ${menu?'is-open':''}`} onKeyDown={e=>{if(e.key==='Escape'){setMenu(false);menuButton.current?.focus();}}}>
      <label>画面を検索<input type="search" placeholder="信頼性 / Theory…" value={search} onChange={e=>setSearch(e.target.value)}/></label>
      <nav className="workspace-pages" aria-label="すべての画面">{Object.entries(categories).map(([category,title])=>{
        const list=filtered.filter(p=>p.category===category);if(!list.length)return null;
        return <section key={category}><h2>{title}</h2>{category==='research'&&list.some(p=>p.group==='middle')&&<div className="workspace-group"><Button variant="outline" aria-expanded={search?true:open} aria-controls="middle-pages" onClick={toggleGroup}>{groups.middle.title}</Button>{(open||search)&&<div id="middle-pages">{list.filter(p=>p.group==='middle').map(item)}</div>}</div>}{list.filter(p=>!p.group).map(item)}</section>;
      })}{filtered.length===0&&<p>一致する画面がありません。</p>}</nav>
      <details className="workspace-recent"><summary>最近使用した画面</summary>{recent.map(id=>{const p=pages.find(p=>p.id===id)!;return <Button key={id} variant="outline" aria-label={`最近: ${p.title}`} onClick={()=>go(id)}>{p.title}</Button>;})}</details>
    </div><main className="workspace-content"><div className="workspace-location" aria-label="現在地"><span>{page?categories[page.category]:'不明なURL'}{page?.group&&` / ${groups[page.group].title}`}</span><h2 ref={heading} tabIndex={-1}>{page?.title??'404 · 画面が見つかりません'}</h2></div>{children}</main></div>
  </div>;
}
