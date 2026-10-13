import type {DecisionDetails,Card} from '../../model';
import {label} from '../../model';
import {metricValue,metricPercent} from '../../evaluation';
import {Chart} from '../../Chart';

type HybridMetadata={kind:string;seed:string;total_budget:number;unused_budget:number;started_games:number;executed_games:number;completed_games:number;elapsed_ms:number;heuristic_ms:number;allocation_ms:number;timed_out:boolean;fallback:string|null;priority_source?:unknown;parameters:{method:string;continuation:string;min_trials:number};candidates:{card:Card;trials:number;average_terminal_reward:number|null;sole_win_rate:number|null;joint_win_rate:number|null;average_score:number|null}[]};
export function HybridSummary({details}:{details:DecisionDetails}){
 return <HybridBudgetSummary metadata={details.optional_metadata??{}}/>;
}
export function HybridBudgetSummary({metadata}:{metadata:Record<string,unknown>}){
 if(metadata.kind!=='hybrid_search')return null;
 const m=metadata as unknown as HybridMetadata;
 return <section aria-label="Hybrid探索の予算と配分"><h3>総Rollout予算と実行記録</h3><p>方式 {m.parameters.method} / 継続 {m.parameters.continuation} / 最低 {m.parameters.min_trials}試行</p>
 <p>総予算 {m.total_budget} / 開始 {m.started_games} / 終局まで実行 {m.executed_games} / 評価に採用 {m.completed_games} / 未使用 {m.unused_budget}</p>
 <p>判断 {m.elapsed_ms.toFixed(2)}ms / {m.priority_source?'Theory評価':'Heuristic評価'} {m.heuristic_ms.toFixed(2)}ms / 追加先選択 {m.allocation_ms.toFixed(2)}ms</p><p>探索seed <code>{m.seed}</code></p>
 {m.timed_out&&<p>時間上限に達しました。途中の仮想対局も開始数へ含めます。</p>}{m.fallback&&<p>{m.fallback}</p>}
 <details><summary>候補別のRollout配分・補助指標</summary><Chart label="候補カード別のRollout配分" option={{tooltip:{},xAxis:{type:'category',data:m.candidates.map(c=>label(c.card))},yAxis:{name:'採用した試行数'},series:[{type:'bar',data:m.candidates.map(c=>c.trials)}]}}/>
 <div className="table-scroll"><table><thead><tr><th>候補</th><th>試行数</th><th>期待終局報酬</th><th>単独 / 共同勝利</th><th>平均累計</th></tr></thead><tbody>{m.candidates.map(c=><tr key={label(c.card)}><td>{label(c.card)}</td><td>{c.trials}</td><td>{metricValue(c.average_terminal_reward)}</td><td>{metricPercent(c.sole_win_rate)} / {metricPercent(c.joint_win_rate)}</td><td>{metricValue(c.average_score)}</td></tr>)}</tbody></table></div></details>
 <p className="muted">候補の95%区間は未提供。適応的な割当と最良候補の選択には偏りがあります。優先評価の点は報酬へ加算しません。同一Rollout予算の比較と同一時間予算の比較は異なります。</p></section>;
}
