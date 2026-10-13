import {useState} from 'react';
import {api} from '../../model';
import {metricValue} from '../../evaluation';
import {Button} from '../../components/ui/button';
import {intervalText,type QualityStudy,type Uncertainty} from './qualityModel';

type Result={comparable:boolean;reasons:string[];difference:number|null;ci95:number[]|null;independent_deals:number;uncertainty?:Uncertainty;conditions:unknown;matched_deals?:string[];first_only_deals?:string[];second_only_deals?:string[]};
export function SavedStudyComparison({history}:{history:{id:string;name:string}[]}){
 const [first,setFirst]=useState<QualityStudy|null>(null),[second,setSecond]=useState<QualityStudy|null>(null);
 const [a,setA]=useState(''),[b,setB]=useState('');const [result,setResult]=useState<Result|null>(null);
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 async function load(id:string,left:boolean){setBusy(true);setError('');setResult(null);try{const data=await api<QualityStudy>('/api/quality-studies/'+id);if(left){setFirst(data);setA(data.summary.settings[0]?.setting??'');}else{setSecond(data);setB(data.summary.settings[0]?.setting??'');}}catch(e){setError(String(e));}finally{setBusy(false);}}
 async function compare(){setBusy(true);setError('');setResult(null);try{setResult(await api('/api/quality-studies/compare',{first_id:first!.id,second_id:second!.id,first_setting:a,second_setting:b}));}catch(e){setError(String(e));}finally{setBusy(false);}}
 return <section className="panel" aria-label="保存実験の対応条件照合"><h3>保存実験を条件照合して比較</h3><p>相手・方策seed・基準SHA・ルール/情報条件・戦略ソース等が一致した共通配札だけを対応比較します。異なる相手の結果を強さランキングに混ぜません。</p>
 <fieldset disabled={busy}><label>比較元の実験<select value={first?.id??''} onChange={e=>{if(e.target.value)load(e.target.value,true);}}><option value="">選択してください</option>{history.map(h=><option key={h.id} value={h.id}>{h.name} · {h.id.slice(0,8)}</option>)}</select></label>
 <label>比較元の設定<select value={a} onChange={e=>{setA(e.target.value);setResult(null);}}>{first?.summary.settings.map(s=><option key={s.setting}>{s.setting}</option>)}</select></label>
 <label>比較先の実験<select value={second?.id??''} onChange={e=>{if(e.target.value)load(e.target.value,false);}}><option value="">選択してください</option>{history.map(h=><option key={h.id} value={h.id}>{h.name} · {h.id.slice(0,8)}</option>)}</select></label>
 <label>比較先の設定<select value={b} onChange={e=>{setB(e.target.value);setResult(null);}}>{second?.summary.settings.map(s=><option key={s.setting}>{s.setting}</option>)}</select></label>
 <Button disabled={!first||!second||!a||!b} onClick={compare}>条件を照合して対応比較</Button></fieldset>
 {error&&<p role="alert" className="error">{error}</p>}{result&&<>{result.comparable?<><p role="status">比較先 − 比較元：{metricValue(result.difference)} · 対応する独立配札 {result.independent_deals}</p><p>95%区間 {intervalText(result.ci95)}<br/>{result.uncertainty?.reason}</p><p>対応した配札 {result.matched_deals?.join(', ')} / 元だけ {result.first_only_deals?.join(', ')||'なし'} / 先だけ {result.second_only_deals?.join(', ')||'なし'}</p></>:<p role="alert" className="error">対応比較にできません。{result.reasons.join(' ')}</p>}<details><summary>比較条件の違いを確認</summary><pre>{JSON.stringify(result.conditions,null,2)}</pre></details></>}
 </section>;
}
