import {useEffect,useState} from 'react';
import {api} from '../../model';
import {Button} from '../../components/ui/button';
import {categories,pages,type ResearchPage} from './registry';
import {readRecent} from './navigation';

export function Overview({navigate}:{navigate:(id:string)=>void}){
  const recent=readRecent().map(id=>pages.find(p=>p.id===id)!);
  return <section aria-label="研究ダッシュボード"><p>対戦で挙動を観察し、戦略を研究し、実験と証拠を積み重ねるための入口です。画面の移動だけでは実験は開始されません。</p>
    <section className="panel"><h3>最近使用した画面</h3><div className="workspace-shortcuts">{recent.length?recent.map(p=><Button key={p.id} variant="outline" aria-label={`開く: ${p.title}`} onClick={()=>navigate(p.id)}>{p.title}</Button>):<p>利用した画面がここに表示されます。</p>}</div></section>
    <div className="workspace-directory">{Object.entries(categories).map(([id,title])=><section className="panel" key={id}><h3>{title}</h3><ul>{pages.filter(p=>p.category===id).map(p=><li key={p.id}><a href={p.path} onClick={e=>{if(!e.ctrlKey&&!e.metaKey&&!e.shiftKey&&!e.altKey){e.preventDefault();navigate(p.id);}}}>{p.title}</a></li>)}</ul></section>)}</div>
  </section>;
}
type SavedRow={id?:unknown;status?:unknown;created_at?:unknown;created?:unknown};
type HistorySource={page:ResearchPage;rows:SavedRow[];error?:string};
export function RecentExperiments({navigate}:{navigate:(id:string)=>void}){
  const [sources,setSources]=useState<HistorySource[]>([]),[busy,setBusy]=useState(true),[revision,setRevision]=useState(0);
  useEffect(()=>{let live=true;setBusy(true);Promise.all(pages.filter(p=>p.historyApi).map(async page=>{
    try{const rows=await api<unknown>(page.historyApi!);if(!Array.isArray(rows))throw new Error('履歴の形式を確認できません');return {page,rows:rows.filter((r):r is SavedRow=>typeof r==='object'&&r!==null)};}
    catch(e){return {page,rows:[],error:String(e)};}
  })).then(rows=>{if(live){setSources(rows);setBusy(false);}});return()=>{live=false;};},[revision]);
  const date=(r:SavedRow)=>{const value=r.created_at??r.created;return typeof value==='string'&&Number.isFinite(Date.parse(value))?value:null;};
  const rows=sources.flatMap(source=>source.rows.map(row=>({source,row}))).sort((a,b)=>(date(b.row)?Date.parse(date(b.row)!):0)-(date(a.row)?Date.parse(date(a.row)!):0)).slice(0,20);
  return <section aria-label="最近の実験"><p>既存の保存履歴を読み取って表示します。実験は各Labで履歴を選択して確認できます。作成日時がない履歴は末尾に表示し、新旧を推測しません。</p><Button disabled={busy} variant="outline" onClick={()=>setRevision(v=>v+1)}>履歴を再読込</Button>{busy&&<p role="status">保存履歴を読込中…</p>}
    {sources.filter(s=>s.error).map(s=><p key={s.page.id} role="alert">{s.page.title}: {s.error}</p>)}
    {!busy&&rows.length===0&&<p className="empty">表示できる保存履歴がありません。</p>}
    {rows.length>0&&<div className="table-scroll"><table><thead><tr><th>研究画面</th><th>実験・計画ID</th><th>状態</th><th>作成日時</th></tr></thead><tbody>{rows.map(({source,row},i)=><tr key={`${source.page.id}-${String(row.id)}-${i}`}><td><Button variant="outline" onClick={()=>navigate(source.page.id)}>{source.page.title}へ</Button></td><td>{typeof row.id==='string'?row.id:'未提供'}</td><td>{typeof row.status==='string'?row.status:'未提供'}</td><td>{date(row)??'未提供'}</td></tr>)}</tbody></table></div>}
    <details><summary>履歴の対象と制限</summary><p>最大20件を表示。一般の比較実験には一覧取得APIがないため含みません。Theory Labの定義一覧も実験として集計しません。取得失敗はデータなしと区別します。計画・証拠系列と実行済み結果は同じ成績として集計しません。</p><ul>{sources.map(s=><li key={s.page.id}>{s.page.title}: {s.error?'取得失敗':`${s.rows.length}件`}</li>)}</ul></details>
  </section>;
}
