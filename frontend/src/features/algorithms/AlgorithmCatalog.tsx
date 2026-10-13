import {useEffect,useState} from 'react';
import {metricValue,metricPercent} from '../../evaluation';
import {Button} from '../../components/ui/button';
import {api,type Algorithm,type AlgorithmStatistics} from '../../model';

function ExplanationList({items,empty='未登録'}:{items:string[];empty?:string}){
  return items.length?<ul>{items.map((text,i)=><li key={i}>{text}</li>)}</ul>:<p className="muted">{empty}</p>;
}

function Statistics({name}:{name:string}){
  const [data,setData]=useState<AlgorithmStatistics|null>(null);const [error,setError]=useState('');const [refresh,setRefresh]=useState(0);
  useEffect(()=>{let active=true;setData(null);setError('');api<AlgorithmStatistics>(`/api/algorithms/${encodeURIComponent(name)}/statistics`).then(result=>{if(active)setData(result);}).catch(e=>{if(active)setError(String(e));});return()=>{active=false;};},[name,refresh]);
  return <section className="panel catalog-statistics"><div className="section-title"><div><small>RECORDED MATCHES</small><h3>保存された対戦成績</h3></div><Button variant="outline" onClick={()=>setRefresh(v=>v+1)}>成績を更新</Button></div>
    {error?<p role="alert" className="error">成績を取得できませんでした。{error}</p>:!data?<p role="status">成績を読み込み中…</p>:<>
      <p className="muted">{data.note}</p>
      {data.groups.length===0?<div className="empty">この戦略の集計可能な保存結果はありません。「比較実験」で対戦すると、ここに条件別の成績が表示されます。</div>:data.groups.map((group,i)=><article className="stat-group" key={i}>
        <div className="stat-conditions"><b>{name} v{group.strategy_version}</b><span>相手: {group.opponents.map(p=>`${p.name} v${p.version}`).join(' / ')}</span><span>ルール: {group.rule_version}</span><span>情報条件: {group.information_condition==='imperfect'?'不完全情報':group.information_condition}</span><span>設定の記録: {group.parameters===null?'未記録':Object.keys(group.parameters).length===0?'既定値（追加パラメータなし）':JSON.stringify(group.parameters)}</span></div>
        <dl className="stat-numbers"><div><dt>対戦回数</dt><dd>{group.match_count}</dd></div><div><dt>参加回数（席数）</dt><dd>{group.participations}</dd></div><div><dt>勝率</dt><dd>{(group.win_rate*100).toFixed(1)}%</dd></div><div><dt>単独勝利率</dt><dd>{metricPercent(group.sole_win_rate)}</dd></div><div><dt>共同勝利率</dt><dd>{metricPercent(group.joint_win_rate)}</dd></div><div><dt>平均累計得点</dt><dd>{metricValue(group.average_score)}</dd></div><div><dt>平均終局報酬</dt><dd>{metricValue(group.average_terminal_reward)}</dd></div></dl>
        <p className="muted">報酬版: {group.reward_version??'不明'} · 報酬算出可能 {group.reward_games??0} / {group.participations}参加 · 不明 {group.reward_unknown_games??group.participations}参加<br/>新形式 {group.reward_sources?.recorded??0} / 旧結果から補完 {group.reward_sources?.derived_from_winners??0}。不明値は平均に含めません。</p><details><summary>得点分布・記録条件を見る</summary><div className="distribution">{group.score_distribution.map(row=><span key={row.score}>{row.score}点: {row.count}回</span>)}</div><p className="muted">設定: {group.parameters===null?'未記録（記録済みの設定と分けて集計）':JSON.stringify(group.parameters)}<br/>保存実験数: {group.experiment_ids.length}</p></details>
      </article>)}
      {data.unclassified_experiments>0&&<p className="muted">全保存実験のうち{data.unclassified_experiments}件は条件・バージョン等の記録不足のため集計に含めていません。</p>}
    </>}
  </section>;
}

export function AlgorithmCatalog({algorithms,selectedName,onSelect,error,onReload}:{algorithms:Algorithm[];selectedName:string;onSelect:(name:string)=>void;error:string;onReload:()=>void}){
  const selected=algorithms.find(a=>a.name===selectedName)??algorithms[0];
  return <div className="catalog-view"><div className="section-title"><div><small>ALGORITHM FIELD GUIDE</small><h2>カードの選び方を、知る。</h2><p>実装に基づく解説と、保存された実際の成績を見比べます。</p></div><Button variant="outline" onClick={onReload}>図鑑を再読み込み</Button></div>
    {error&&<p className="error" role="alert">図鑑を取得できませんでした。{error}</p>}
    {!selected?<div className="empty">{error?'APIの起動を確認して再読み込みしてください。':'登録アルゴリズムを読み込み中…'}</div>:<div className="catalog-grid">
      <section className="catalog-index" aria-label="登録アルゴリズム">{algorithms.map(algorithm=><button key={algorithm.name} className={`catalog-entry ${selected.name===algorithm.name?'active':''}`} aria-pressed={selected.name===algorithm.name} onClick={()=>onSelect(algorithm.name)}><span>{algorithm.name} <small>v{algorithm.version}</small></span><p>{algorithm.tagline}</p><small>{algorithm.implementation}</small></button>)}</section>
      <div className="catalog-detail"><article className="panel prose"><small>{selected.implementation} · v{selected.version}</small><h2>{selected.name}</h2><p className="catalog-tagline">{selected.tagline}</p><p className="muted">{selected.description_origin}</p>
        {!selected.description_available&&<p>説明は未登録です。対戦と成績の確認は通常どおり利用できます。</p>}
        <h3>基本的な考え方</h3><p>{selected.overview||'未登録'}</p>
        <h3>カードを選ぶまで</h3>{selected.steps.length?<ol>{selected.steps.map((step,i)=><li key={i}>{step}</li>)}</ol>:<p className="muted">判断手順は未登録です。</p>}
        <h3>使用する情報</h3><ExplanationList items={selected.information}/>
        <div className="catalog-pair"><section><h3>得意な状況・狙いが合う場面</h3><ExplanationList items={selected.strengths}/></section><section><h3>苦手な状況・見ていないこと</h3><ExplanationList items={selected.weaknesses}/></section></div><p className="muted">設計上の特徴です。勝率で検証された優位性を意味しません。</p>
        <h3>ランダム要素</h3><p>{selected.randomness}</p>
        <h3>調整可能なパラメータ</h3>{selected.parameters.length?<dl>{selected.parameters.map(p=><div key={p.name}><dt>{p.name}（既定値: {p.default}）</dt><dd>{p.meaning}</dd></div>)}</dl>:<p className="muted">外部から調整するパラメータは登録されていません。</p>}
        {selected.examples.length>0&&<><h3>選び方の例</h3><ExplanationList items={selected.examples}/></>}
        {selected.notes.length>0&&<details><summary>計算の前提・補足</summary><ExplanationList items={selected.notes}/></details>}
      </article><Statistics key={selected.name} name={selected.name}/></div>
    </div>}
  </div>;
}
