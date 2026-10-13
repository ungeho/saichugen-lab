import type {DecisionDetails,Card} from '../../model';
import {label} from '../../model';

type Evaluation={card:Card;score:number;terms:{id:string;value:number;weight:number;contribution:number;applicable:boolean;explanation:string}[]};
export function TheorySummary({details}:{details:DecisionDetails}){
 return <TheoryMetadata metadata={details.optional_metadata??{}}/>;
}
export function TheoryMetadata({metadata}:{metadata:Record<string,unknown>}){
 const rows=(metadata.kind==='theory_policy'?metadata.evaluations:metadata.priority_evaluations) as Evaluation[]|undefined;
 if(!rows)return null;
 return <section aria-label="Theoryごとの評価寄与"><h3>未検証の仮説の寄与</h3><p>仮説ごとの代理評価です。期待終局報酬ではありません。探索版では追加試行の優先順位にだけ使います。</p>
 <details><summary>仮説別の評価値・重み・寄与</summary><div className="table-scroll"><table><thead><tr><th>候補</th><th>合計</th><th>仮説</th><th>評価値</th><th>重み</th><th>寄与</th><th>適用</th></tr></thead><tbody>{rows.flatMap(r=>r.terms.map(t=><tr key={label(r.card)+t.id}><td>{label(r.card)}</td><td>{r.score.toFixed(4)}</td><td>{t.id}<small>{t.explanation}</small></td><td>{t.value.toFixed(4)}</td><td>{t.weight}</td><td>{t.contribution.toFixed(4)}</td><td>{t.applicable?'適用':'無効・不適用'}</td></tr>))}</tbody></table></div></details></section>;
}
