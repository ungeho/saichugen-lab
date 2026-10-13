import {useEffect,useRef,useState} from 'react';
import {metricValue,metricPercent,type RewardMetrics} from '../../evaluation';
import {Chart} from '../../Chart';
import {Button} from '../../components/ui/button';
import {api,label,type Card,type Algorithm,type ComparisonPosition,type PositionComparison} from '../../model';
import {cardKey,groupChoices} from './comparisonModel';

type Stats=RewardMetrics&{card:Card;trials:number;wins:number;win_rate:number;ci95:number[];average_score:number;score_std:number;rank_distribution:Record<string,number>};
type Result={reward_version?:string;position:ComparisonPosition;seed:number;trials:number;continuation:{name:string;version:string}[];sampling_note:string;continuation_note:string;sampler:string;state_policy:string;candidates:Stats[];paired:{a:Card;b:Card;win_rate_difference:number;average_score_difference:number;average_terminal_reward_difference?:number;reward_difference_ci95?:number[]|null;reward_difference_samples?:number;reward_difference_zero_variance?:boolean;ci95:number[]|null}[]};
type Job={id:string;status:string;completed_trials:number;total_trials:number;candidate_count:number;result:Result|null;error:string|null};
const active=(job:Job|null)=>!!job&&['running','cancelling'].includes(job.status);
const percent=(n:number)=>(n*100).toFixed(1)+'%';

