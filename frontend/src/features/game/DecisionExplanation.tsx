import {formatEvaluation} from '../../history';
import {label,type Decision} from '../../model';
import {RolloutSummary} from './RolloutSummary';
import {HybridSummary} from './HybridSummary';
import {TheorySummary} from './TheorySummary';

const componentLabels:Record<string,string>={trials:'共通試行数',sole_win_rate:'単独勝利率',joint_win_rate:'共同勝利率',average_score:'平均最終累計得点',reward_std:'終局報酬の標本標準偏差',turn_win_probability:'モデル上の獲得確率',desire:'獲得方針',target_score:'目標ラウンド得点',expected_distance:'目標からの予想距離',remaining_rank_distance:'残す札のランク7からの平均距離',win_term:'方針×獲得確率',distance_term:'得点距離の項',hand_term:'残り手札の項'};
export function DecisionExplanation({decision}:{decision:Decision}){
  const details=decision.details;
  return <div className="decision-explanation">{details?<><RolloutSummary details={details}/><HybridSummary details={details}/><TheorySummary details={details}/><h3>実際の判断手順</h3><ol className="reasoning">{details.reasoning.map((reason,i)=><li key={i}>{reason}</li>)}</ol><h3>候補カードと評価</h3><p className="muted">{details.score_label}。{details.candidates.length}枚の記録。選択したカードを強調しています。表示は小数第6位までですが、選択判定は丸め前の値を使います。</p>
      <div className="table-scroll"><table className="candidate-table"><thead><tr><th>候補</th><th>評価値</th><th>計算・評価の理由</th></tr></thead><tbody>{details.candidates.map(candidate=><tr key={`${candidate.card.rank}-${candidate.card.suit}`} className={candidate.card.rank===decision.card.rank&&candidate.card.suit===decision.card.suit?'chosen-candidate':''}><td>{label(candidate.card)}{candidate.card.rank===decision.card.rank&&candidate.card.suit===decision.card.suit&&<small> 選択</small>}</td><td>{formatEvaluation(candidate.score)}</td><td>{candidate.explanation||'評価理由は未提供'}{candidate.components&&<details><summary>計算に使った値</summary><dl className="component-values">{Object.entries(candidate.components).map(([key,value])=><div key={key}><dt>{componentLabels[key]??key}</dt><dd>{value.toFixed(6)}</dd></div>)}</dl></details>}</td></tr>)}</tbody></table></div>
      <div className="catalog-pair"><section><h3>戦略が使用した情報</h3>{details.information_used.length?<ul>{details.information_used.map((info,i)=><li key={i}>{info}</li>)}</ul>:<p className="muted">情報の内訳は未提供です。</p>}</section><section><h3>推定・仮定</h3>{details.estimates.length?<ul>{details.estimates.map((info,i)=><li key={i}>{info}</li>)}</ul>:<p className="muted">推定情報の記録はありません。</p>}</section></div></>:<p className="muted">このアルゴリズムは候補別の評価・判断手順を提供していません。評価値は生成していません。</p>}</div>;
}
