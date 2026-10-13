import {useEffect,useState} from 'react';
import {Button} from '../../components/ui/button';
import {historyFrame} from '../../history';
import {label,type Game} from '../../model';
import {AlgorithmLink} from '../algorithms/AlgorithmQuickView';
import {DecisionExplanation} from './DecisionExplanation';

export function DecisionInspector({game,index,onAlgorithm,onAnalysis,busy}:{game:Game;index:number;onAlgorithm:(name:string)=>void;onAnalysis:()=>void;busy:boolean}){
  const [player,setPlayer]=useState(0);
  const frame=historyFrame(game,index);const decision=game.decisions[index]?.[player];
  useEffect(()=>setPlayer(0),[game.id]);
  if(!frame||!decision)return null;
  return <section className="panel decision-inspector" aria-label="判断過程の詳細"><div className="section-title"><div><small>RECORDED DECISION</small><h3>ターン {index+1} の判断をたどる</h3></div>{game.finished&&game.capture_details&&<Button variant="outline" disabled={busy} onClick={onAnalysis}>{game.analysis_visible?'自分の判断だけに戻す':'全員の判断を分析表示'}</Button>}</div>
    <p className="muted">選択時の計算記録と、実行環境が残した得点・公開情報です。図鑑の一般的な解説とは区別して表示します。評価値は戦略ごとに尺度が異なります。</p>
    <div className="inspector-tabs" aria-label="判断を見るプレイヤー">{game.strategies.map((name,p)=><Button key={p} variant={p===player?'default':'outline'} aria-pressed={p===player} onClick={()=>setPlayer(p)}>P{p+1} {name}</Button>)}</div>
    <div className="decision-heading"><span className={`card ${[1,2].includes(decision.card.suit)?'red':''}`}>{label(decision.card)}</span><div><small>選択カード · P{player+1}</small><h3><AlgorithmLink name={game.strategies[player]} onOpen={onAlgorithm}/> <small>v{game.strategy_versions?.[player]??'記録なし'}</small></h3><p>{decision.explanation||'このアルゴリズムは選択理由を提供していません。'}</p></div></div>
    <div className="table-scroll"><table className="score-change"><caption>判断前 → このターンの集計後</caption><thead><tr><th>プレイヤー</th><th>ラウンド得点</th><th>ゲーム得点</th></tr></thead><tbody>{game.strategies.map((name,p)=><tr key={p}><td>P{p+1} {name}</td><td>{frame.beforeRound[p]} → {frame.afterRound[p]}</td><td>{frame.beforeGame[p]} → {frame.afterGame[p]}</td></tr>)}</tbody></table></div>
    {index%3===2&&<p className="muted">このターンでラウンド終了。上のラウンド得点は3ターンの集計値で、次のラウンド開始時に0へ戻ります。</p>}
    {decision.details_status==='hidden'?<div className="empty">相手の候補には非公開手札が含まれるため、対戦中は詳細を表示しません。{game.finished?'「全員の判断を分析表示」で終了後の分析用に開けます。':'ゲーム終了後に分析表示できます。'}</div>:decision.details_status==='disabled'?<p className="muted">このゲームは詳細ログを記録していません。新しいゲームの開始前に「判断の詳細を記録」を有効にしてください。</p>:<>
      <DecisionExplanation decision={decision}/>
      <details className="public-context"><summary>判断時点までの公開情報（実行環境の記録）</summary><p>公開済み {frame.publicHistory.length} ターン・{frame.publicHistory.length*3} 枚。本人の未知札数: {decision.context?.unseen_count??'未記録'}。</p><p className="muted">この一覧のすべてを戦略が使用したという意味ではありません。現在のターンや未来の札は含めません。</p>{frame.publicHistory.length?<ol>{frame.publicHistory.map(turn=><li key={turn.index}>ターン{turn.index+1}: {turn.cards.map((card,p)=>`P${p+1} ${label(card)}`).join(' / ')} · P{turn.winner+1}が獲得</li>)}</ol>:<p>最初の選択なので、まだ公開札はありません。</p>}</details>
    </>}
    {game.analysis_visible&&<p className="footnote">終了後の分析表示には各プレイヤーの当時の候補手札が含まれます。対戦中のStrategyへ渡した情報条件は不完全情報のままです。</p>}
  </section>;
}
