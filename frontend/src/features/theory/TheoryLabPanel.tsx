import {useEffect,useState} from 'react';
import {api,label,type Decision,type Game} from '../../model';
import {Button} from '../../components/ui/button';
import {DecisionExplanation} from '../game/DecisionExplanation';
import {QualityStudyPanel} from '../quality/QualityStudyPanel';
import type {StudyConfig} from '../quality/qualityModel';
import {theoryVariants,partitionStarts,type TheoryDefinition,type TheorySpec} from './theoryModel';

type Evaluation={observation:Game['observation'];decision:Decision;generation:string};
const choiceLabels:Record<string,string>={preserve:'温存',consume:'早期消費',round:'ラウンド重視',cumulative:'累計重視',both:'両方',true:'利用する',false:'利用しない'};
const opponents=['Random','Greedy','Conservative','ScoreAware','Heuristic'];
export function TheoryLabPanel(){
 const [catalog,setCatalog]=useState<TheoryDefinition[]>([]),[specs,setSpecs]=useState<TheorySpec[]>([]);
 const [template,setTemplate]=useState<StudyConfig|null>(null),[plan,setPlan]=useState<StudyConfig>();
 const [mode,setMode]=useState('theory'),[budget,setBudget]=useState(64),[baseline,setBaseline]=useState('Heuristic');
 const [deals,setDeals]=useState(2),[partition,setPartition]=useState('development'),[start,setStart]=useState(100);
 const [opponentsChosen,setOpponents]=useState(['Random','Heuristic']);
 const [turn,setTurn]=useState(0),[evaluation,setEvaluation]=useState<Evaluation|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
 useEffect(()=>{Promise.all([api<TheoryDefinition[]>('/api/theories'),api<{id:string;config:StudyConfig}[]>('/api/quality-studies/presets')]).then(([definitions,presets])=>{
  setCatalog(definitions);setSpecs(definitions.map(d=>({id:d.id,version:d.version,enabled:d.id==='reserve_strong',weight:1,params:Object.fromEntries(Object.entries(d.parameters).map(([k,v])=>[k,v.default]))})));
  const initial=presets.find(p=>p.id==='rollout-phase20-stage1')?.config;setTemplate(initial??null);if(initial)setPlan(initial);
 }).catch(e=>setError(String(e)));},[]);
 function update(id:string,change:Partial<TheorySpec>){setSpecs(old=>old.map(s=>s.id===id?{...s,...change}:s));setEvaluation(null);}
 function prepare(){try{
  if(!template)throw new Error('実験テンプレートを取得できていません');
  if(!Number.isInteger(deals)||deals<1||deals>20)throw new Error('独立配札数は1〜20です');
  const settings=theoryVariants({theories:specs},mode,budget,baseline);
  setPlan({...template,name:'Theory Lab / '+partition,seed_partition:partition,deal_seeds:Array.from({length:deals},(_,i)=>start+i),opponents:opponentsChosen,
   settings:settings.map(s=>({trials:8,continuation:'Random',...s})) as StudyConfig['settings']});setError('');
 }catch(e){setError(String(e));}}
 async function evaluate(){setBusy(true);setError('');try{setEvaluation(await api('/api/theories/evaluate',{config:{theories:specs},seed:start,turn}));}catch(e){setError(String(e));}finally{setBusy(false);}}
 return <section aria-label="戦術仮説研究室"><div className="section-title"><div><small>THEORY LAB / PHASE 20</small><h2>戦術の考え方を、仮説として試す。</h2><p>すべて未検証です。確立された定石や強さの保証ではありません。代理評価と終局報酬を区別します。</p></div></div>
 {error&&<p role="alert" className="error">{error}</p>}
 <div className="catalog-pair">{catalog.map(d=>{const s=specs.find(s=>s.id===d.id);if(!s)return null;return <section key={d.id} className="panel"><h3>{d.name}</h3><small>{d.id} · v{d.version} · {d.status}</small><p>{d.description}</p>
 <label><input type="checkbox" aria-label={d.name+'を有効'} checked={s.enabled} onChange={e=>update(d.id,{enabled:e.target.checked})}/>この仮説を使う</label>
 <label>{d.name}の重み<input type="number" min={-2} max={2} step={0.25} value={s.weight} onChange={e=>update(d.id,{weight:Number(e.target.value)})}/></label>
 {Object.entries(d.parameters).map(([key,p])=><label key={key}>{d.name}：{p.meaning}{p.choices?<select aria-label={d.id+'.'+key} value={String(s.params[key])} onChange={e=>update(d.id,{params:{...s.params,[key]:typeof p.default==='boolean'?e.target.value==='true':e.target.value}})}>{p.choices.map(v=><option key={String(v)} value={String(v)}>{choiceLabels[String(v)]??String(v)}</option>)}</select>:<input aria-label={d.id+'.'+key} type="number" min={p.min} max={p.max} value={Number(s.params[key])} onChange={e=>update(d.id,{params:{...s.params,[key]:Number(e.target.value)}})}/>}</label>)}
 <details><summary>前提・評価式・限界</summary><p>{d.rationale}</p><p>評価：{d.evaluation}<br/>尺度：{d.scale}<br/>適用：{d.applicability}<br/>利用情報：{d.information.join('、')}</p><p>既存機能：{d.relationship}</p><ul>{d.limitations.map(t=><li key={t}>{t}</li>)}</ul></details></section>;})}</div>
 <section className="panel"><h3>同じ人工局面で単独寄与と組み合わせを確認</h3><label>人工局面のターン<input type="number" min={0} max={14} value={turn} onChange={e=>setTurn(Number(e.target.value))}/></label><Button disabled={busy||!catalog.length} onClick={evaluate}>この設定の評価を見る</Button><p>下の開始seedで人工局面を作成します。評価だけで通常の対戦は変化しません。</p>
 {evaluation&&<><p>{evaluation.generation} · 判断時点 {evaluation.observation.turn+1} · 選択 {label(evaluation.decision.card)}</p><p>ラウンド得点 {evaluation.observation.round_scores.join(' / ')} · 累計 {evaluation.observation.game_scores.join(' / ')} · 本人の手札 {evaluation.observation.hand.map(label).join(' ')}</p><DecisionExplanation decision={evaluation.decision}/></>}</section>
 <section className="panel"><h3>対照条件と単独・組み合わせの実験計画</h3><p>無効化した対照、仮説ごとの単独設定、複数有効なら組み合わせ、比較戦略を生成します。最大8設定。仮説が多い場合は分けて実験してください。</p>
 <label>評価方式<select value={mode} onChange={e=>{setMode(e.target.value);setBaseline(e.target.value==='theory'?'Heuristic':'uniform');}}><option value="theory">代理評価で直接選択</option><option value="theory_search">Theory優先の総予算探索</option><option value="theory_search_adaptive">Theory＋適応型の総予算探索</option></select></label>
 {mode!=='theory'&&<label>総Rollout予算<input type="number" min={1} max={1024} value={budget} onChange={e=>setBudget(Number(e.target.value))}/></label>}
 <label>比較対象戦略<select value={baseline} onChange={e=>setBaseline(e.target.value)}><option value="none">追加しない</option>{(mode==='theory'?opponents:['uniform','heuristic','adaptive','combined']).map(n=><option key={n}>{n}</option>)}</select></label>
 {opponentsChosen.map((n,i)=><label key={i}>対戦相手 {i+1}<select value={n} onChange={e=>setOpponents(old=>old.map((x,j)=>i===j?e.target.value:x))}>{opponents.map(n=><option key={n}>{n}</option>)}</select></label>)}
 <label>seedの用途<select value={partition} onChange={e=>{setPartition(e.target.value);setStart(partitionStarts[e.target.value]+100);}}><option value="development">開発用</option><option value="validation">検証用</option><option value="final">最終評価用</option></select></label>
 <label>開始seed<input type="number" min={partitionStarts[partition]} max={partitionStarts[partition]+999999} value={start} onChange={e=>setStart(Number(e.target.value))}/></label>
 <label>Theory実験の独立配札数<input type="number" min={1} max={20} value={deals} onChange={e=>setDeals(Number(e.target.value))}/></label>
 <Button disabled={!template} onClick={prepare}>この仮説から実験計画を作る</Button><p>計画の作成だけでは実行しません。下で時間・保存量と設定JSONを確認してから開始します。用途別seed範囲の混入はサーバーでも拒否します。</p></section>
 {plan&&<QualityStudyPanel initialPlan={plan}/>}
 </section>;
}
