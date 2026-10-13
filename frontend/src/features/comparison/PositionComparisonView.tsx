import {useEffect,useRef,useState,type CSSProperties} from 'react';
import {Button} from '../../components/ui/button';
import {api,label,names,type Algorithm,type Game,type ComparisonPosition,type PositionComparison} from '../../model';
import {AlgorithmLink} from '../algorithms/AlgorithmQuickView';
import {DecisionExplanation} from '../game/DecisionExplanation';
import {cardKey,comparisonTurn,groupChoices} from './comparisonModel';
import {BranchSimulationPanel} from './BranchSimulationPanel';

const colors=['#90e7ca','#b5b0ff','#f3c788','#89cbed','#eea6c7','#d9e98a'];

export function PositionComparisonView({game,gameId,algorithms,selectedTurn,onSelectTurn,onAlgorithm,onAnalysis,gameBusy}:{game:Game;gameId:string;algorithms:Algorithm[];selectedTurn:number|null;onSelectTurn:(turn:number|null)=>void;onAlgorithm:(name:string)=>void;onAnalysis:()=>void;gameBusy:boolean}){
  const [player,setPlayer]=useState(0);const [seed,setSeed]=useState('42');const [selected,setSelected]=useState<string[]>(names);
  const [position,setPosition]=useState<ComparisonPosition|null>(null);const [result,setResult]=useState<PositionComparison|null>(null);
  const [loading,setLoading]=useState(false);const [running,setRunning]=useState(false);const [error,setError]=useState('');
  const generation=useRef(0);const root=useRef<HTMLElement>(null);
  const canViewOthers=game.finished&&!!game.analysis_visible;const effectivePlayer=canViewOthers?player:0;
  const turn=comparisonTurn(game,selectedTurn);const positionKey=`${gameId}:${turn}:${effectivePlayer}:${canViewOthers}`;
  const selectedNames=selected.filter(name=>algorithms.some(a=>a.name===name));
  const selectionKey=selectedNames.join('\u0000');

  useEffect(()=>{root.current?.scrollIntoView({block:'start',behavior:'smooth'});},[]);
  useEffect(()=>{
    const token=++generation.current;setLoading(true);setRunning(false);setPosition(null);setResult(null);setError('');
    api<ComparisonPosition>(`/api/games/${gameId}/comparison-position?turn=${turn}&player=${effectivePlayer}&analysis=${canViewOthers}`)
      .then(data=>{if(generation.current===token)setPosition(data);})
      .catch(e=>{if(generation.current===token)setError(String(e));})
      .finally(()=>{if(generation.current===token)setLoading(false);});
    return()=>{generation.current++;};
  },[positionKey]);
  useEffect(()=>setResult(null),[seed,selectionKey]);

  async function compare(){
    const numericSeed=Number(seed);
    if(!seed.trim()||!Number.isSafeInteger(numericSeed)){setError('乱数シードは整数で指定してください。');return;}
    const token=generation.current;setRunning(true);setError('');setResult(null);
    try{
      const data=await api<PositionComparison>(`/api/games/${gameId}/compare`,{strategies:selectedNames,seed:numericSeed,turn,player:effectivePlayer,analysis:canViewOthers,information_condition:'imperfect'});
      if(generation.current===token){setPosition(data.position);setResult(data);}
    }catch(e){if(generation.current===token)setError(String(e));}
    finally{if(generation.current===token)setRunning(false);}
  }
  const groups=groupChoices(result?.results??[]);const observation=position?.observation;
  const legalKeys=new Set(position?.legal_actions.map(cardKey));
  return <section ref={root} className="panel position-comparison" aria-label="同一局面のアルゴリズム比較">
    <div className="section-title"><div><small>SAME POSITION, DIFFERENT CHOICES</small><h2>同じ手札なら、何を選ぶ？</h2><p>選択する直前の同じ観測を各戦略に渡し、比較用に判断します。対戦はそのまま続けられます。</p></div></div>
    <div className="comparison-controls"><label>比較する局面<select value={selectedTurn===null?'current':String(selectedTurn)} onChange={e=>onSelectTurn(e.target.value==='current'?null:Number(e.target.value))}><option value="current">{game.finished?'最終ターンの選択直前':'現在の手番・選択直前'}</option>{game.observation.history.map(t=><option key={t.index} value={t.index}>履歴・ターン {t.index+1} の選択直前</option>)}</select></label>
      <label>対象プレイヤー<select value={effectivePlayer} onChange={e=>setPlayer(Number(e.target.value))}>{[0,1,2].map(p=><option key={p} value={p} disabled={p!==0&&!canViewOthers}>P{p+1} {game.strategies[p]}</option>)}</select></label>
      <label>比較の乱数シード<input type="number" step="1" value={seed} disabled={running} onChange={e=>setSeed(e.target.value)}/></label>
      {game.finished&&!canViewOthers&&<Button variant="outline" disabled={gameBusy} onClick={onAnalysis}>他プレイヤー視点を開く</Button>}
    </div>
    {!canViewOthers&&<p className="muted">対戦中はP1の視点です。P2・P3の視点は、終了後に分析表示を開くと利用できます。</p>}
    {error&&<p role="alert" className="error">{error}</p>}
    {loading&&<p role="status">局面を読み込み中…</p>}
    {position&&observation&&<div className="position-snapshot"><div className="position-heading"><strong>ターン {observation.turn+1} / 15・P{observation.player+1}の選択直前</strong><span className="badge">{position.information_condition==='imperfect'?'不完全情報':position.information_condition}</span><small>局面ID {position.snapshot_id.slice(0,12)}</small></div>
      <div className="table-scroll"><table><caption>選択直前の得点</caption><thead><tr><th>プレイヤー</th><th>ラウンド得点</th><th>ゲーム得点</th></tr></thead><tbody>{game.strategies.map((name,p)=><tr key={p}><td>P{p+1} {name}</td><td>{observation.round_scores[p]}</td><td>{observation.game_scores[p]}</td></tr>)}</tbody></table></div>
      <h3>対象プレイヤーの手札・合法手</h3><p className="muted">合法手は枠で強調しています。手札 {observation.hand.length} 枚・合法手 {position.legal_actions.length} 枚。</p><div className="position-hand">{observation.hand.map(card=><span key={cardKey(card)} className={`card ${[1,2].includes(card.suit)?'red':''} ${legalKeys.has(cardKey(card))?'legal-card':''}`}>{label(card)}</span>)}</div>
      <details className="public-context"><summary>この局面までの公開済みカード（{observation.history.length*3}枚）</summary>{observation.history.length?<ol>{observation.history.map(t=><li key={t.index}>ターン{t.index+1}: {t.cards.map((c,p)=>`P${p+1} ${label(c)}`).join(' / ')}</li>)}</ol>:<p>まだ公開済みカードはありません。</p>}</details>
    </div>}
    <fieldset className="comparison-selection" disabled={running}><legend>比較するアルゴリズム</legend>{algorithms.length?algorithms.map(a=><label key={a.name}><input type="checkbox" checked={selected.includes(a.name)} onChange={e=>setSelected(current=>e.target.checked?[...current,a.name]:current.filter(n=>n!==a.name))}/>{a.name} <small>v{a.version}</small></label>):<p className="muted">登録済みアルゴリズムの一覧を読み込み中です。</p>}</fieldset>
    <Button disabled={loading||running||!position||selectedNames.length===0} onClick={compare}>{running?'判断を比較中…':'この局面で比較する'}</Button>
    <p className="muted">対象席で動いている戦略は内部状態を複製し、他の戦略は登録設定から作る初期状態を使用します。詳細な状態の出所は各結果に表示します。</p>
    {result&&<div className="comparison-results"><h3>選択カードでグループ化</h3><p className="muted">比較シード {result.seed} で再判断した結果です。実際の対戦の選択は履歴の判断ログで確認できます。同じカードを選んだ戦略をまとめています。並び順や異なる戦略の評価値は、強さの順位ではありません。</p>
      <div className="choice-groups">{groups.map((group,index)=><section key={cardKey(group.card)} className="choice-group" style={{'--choice-color':colors[index%colors.length]} as CSSProperties} aria-label={`${label(group.card)}を選んだ戦略`}>
        <div className="choice-group-heading"><span className={`card ${[1,2].includes(group.card.suit)?'red':''}`}>{label(group.card)}</span><div><h3>{group.strategies.length}戦略がこのカードを選択</h3><p>{group.strategies.map(s=>s.name).join(' / ')}</p></div></div>
        {group.strategies.map(row=>{const algorithm=algorithms.find(a=>a.name===row.name);return <article className="compared-strategy" key={row.name} aria-label={`${row.name}の比較結果`}>
          <div className="compared-title"><h3><AlgorithmLink name={row.name} onOpen={onAlgorithm}/> <small>v{row.version}</small></h3><span>選択 {label(row.decision!.card)} · 判断 {row.elapsed_ns===null?'未記録':(row.elapsed_ns/1e6).toFixed(3)+' ms'}</span></div>
          <p className="accent">{algorithm?.tagline??'図鑑の説明は未登録です'}</p><p>{row.decision!.explanation||'この戦略は判断理由を提供していません。'}</p>
          <p className="muted">ランダム要素: {algorithm?.randomness??'未登録'}<br/>状態: {row.state_note}</p>
          <div className="information-tags" aria-label="実際に使用した情報">{row.decision!.details?.information_used.length?row.decision!.details.information_used.map((info,i)=><span key={i}>{info}</span>):<span>使用した情報の内訳は未提供</span>}</div>
          <details className="comparison-decision-details"><summary>{row.name}の候補評価・計算内訳を開く</summary><DecisionExplanation decision={row.decision!}/></details>
        </article>;})}
      </section>)}</div>
      {result.results.filter(row=>row.status==='error').map(row=><article key={row.name} className="error"><h3><AlgorithmLink name={row.name} onOpen={onAlgorithm}/></h3><p>{row.error}</p></article>)}
      <details className="comparison-reproducibility"><summary>再現条件を確認</summary><p className="muted">{result.randomness_note}時間は戦略の判断呼び出しを計測し、局面復元・戦略複製の時間は含めません。</p><p className="muted">ルール {result.position.rule_version} · 観測形式 v{result.position.schema_version}<br/>観測の局面ID {result.position.snapshot_id}</p><ul>{result.results.map(row=><li key={row.name}>{row.name} v{row.version??'取得できず'} · 独立シード {row.derived_seed??'実行前に失敗'}</li>)}</ul></details>
    </div>}
    {position&&<BranchSimulationPanel key={positionKey} position={position} comparison={result} algorithms={algorithms} strategies={game.strategies} analysis={canViewOthers}/>}
  </section>;
}
