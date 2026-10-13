import {SavedStudyComparison} from './SavedStudyComparison';
import {useEffect,useState,useRef} from 'react';
import {api,label} from '../../model';
import {metricValue,metricPercent} from '../../evaluation';
import {Chart} from '../../Chart';
import {Button} from '../../components/ui/button';
import {intervalText,studyActive,studyStatus,type QualityStudy,type StudyConfig} from './qualityModel';

type Preset={id:string;config:StudyConfig};
type History={id:string;name:string;status:string;completed_games:number};
export function QualityStudyPanel(){
 const [presets,setPresets]=useState<Preset[]>([]);const [history,setHistory]=useState<History[]>([]);
 const [text,setText]=useState('');const [plan,setPlan]=useState<QualityStudy['estimate']|null>(null);
 const [study,setStudy]=useState<QualityStudy|null>(null);const [busy,setBusy]=useState(false);const [error,setError]=useState('');
 const generation=useRef(0);
 const refresh=()=>api<History[]>('/api/quality-studies').then(setHistory);
 useEffect(()=>{api<Preset[]>('/api/quality-studies/presets').then(p=>{setPresets(p);if(p[0])setText(JSON.stringify(p[0].config,null,2));}).catch(e=>setError(String(e)));refresh().catch(e=>setError(String(e)));return()=>{generation.current++;};},[]);
 useEffect(()=>setPlan(null),[text]);
 useEffect(()=>{
  if(!study||!studyActive(study.status))return;
  const token=generation.current;
  const timer=setTimeout(()=>{api<QualityStudy>('/api/quality-studies/'+study.id).then(s=>{if(token===generation.current){setStudy(s);if(!studyActive(s.status))refresh().catch(e=>setError(String(e)));}}).catch(e=>{if(token===generation.current){setError(String(e));setStudy(s=>s?{...s}:s);}});},600);
  return()=>clearTimeout(timer);
 },[study]);
 async function work(action:()=>Promise<void>){setBusy(true);setError('');try{await action();}catch(e){setError(String(e));}finally{setBusy(false);}}
 const running=!!study&&studyActive(study.status);
 const config=()=>JSON.parse(text) as StudyConfig;
 const download=(value:unknown,name:string)=>{const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();URL.revokeObjectURL(url);};
 const summaries=study?.summary.settings??[];
 const chartRows=summaries.filter(s=>s.average_terminal_reward!==null);
 return <section className="quality-study" aria-label="Rolloutの探索品質評価"><div className="section-title"><div><small>ROLLOUT QUALITY / PHASE 18</small><h2>試行数と継続戦略を、同じ配札で比べる。</h2><p>主指標は平均終局報酬。累計得点・単独/共同勝利率・計算時間も別に確認します。</p></div></div>
 <section className="panel"><fieldset disabled={busy||running}><legend>段階的な実験計画</legend><label>実験プリセット<select aria-label="実験プリセット" onChange={e=>{const p=presets.find(p=>p.id===e.target.value);if(p)setText(JSON.stringify(p.config,null,2));}}>{presets.map(p=><option key={p.id} value={p.id}>{p.config.name}</option>)}</select></label>
 <p className="muted">Phase 18 Stage1は少数配札で相手構成ごとに8/16試行を確認します。Stage2は混合相手の10配札。従来のA/B候補も利用できます。時間見積もりを確認し、長時間の計画は実行せず分割・絞り込みを検討してください。</p>
 <details open><summary>実験設定JSON（保存した設定を貼り付けて再実行可能）</summary><textarea aria-label="探索品質実験の設定JSON" value={text} onChange={e=>setText(e.target.value)} rows={12}/></details>
 <div className="actions"><Button variant="outline" onClick={()=>work(async()=>setPlan(await api('/api/quality-studies/estimate',config())))}>実験規模を見積もる</Button><Button variant="outline" onClick={()=>work(async()=>download(config(),'rollout-quality-config.json'))}>設定JSONを保存</Button><Button disabled={!plan} onClick={()=>work(async()=>{generation.current++;setStudy(await api('/api/quality-studies',config()));})}>この計画で実行</Button></div></fieldset>
 {plan&&<p role="status">予定 {plan.games}対局 / 独立配札 {plan.independent_deals} / 仮想対局上限 {plan.rollout_upper_bound.toLocaleString()}。{plan.note}<br/>推定所要時間 {plan.estimated_seconds_range?plan.estimated_seconds_range.map(n=>n.toFixed(1)).join('〜')+'秒':'未校正・先に小規模測定'} / 保存JSON概算 {plan.estimated_storage_bytes?Math.ceil(plan.estimated_storage_bytes/1024)+'KiB':'未提供'}<br/>{plan.resource_note}</p>}
 {error&&<p role="alert" className="error">{error}</p>}</section>
 <section className="panel"><label>保存済み探索品質実験<select aria-label="保存済み探索品質実験" value={study?.id??''} disabled={running||busy} onChange={e=>{if(e.target.value)work(async()=>{generation.current++;setStudy(await api('/api/quality-studies/'+e.target.value));});}}><option value="">選択してください</option>{history.map(h=><option key={h.id} value={h.id}>{h.name} · {studyStatus[h.status]??h.status} · {h.completed_games}対局</option>)}</select></label></section>
 <SavedStudyComparison history={history}/>
 {study&&<><section className="panel"><h3>実行条件と進捗</h3><p role="status">{studyStatus[study.status]??study.status} · {study.completed_games} / {study.estimate.games} 対局 · {study.elapsed_seconds.toFixed(1)}秒</p><p>基準コミット <code>{study.baseline_commit}</code><br/>配札seed {study.config.deal_seeds.join(', ')} / 方策seed {study.config.policy_seed} / 相手 {study.config.opponents.join('・')} / 全6席順 / 設定間で共通配札 / 不完全情報</p><p>設定 {study.config.settings.map(s=>`${s.trials}試行・${s.continuation}・時間上限${s.time_limit_ms??'なし'}${s.time_limit_ms==null?'':'ms'}`).join(' / ')}</p>
 {study.status!=='completed'&&<p className="error">未完了の実験です。報酬統計は各設定で6席順が揃った配札だけを使用します。中断結果を完了扱いにしません。</p>}
 <div className="actions">{running&&<Button onClick={()=>work(async()=>setStudy(await api('/api/quality-studies/'+study.id+'/cancel',{})))}>実験を中断</Button>}<Button variant="outline" onClick={()=>work(async()=>download(await api('/api/quality-studies/'+study.id+'/export'),'rollout-quality-'+study.id+'.json'))}>結果JSONを保存</Button></div>{study.error&&<p role="alert" className="error">{study.error}</p>}
 <p className="muted">{study.summary.method}<br/>{study.summary.warning} 10配札未満・分散0の区間は非表示。10〜19配札も参考区間です。点推定を確定順位と扱わないでください。</p></section>
 <section className="panel"><h3>設定ごとの対戦成績</h3><div className="table-scroll"><table><thead><tr><th>試行数 / 継続</th><th>平均終局報酬・95%区間</th><th>単独 / 共同勝利率</th><th>平均累計</th><th>使用対局 / 独立配札</th></tr></thead><tbody>{summaries.map(s=><tr key={s.setting}><td>{s.parameters.trials} / {s.parameters.continuation}</td><td>{s.independent_deals<20?'暫定 ':''}{metricValue(s.average_terminal_reward)}（{intervalText(s.reward_ci95)}）<small>{s.uncertainty?.reason}</small></td><td>{metricPercent(s.sole_win_rate)} / {metricPercent(s.joint_win_rate)}</td><td>{metricValue(s.average_score)}</td><td>{s.games} / {s.independent_deals}{s.excluded_partial_games>0&&` · 未完・条件不一致配札の${s.excluded_partial_games}対局を除外`}</td></tr>)}</tbody></table></div></section>
 <div className="charts"><section className="panel"><h3>試行数・継続戦略と報酬</h3><Chart label="Rollout設定別の平均終局報酬と95%区間" option={{tooltip:{trigger:'axis'},xAxis:{type:'category',data:chartRows.map(s=>`${s.parameters.trials}/${s.parameters.continuation}`)},yAxis:{min:-2,max:2,name:'平均終局報酬'},legend:{},series:[{name:'平均',type:'bar',data:chartRows.map(s=>s.average_terminal_reward)},{name:'95%下限（未提供は欠損）',type:'line',showSymbol:true,data:chartRows.map(s=>s.reward_ci95?.[0]??null),lineStyle:{opacity:0}},{name:'95%上限（未提供は欠損）',type:'line',showSymbol:true,data:chartRows.map(s=>s.reward_ci95?.[1]??null),lineStyle:{opacity:0}}]}}/></section>
 <section className="panel"><h3>計算時間と報酬（点推定）</h3><Chart label="判断時間と平均終局報酬の散布図" option={{tooltip:{},legend:{},xAxis:{type:'value',name:'平均判断ms'},yAxis:{min:-2,max:2,name:'平均終局報酬'},series:chartRows.map(s=>({name:`${s.parameters.trials}/${s.parameters.continuation}`,type:'scatter',data:[[s.decision_ms.mean,s.average_terminal_reward]],symbolSize:14}))}}/><p className="muted">時間は環境依存。上の区間と独立配札数も確認し、点だけで効率の優劣を断定しないでください。</p></section>
 <section className="panel"><h3>基準設定との差</h3><Chart label="基準設定との対応報酬差と95%区間" option={{tooltip:{trigger:'axis'},xAxis:{type:'category',data:study.summary.differences.map(d=>d.setting)},yAxis:{name:'平均報酬差'},series:[{name:'対応差',type:'bar',data:study.summary.differences.map(d=>d.difference)},{name:'95%下限',type:'line',lineStyle:{opacity:0},data:study.summary.differences.map(d=>d.ci95?.[0]??null)},{name:'95%上限',type:'line',lineStyle:{opacity:0},data:study.summary.differences.map(d=>d.ci95?.[1]??null)}]}}/><p>基準 {study.summary.baseline}</p>{study.summary.differences.map(d=><p key={d.setting}>{d.setting}: {metricValue(d.difference)}（{intervalText(d.ci95)}）· 対応する独立配札 {d.independent_deals}<br/>{d.comparable===false?d.reasons?.join(' '):d.uncertainty?.reason}</p>)}</section></div>
 <details className="panel"><summary>計算時間・実行Rollout数の詳細</summary><div className="table-scroll"><table><thead><tr><th>設定</th><th>判断ms 平均 / 中央 / p95 / 最大</th><th>対局平均秒</th><th>開始 / 終局まで実行 / 公平な集計に採用</th><th>判断の時間切れ</th></tr></thead><tbody>{summaries.map(s=><tr key={s.setting}><td>{s.setting}</td><td>{[s.decision_ms.mean,s.decision_ms.median,s.decision_ms.p95,s.decision_ms.max].map(v=>metricValue(v)).join(' / ')}</td><td>{metricValue(s.game_seconds_mean)}</td><td>{s.started_rollouts} / {s.executed_rollouts} / {s.accepted_rollouts}</td><td>{s.timeout_decisions}</td></tr>)}</tbody></table></div><p className="muted">時間には計測用の詳細作成も含みます。対局時間は全席分、判断時間は対象Rollout席だけ。共通局面プローブはこの対戦指標に含めません。</p></details>
 {study.positions.map(p=><details className="panel" key={p.snapshot_id}><summary>同じ局面で選択が{p.changed?'変わりました':'一致しました'}</summary><p>局面 {p.snapshot_id}<br/>{p.generation}</p>{p.choices.map(c=><p key={c.setting}>{c.setting}: {label(c.selected_card)} · 探索seed {c.seed}</p>)}<details><summary>本人の観測と候補評価（JSON）</summary><pre>{JSON.stringify(p,null,2)}</pre></details></details>)}</>}
 </section>;
}
