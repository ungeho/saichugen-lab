import {useEffect,useState} from 'react';
import {signedReward} from '../../evaluation';
import {api,label,type Card,type Turn} from '../../model';
import {Button} from '../../components/ui/button';

type Source={id:string;name:string;url:string|null;location:string;status:string};
type Judgement={cards:Card[];weak_to_strong:number[];winner:number;round_delta:number[];game_delta:number[];rule:string;explanation:string};
type Guide={reward?:{version:string;source:string;table:{winners:number;winner_reward:number;loser_reward:number}[];note:string};rule_version:string;visibility_version:string;implementation_name:string;constants:Record<string,number>;rank_order:number[];suit_order:number[];sources:Source[];rules:{id:string;title:string;text:string;source:string;implementation:string}[];turn_examples:(Judgement&{title:string})[];round_examples:{title:string;turns:Turn[];round_scores:number[];winners:number[];game_delta:number[];next_round_scores:number[]}[];final_examples:{scores:number[];winners:number[];terminal_rewards?:number[]}[];uncertainties:string[];examples_origin:string};
const suitNames=['クラブ','ダイヤ','ハート','スペード'];
const ranks=(rank:number)=>({1:'A',11:'J',12:'Q',13:'K'}[rank]??rank);
const players=(values:number[])=>values.map(p=>'P'+(p+1)).join('・');
const points=(scores:number[])=>scores.map((n,p)=>'P'+(p+1)+': '+n).join(' / ');
function Cards({cards,winner}:{cards:Card[];winner:number}){
 return <div className="rule-cards">{cards.map((card,p)=><div key={p}><small>P{p+1}</small><span className={'card '+([1,2].includes(card.suit)?'red ':'')+(p===winner?'winner':'')}>{label(card)}</span>{p===winner&&<small>中間・獲得</small>}</div>)}</div>;
}
function Verdict({data}:{data:Judgement}){
 return <><Cards cards={data.cards} winner={data.winner}/><p>弱い順: {data.weak_to_strong.map(p=>'P'+(p+1)+' '+label(data.cards[p])).join(' < ')}<br/><strong>{data.explanation}</strong></p><p>ラウンド得点の増加: {points(data.round_delta)}<br/>ゲーム得点の増加: {points(data.game_delta)}</p><small>{data.rule}</small></>;
}
export function RulesPage(){
 const [guide,setGuide]=useState<Guide|null>(null);const [error,setError]=useState('');const [loading,setLoading]=useState(false);
 const [cards,setCards]=useState<Card[]>([{rank:7,suit:3},{rank:7,suit:0},{rank:7,suit:2}]);
 const [judgement,setJudgement]=useState<Judgement|null>(null);const [sampleError,setSampleError]=useState('');const [busy,setBusy]=useState(false);
 function load(){setLoading(true);setError('');api<Guide>('/api/rules').then(setGuide).catch(e=>setError(String(e))).finally(()=>setLoading(false));}
 useEffect(load,[]);
 async function judge(){setBusy(true);setSampleError('');setJudgement(null);try{setJudgement(await api<Judgement>('/api/rules/judge',{cards}));}catch(e){setSampleError(String(e));}finally{setBusy(false);}}
 const update=(player:number,field:'rank'|'suit',value:number)=>{setCards(current=>current.map((c,p)=>p===player?{...c,[field]:value}:c));setJudgement(null);setSampleError('');};
 return <section className="rules-page" aria-label="ゲームルール">
 <div className="section-title"><div><small>HOW TO PLAY</small><h2>「中間」を、3回目指すゲーム。</h2><p>カードの中間、ラウンド得点の中間、最後のゲーム得点の中間。それぞれの判定を分けて考えましょう。</p></div></div>
 {loading&&<p role="status">ルールを読み込み中…</p>}{error&&<div role="alert" className="error">{error}<Button variant="outline" onClick={load}>ルールを再読み込み</Button></div>}
 {guide&&<><p className="muted">{guide.implementation_name} · {guide.rule_version} · 公開仕様 {guide.visibility_version}</p>
 <div className="rules-overview">{[['人数',guide.constants.players+'人'],['配札',guide.constants.initial_hand+'枚ずつ'],['進行',guide.constants.turns_per_round+'ターン × '+guide.constants.rounds+'ラウンド'],['終局',guide.constants.turns+'ターン・残り各'+guide.constants.remaining_hand+'枚']].map(([name,value])=><div className="panel" key={name}><small>{name}</small><h3>{value}</h3></div>)}</div>
 <section className="panel rule-order"><h3>カードは数字が先、同じ数字ならスート</h3><p className="rule-ranks">{guide.rank_order.map(ranks).join(' > ')}</p><div className="rule-suits">{guide.suit_order.map((s,i)=><div key={s}>{i>0&&<b aria-hidden="true"> &gt; </b>}<span className={[1,2].includes(s)?'red-suit':''}>{'♣♦♥♠'[s]}</span><small>{suitNames[s]}</small></div>)}</div><p>♣K は ♠Q より強くなります。スートの順位を使うのは、数字が同じときだけです。</p><p className="muted">二次資料に基づく暫定採用。GPCC報告にはこの比較順の詳述はありません。スートによる得点の増減はありません。</p></section>
 <div className="rule-flow">{['1. 3枚の中間 → 数字をラウンド得点へ','2. 3ターンの中間 → 自分の合計をゲーム得点へ','3. 5ラウンドの中間 → 最終勝者'].map(text=><div className="panel" key={text}>{text}</div>)}</div>
 <section className="panel"><h3>遊び方と確認状況</h3><p className="muted">「GPCC一次資料で確認」は2009年の要約との一致を表します。原典全文の確認済みを意味しません。</p><div className="rule-list">{guide.rules.map(rule=>{const source=guide.sources.find(s=>s.id===rule.source)!;return <article key={rule.id}><h3>{rule.title}</h3><span className={'rule-status '+rule.source}>{source.status}</span><p>{rule.text}</p><details><summary>根拠と実装の対応</summary><p>{source.url?<a href={source.url} target="_blank" rel="noreferrer">{source.name}</a>:source.name}<br/>{source.location}</p><p className="muted">{rule.implementation}</p>{rule.id==='turn'&&<p className="muted">絵札・Aの数値対応は下の「カードの数値」の二次資料による採用です。</p>}</details></article>;})}</div></section>
 <section className="panel"><h3>カードを比べてみよう</h3><p>選択する3枚の中間を、実際の判定関数で調べます。同じカードは2回選べません。ラウンド途中、加算前は0点として表示する例です。</p>
 <fieldset disabled={busy} className="rule-sample-inputs"><legend>3人が出すカード</legend>{cards.map((c,p)=><div key={p}><label>P{p+1}の数字<select value={c.rank} onChange={e=>update(p,'rank',Number(e.target.value))}>{guide.rank_order.map(r=><option key={r} value={r}>{ranks(r)}</option>)}</select></label><label>P{p+1}のスート<select value={c.suit} onChange={e=>update(p,'suit',Number(e.target.value))}>{guide.suit_order.map(s=><option key={s} value={s}>{'♣♦♥♠'[s]} {suitNames[s]}</option>)}</select></label></div>)}</fieldset>
 <Button disabled={busy} onClick={judge}>{busy?'判定中…':'この3枚を判定'}</Button>{sampleError&&<p role="alert" className="error">{sampleError}</p>}{judgement&&<div className="rule-sample-result" role="status"><Verdict data={judgement}/></div>}</section>
 <section className="panel"><h3>具体例で理解する</h3><p className="muted">{guide.examples_origin}以下は説明用の独立した例で、対戦中の手札は使用しません。</p><div className="rule-examples">{guide.turn_examples.map(example=><article key={example.title}><h3>{example.title}</h3><Verdict data={example}/></article>)}</div>
 <h3>3ターンの得点を、ゲーム得点へ</h3>{guide.round_examples.map(example=><article className="rule-round-example" key={example.title}><h3>{example.title}</h3><div className="table-scroll"><table><thead><tr><th>ターン</th><th>P1</th><th>P2</th><th>P3</th><th>獲得者・点</th></tr></thead><tbody>{example.turns.map(t=><tr key={t.index}><td>{t.index+1}</td>{t.cards.map((c,p)=><td key={p}>{label(c)}</td>)}<td>P{t.winner+1} +{t.cards[t.winner].rank}</td></tr>)}</tbody></table></div><p>3ターンの合計: {points(example.round_scores)}<br/>中間の勝者: {players(example.winners)}<br/><strong>ゲーム得点の増加: {points(example.game_delta)}</strong><br/>次ラウンドのラウンド得点: {points(example.next_round_scores)}</p><p className="muted">中央の得点と同点の全員が、自分の合計だけを加算します。0点なら勝者でも加算は0です。</p></article>)}
 <h3>終局ではゲーム得点の中間が勝利</h3><p className="muted">次の表は判定だけの例です。終局時に得点は再配分せず、5ラウンド合計をそのまま比較します。</p><div className="table-scroll"><table><thead><tr><th>最終ゲーム得点（P1 / P2 / P3）</th><th>勝者</th><th>累計得点の変化</th><th>終局報酬（P1 / P2 / P3）</th></tr></thead><tbody>{guide.final_examples.map((e,i)=><tr key={i}><td>{e.scores.join(' / ')}</td><td>{players(e.winners)}</td><td>なし</td><td>{e.terminal_rewards?.map(signedReward).join(' / ')??'未提供'}</td></tr>)}</tbody></table></div></section>
 {guide.reward&&<section className="panel terminal-reward-rules" aria-label="終局報酬のルール"><h3>終局報酬と累計得点を分けて考える</h3><p>累計得点の中間から勝者を確定した後で計算する、別の評価指標です。累計得点には加算せず、勝者を再判定しません。勝率と平均終局報酬は異なる観点です。</p><div className="table-scroll"><table><thead><tr><th>勝者人数</th><th>各勝者の報酬</th><th>各敗者の報酬</th></tr></thead><tbody>{guide.reward.table.map(r=><tr key={r.winners}><td>{r.winners}人</td><td>{signedReward(r.winner_reward)}</td><td>{r.winners===3?'0（敗者なし）':signedReward(r.loser_reward)}</td></tr>)}</tbody></table></div><p>単独勝利の例: 累計10 / 25 / 40 → 勝者P2 → 報酬−1 / +2 / −1。<br/>共同勝利の例: 累計10 / 10 / 4 → 勝者P1・P2 → 報酬+1 / +1 / −2。累計はそのままです。</p><p>{guide.reward.note}</p><p><a href="https://ipsj.ixsq.nii.ac.jp/record/58572/files/IPSJ-GI03010005.pdf" target="_blank" rel="noreferrer">2003年論文・紙面32–33、表2</a></p><small>報酬版: {guide.reward.version}</small></section>}
 <section className="panel"><h3>根拠資料・未確認事項</h3>{guide.sources.map(s=><p key={s.id}><strong>{s.status}</strong><br/>{s.url?<a href={s.url} target="_blank" rel="noreferrer">{s.name}</a>:s.name}<br/>{s.location}</p>)}<ul>{guide.uncertainties.map(u=><li key={u}>{u}</li>)}</ul></section>
 </>}
 </section>;
}