export function BranchSimulationPanel({position,comparison,algorithms,strategies,analysis}:{position:ComparisonPosition;comparison:PositionComparison|null;algorithms:Algorithm[];strategies:string[];analysis:boolean}){
 const [chartMetric,setChartMetric]=useState<'win'|'reward'>('win');
 const groups=groupChoices(comparison?.results??[]);
 const [selected,setSelected]=useState<string[]>([]);
 const [continuation,setContinuation]=useState(strategies);
 const [trials,setTrials]=useState('100');const [seed,setSeed]=useState('42');
 const [job,setJob]=useState<Job|null>(null);const [error,setError]=useState('');const [starting,setStarting]=useState(false);
 const generation=useRef(0);const jobId=useRef<string|null>(null);
 useEffect(()=>{setSelected(groups.map(g=>cardKey(g.card)));},[comparison]);
 useEffect(()=>()=>{generation.current++;if(jobId.current)void api('/api/branches/'+jobId.current+'/cancel',{}).catch(()=>{});},[]);
 useEffect(()=>{
  if(!job||!active(job))return;
  const token=generation.current;
  const timer=setTimeout(()=>{api<Job>('/api/branches/'+job.id).then(data=>{if(token===generation.current)setJob(data);}).catch(e=>{if(token===generation.current){setError(String(e));setJob(null);}});},350);
  return()=>clearTimeout(timer);
 },[job]);
 async function run(){
  const n=Number(trials),s=Number(seed);
  if(!trials.trim()||!Number.isInteger(n)||n<1||n>1000||n*selected.length>10000||!seed.trim()||!Number.isSafeInteger(s)){setError('試行は1〜1000回、候補数×試行回数は10000以下、シードは整数で指定してください。');return;}
  const token=generation.current;setStarting(true);setError('');setJob(null);
  try{
   const data=await api<Job>('/api/games/'+position.game_reference!.id+'/branches',{cards:position.legal_actions.filter(c=>selected.includes(cardKey(c))),strategies:continuation,trials:n,seed:s,turn:position.observation.turn,player:position.observation.player,analysis,information_condition:'imperfect'});
   if(token===generation.current){jobId.current=data.id;setJob(data);}else void api('/api/branches/'+data.id+'/cancel',{}).catch(()=>{});
  }catch(e){if(token===generation.current)setError(String(e));}
  finally{if(token===generation.current)setStarting(false);}
 }
 const busy=starting||active(job);const result=job?.result;
 return <section className="branch-panel" aria-label="分岐シミュレーション"><h3>この一手から、最後まで試してみる</h3>
 <p>最初のカードだけを変えて、同じ世界で続きを対戦します。推定結果は継続戦略と手札の仮定に依存し、正解を示すものではありません。</p>
 <fieldset disabled={busy}><legend>分岐する候補カード</legend><p className="muted">AI比較で選ばれたカードを初期選択します。同じカードは1回だけ計算します。</p><div className="branch-cards">{position.legal_actions.map(c=><label key={cardKey(c)}><input type="checkbox" checked={selected.includes(cardKey(c))} onChange={e=>{setJob(null);setSelected(v=>e.target.checked?[...v,cardKey(c)]:v.filter(k=>k!==cardKey(c)));}}/>{label(c)} <small>{groups.find(g=>cardKey(g.card)===cardKey(c))?.strategies.map(s=>s.name).join(' / ')}</small></label>)}</div>
 <div className="comparison-controls">{continuation.map((name,p)=><label key={p}>P{p+1}の継続戦略{p===position.observation.player?'（対象）':''}<select value={name} onChange={e=>{setJob(null);setContinuation(v=>v.map((n,i)=>i===p?e.target.value:n));}}>{algorithms.map(a=><option key={a.name} value={a.name}>{a.name} v{a.version}</option>)}</select></label>)}
 <label>分岐の試行回数<input type="number" min="1" max="1000" value={trials} onChange={e=>{setJob(null);setTrials(e.target.value);}}/></label>
 <label>分岐の乱数シード<input type="number" step="1" value={seed} onChange={e=>{setJob(null);setSeed(e.target.value);}}/></label></div></fieldset>
 <p className="muted">継続戦略は全席とも登録時の初期状態から開始します。実対戦の内部状態は流用しません。対象席では最初の一手を強制し、次のターンから戦略を呼びます。</p>
 <Button disabled={busy||!selected.length} onClick={run}>{starting?'実験を準備中…':'分岐シミュレーションを実行'}</Button>
 {active(job)&&<Button variant="outline" onClick={()=>api<Job>('/api/branches/'+job!.id+'/cancel',{}).then(setJob).catch(e=>setError(String(e)))}>計算を停止</Button>}
 {error&&<p role="alert" className="error">{error}</p>}
 {job&&<p role="status">{({running:'計算中',cancelling:'停止処理中',completed:'計算完了',cancelled:'停止しました',timed_out:'制限時間（60秒）で停止しました',failed:'計算に失敗しました'} as Record<string,string>)[job.status]} · {job.completed_trials} / {job.total_trials} 試行</p>}
 {job?.error&&<p role="alert" className="error">{job.error}</p>}
 {result&&<div className="branch-results">{result.trials<100&&<p className="error">試行回数が少ないため、推定結果は不安定です。</p>}
 <p>ターン {result.position.observation.turn+1} · P{result.position.observation.player+1} · 不完全情報 · シード {result.seed}</p>
 <div className="table-scroll"><table><caption>候補ごとの推定結果</caption><thead><tr><th>最初のカード</th><th>推定勝率（95%信頼区間）</th><th>単独 / 共同勝利率</th><th>平均最終累計得点</th><th>平均終局報酬</th><th>試行回数</th></tr></thead><tbody>{result.candidates.map(r=><tr key={cardKey(r.card)}><td>{label(r.card)}</td><td>{percent(r.win_rate)}（{r.ci95.map(percent).join('〜')}）</td><td>{metricPercent(r.sole_win_rate)} / {metricPercent(r.joint_win_rate)}</td><td>{r.average_score.toFixed(2)}</td><td>{metricValue(r.average_terminal_reward)}</td><td>{r.trials}</td></tr>)}</tbody></table></div>
 <p className="muted">勝率＝単独＋共同勝利率（全員勝利を含む）。終局報酬は累計得点に加算されない別の指標です。</p>
 <label>分岐結果のグラフ指標<select value={chartMetric} onChange={e=>setChartMetric(e.target.value as typeof chartMetric)}><option value="win">推定勝率</option><option value="reward">平均終局報酬</option></select></label>
 <Chart label={chartMetric==='win'?'候補カード別の推定勝率':'候補カード別の平均終局報酬'} option={{xAxis:{type:'category',data:result.candidates.map(r=>label(r.card))},yAxis:{type:'value',min:chartMetric==='win'?0:-2,max:chartMetric==='win'?100:2,name:chartMetric==='win'?'推定勝率 %':'終局報酬'},series:[{type:'bar',data:result.candidates.map(r=>chartMetric==='win'?r.win_rate*100:(r.average_terminal_reward??null)),itemStyle:{color:'#90e7ca'}}],tooltip:{trigger:'axis'}}}/>
 <details><summary>順位分布・ばらつき・候補間の差</summary>{result.candidates.map(r=><p key={cardKey(r.card)}>{label(r.card)}: 勝利 {r.wins} 回 · 得点標準偏差 {r.score_std.toFixed(2)} · {Object.entries(r.rank_distribution).map(([rank,count])=>rank+'位'+(rank.includes('–')?'同点':'')+' '+count+'回').join(' / ')}</p>)}{result.paired.map((p,i)=><p key={i}>{label(p.a)} − {label(p.b)}: 勝率差 {(p.win_rate_difference*100).toFixed(1)}ポイント · 近似95%区間 {p.ci95?p.ci95.map(n=>(n*100).toFixed(1)).join('〜'):'試行不足'} · 平均累計得点差 {p.average_score_difference.toFixed(2)}<br/>平均終局報酬差 {metricValue(p.average_terminal_reward_difference)} · 対応差の近似95%区間 {p.reward_difference_ci95?p.reward_difference_ci95.map(n=>n.toFixed(2)).join('〜'):'試行不足・未提供'}（{p.reward_difference_samples??0}組）{p.reward_difference_zero_variance&&' · 標本差の分散0：不確実性がないことを保証しません'}</p>)}<p className="muted">順位は得点の高い順。同点は占有する順位範囲で表示します。勝者はエンジンの中間得点ルールに従い、同時勝利を含みます。候補間の区間は対応する試行差の正規近似で、報酬差の区間も同じ試行の報酬差を標本にした正規近似です。1試行では未提供。少数試行・差の少ない標本では信頼できません。</p></details>
 <details><summary>サンプリングと再現条件</summary><p>{result.sampling_note}</p><p>{result.continuation_note}</p><p>{result.continuation.map((s,p)=>'P'+(p+1)+' '+s.name+' v'+s.version).join(' / ')}</p><p>局面 {result.position.snapshot_id} · ルール {result.position.rule_version} · {result.sampler} · {result.state_policy} · 報酬 {result.reward_version??'未記録'}</p><p className="muted">同じ試行では世界と席別の初期乱数状態を共有します。分岐後の乱数消費は異なる場合があります。信頼区間はこのサンプリングモデル内の誤差であり、仮定の誤りを含みません。</p></details></div>}
 </section>;
}

