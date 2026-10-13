import {useEffect,useState} from 'react';
import {api,label} from '../../model';
import {Button} from '../../components/ui/button';
import {Chart} from '../../Chart';
import {metricValue,metricPercent} from '../../evaluation';
import {DecisionExplanation} from '../game/DecisionExplanation';
import {SavedStudyComparison} from '../quality/SavedStudyComparison';
import {intervalText,studyActive,studyStatus} from '../quality/qualityModel';
import {derivedDraft,definitionDocument,type ArenaCatalog,type Definition,type ArenaRequest,type ArenaResult} from './arenaModel';

export function StrategyArena(){
 const [catalog,setCatalog]=useState<ArenaCatalog>({builtins:[],definitions:[]}),[selected,setSelected]=useState('');
 const [participants,setParticipants]=useState<string[]>([]),[opponents,setOpponents]=useState(['Random','Heuristic']);
 const [deals,setDeals]=useState(2),[partition,setPartition]=useState('development'),[offset,setOffset]=useState(100),[policySeed,setPolicySeed]=useState(42),[expensive,setExpensive]=useState(false);
 const [plan,setPlan]=useState<{games:number;independent_deals:number;rollout_upper_bound:number;estimated_seconds_range:number[];estimated_storage_bytes:number;resource_note:string}|null>(null);
 const [study,setStudy]=useState<ArenaResult|null>(null),[history,setHistory]=useState<{id:string;name:string;completed_games:number;status:string}[]>([]);
 const [editor,setEditor]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const active=!!study&&studyActive(study.status);
 const refresh=()=>Promise.all([api<ArenaCatalog>('/api/arena/strategies'),api<typeof history>('/api/arena/studies')]).then(([c,h])=>{setCatalog(c);setHistory(h);setSelected(old=>old||c.definitions[0]?.reference||'');setParticipants(old=>old.length?old:c.definitions.filter(d=>d.version==='1.0.0').map(d=>d.reference));});
 useEffect(()=>{refresh().catch(e=>setError(String(e)));},[]);
 useEffect(()=>setPlan(null),[participants,opponents,deals,partition,offset,policySeed,expensive]);
 useEffect(()=>{if(!study||!studyActive(study.status))return;let live=true;const timer=setTimeout(()=>api<ArenaResult>('/api/arena/studies/'+study.id).then(s=>{if(live){setStudy(s);if(!studyActive(s.status))refresh().catch(e=>setError(String(e)));}}).catch(e=>{if(live)setError(String(e));}),500);return()=>{live=false;clearTimeout(timer);};},[study]);
 async function work(action:()=>Promise<void>){setBusy(true);setError('');try{await action();}catch(e){setError(String(e));}finally{setBusy(false);}}
 const request=():ArenaRequest=>({participants,opponents,deals,seed_partition:partition,start_offset:offset,policy_seed:policySeed,include_expensive:expensive,timeout_seconds:180});
 const selectedDefinition=catalog.definitions.find(d=>d.reference===selected);
 const references=[...catalog.definitions.map(d=>d.reference),...catalog.builtins];
 function toggle(ref:string,checked:boolean){setParticipants(old=>checked?[...old,ref]:old.filter(v=>v!==ref));}
 function download(value:unknown,filename:string){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=filename;a.click();URL.revokeObjectURL(url);}
 async function open(id:string){setStudy(await api('/api/arena/studies/'+id));}
 return <section className="quality-study strategy-arena" aria-label="Codex Strategy Arena"><div className="section-title"><div><small>CODEX STRATEGY ARENA / PHASE 21</small><h2>考案した戦略を、条件を固定して試す。</h2><p>すべて未検証の仮説です。各候補＋固定相手2役の3人対戦を記録し、絶対的な強さランキングにはしません。</p></div></div>
 {error&&<p role="alert" className="error">{error}</p>}
 <section className="panel"><label>宣言戦略の詳細<select value={selected} onChange={e=>setSelected(e.target.value)}>{catalog.definitions.map(d=><option key={d.reference} value={d.reference}>{d.name} · v{d.version}</option>)}</select></label>
 {selectedDefinition&&<><h3>{selectedDefinition.name}</h3><p>{selectedDefinition.description}</p><p>中心仮説：{selectedDefinition.hypothesis}<br/>考案理由：{selectedDefinition.rationale}</p><p>作成：{selectedDefinition.creator} / {selectedDefinition.created_at}<br/>状態：{selectedDefinition.verification}<br/>親：{selectedDefinition.parent?selectedDefinition.parent.id+'@'+selectedDefinition.parent.version:'初期候補'}<br/>定義hash：<code>{selectedDefinition.definition_hash}</code></p>
 <div className="catalog-pair"><section><h4>期待する強み（未確認）</h4><ul>{selectedDefinition.expected_strengths.map(s=><li key={s}>{s}</li>)}</ul></section><section><h4>予想する弱点（未確認）</h4><ul>{selectedDefinition.expected_weaknesses.map(s=><li key={s}>{s}</li>)}</ul></section></div><p>{selectedDefinition.difference_from_existing}</p>
 <details><summary>Theory・局面規則・探索設定</summary><pre>{JSON.stringify({theory_config:selectedDefinition.theory_config,rules:selectedDefinition.rules,selection:selectedDefinition.selection,total_budget:selectedDefinition.total_budget,continuation:selectedDefinition.continuation},null,2)}</pre></details>
 <p>派生版：{selectedDefinition.children.join(', ')||'なし'}</p><p>この版の実験：</p><div className="actions">{selectedDefinition.experiment_ids.length?selectedDefinition.experiment_ids.map(id=><Button key={id} variant="outline" disabled={active||busy} onClick={()=>work(()=>open(id))}>{id.slice(0,8)}</Button>):'記録なし'}</div>
 <Button variant="outline" disabled={active} onClick={()=>setEditor(JSON.stringify(derivedDraft(selectedDefinition),null,2))}>この版から派生JSONを作る</Button><Button variant="outline" onClick={()=>download(definitionDocument(selectedDefinition),selectedDefinition.id+'-'+selectedDefinition.version+'.json')}>定義JSONを保存</Button></>}
 <details><summary>新しい宣言戦略・版を登録</summary><p>任意コード、式、ファイル操作は指定できません。親版とhashを固定し、同じID・版は上書きしません。変更したJSONのdefinition_hashを省略するとサーバーで計算します。</p><textarea aria-label="宣言戦略JSON" rows={14} value={editor} onChange={e=>setEditor(e.target.value)}/><Button disabled={busy||active||!editor} onClick={()=>work(async()=>{const d=await api<Definition>('/api/arena/definitions',JSON.parse(editor));await refresh();setSelected(d.id+'@'+d.version);})}>検証して新しい版を登録</Button></details></section>
 <section className="panel"><fieldset disabled={busy||active}><legend>固定相手とのリーグ計画</legend><p>同じIDを相手席にも指定できます。全6役割順は同一配札内の繰り返しで、独立標本ではありません。</p>
 <div className="catalog-pair">{catalog.definitions.map(d=><label key={d.reference}><input type="checkbox" checked={participants.includes(d.reference)} onChange={e=>toggle(d.reference,e.target.checked)}/>{d.name} · {d.version}</label>)}</div>
 <details><summary>既存AIの参加選択</summary>{catalog.builtins.map(ref=><label key={ref}><input type="checkbox" checked={participants.includes(ref)} onChange={e=>toggle(ref,e.target.checked)}/>{ref}</label>)}</details>
 {opponents.map((value,i)=><label key={i}>Arena相手 {i+1}<select value={value} onChange={e=>setOpponents(old=>old.map((x,j)=>j===i?e.target.value:x))}>{references.map(ref=><option key={ref} value={ref}>{ref}</option>)}</select></label>)}
 <label>Arena独立配札数<input type="number" min={1} max={20} value={deals} onChange={e=>setDeals(Number(e.target.value))}/></label>
 <label>Arena seed区分<select value={partition} onChange={e=>setPartition(e.target.value)}><option value="development">開発用</option><option value="validation">検証用</option><option value="final">最終評価用</option></select></label>
 <label>評価者用の配札offset<input type="number" min={0} max={999980} value={offset} onChange={e=>setOffset(Number(e.target.value))}/></label><label>独立した方策seed<input type="number" min={0} value={policySeed} onChange={e=>setPolicySeed(Number(e.target.value))}/></label>
 <label><input type="checkbox" checked={expensive} onChange={e=>setExpensive(e.target.checked)}/>高コスト探索戦略の参加を許可</label>
 <div className="actions"><Button onClick={()=>work(async()=>setPlan(await api('/api/arena/estimate',request())))}>Arenaの規模を見積もる</Button><Button disabled={!plan} onClick={()=>work(async()=>setStudy(await api('/api/arena/studies',request())))}>このArena計画で実行</Button></div></fieldset>
 {plan&&<p role="status">予定 {plan.games}対局 / 独立配札 {plan.independent_deals} / Rollout上限 {plan.rollout_upper_bound} / 約{plan.estimated_seconds_range.map(x=>x.toFixed(1)).join('〜')}秒 / JSON約{Math.ceil(plan.estimated_storage_bytes/1024)}KiB。{plan.resource_note}</p>}</section>
 <section className="panel"><label>Arenaの保存履歴<select value={study?.id??''} disabled={busy||active} onChange={e=>{if(e.target.value)work(()=>open(e.target.value));}}><option value="">選択してください</option>{history.map(h=><option key={h.id} value={h.id}>{h.id.slice(0,8)} · {studyStatus[h.status]??h.status} · {h.completed_games}対局</option>)}</select></label></section>
 <SavedStudyComparison history={history} basePath="/api/arena/studies"/>
 {study&&<><section className="panel"><h3>Arenaの結果</h3><p role="status">{studyStatus[study.status]??study.status} · {study.completed_games}対局 · {study.elapsed_seconds.toFixed(2)}秒</p><p>相手2役：{study.config.opponent_entries.map(e=>e.reference).join(' / ')}<br/>seed区分：{study.config.seed_partition} / 独立配札：{study.config.deal_seeds.length}<br/>基準SHA：<code>{study.config.baseline_commit}</code></p><p>{study.summary.method}<br/>{study.summary.warning}</p>
 {study.status!=='completed'&&<p>未完了です。全6役割順が揃った配札だけを成績へ使います。</p>}{study.error&&<p role="alert">{study.error}</p>}
 <div className="actions">{active&&<Button onClick={()=>work(async()=>setStudy(await api('/api/arena/studies/'+study.id+'/cancel',{})))}>Arenaを中断</Button>}<Button onClick={()=>work(async()=>download(await api('/api/arena/studies/'+study.id+'/export'),'arena-'+study.id+'.json'))}>Arena結果JSONを保存</Button></div></section>
 <section className="panel"><div className="table-scroll"><table><thead><tr><th>参加設定</th><th>平均終局報酬 / 95%区間</th><th>単独 / 共同 / 敗北</th><th>平均累計点</th><th>対局 / 独立配札</th><th>判断ms平均 / p95</th><th>実行Rollout</th></tr></thead><tbody>{study.summary.settings.map(s=><tr key={s.setting}><td>{s.reference}</td><td>{metricValue(s.average_terminal_reward)} / {intervalText(s.reward_ci95)}<small>{s.uncertainty?.reason}</small></td><td>{metricPercent(s.sole_win_rate)} / {metricPercent(s.joint_win_rate)} / {metricPercent(s.loss_rate)}</td><td>{metricValue(s.average_score)}</td><td>{s.games} / {s.independent_deals}</td><td>{metricValue(s.decision_ms.mean)} / {metricValue(s.decision_ms.p95)}</td><td>{s.executed_rollouts}</td></tr>)}</tbody></table></div>
 <Chart label="Arenaの判断時間と平均終局報酬" option={{tooltip:{},xAxis:{name:'判断ms'},yAxis:{min:-2,max:2,name:'平均終局報酬'},series:study.summary.settings.map(s=>({type:'scatter',name:s.reference,symbolSize:14,data:s.average_terminal_reward===null?[]:[[s.decision_ms.mean,s.average_terminal_reward]]}))}}/>
 <h3>先頭参加設定との差（対応配札）</h3>{study.summary.differences.map(d=><p key={d.setting}>{d.setting}: {d.comparable?`${metricValue(d.difference)} / ${intervalText(d.ci95)} · 独立配札${d.independent_deals}`:'対応比較不可：'+d.reasons.join(' ')}<br/>{d.uncertainty?.reason}</p>)}
 <details><summary>相手構成・席順別の成績</summary>{study.summary.settings.map(s=><p key={s.setting}>{s.reference} 対 {s.opponents.join(' / ')}<br/>{s.seats.map(t=>`P${t.seat+1}: ${t.games}対局・平均報酬${metricValue(t.average_terminal_reward)}`).join(' / ')}</p>)}</details></section>
 {study.positions.map((p,i)=><details className="panel" key={i}><summary>同一の公開人工局面での判断の違い</summary><p>{p.generation}</p>{p.choices.map(c=><section key={c.setting}><h3>{c.setting}：{label(c.selected_card)}</h3><DecisionExplanation decision={c.decision}/></section>)}</details>)}</>}
 </section>;
}
