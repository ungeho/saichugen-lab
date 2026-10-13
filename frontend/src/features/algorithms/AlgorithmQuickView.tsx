import {useEffect,useId,useRef} from 'react';
import {Button} from '../../components/ui/button';
import type {Algorithm} from '../../model';

export function AlgorithmLink({name,onOpen}:{name:string;onOpen:(name:string)=>void}){
  return <button type="button" className="algorithm-link" onClick={()=>onOpen(name)} aria-label={`${name}の説明`}>{name}<span aria-hidden="true"> ⓘ</span></button>;
}

export function AlgorithmQuickView({name,algorithm,onClose,onDetailed}:{name:string;algorithm?:Algorithm;onClose:()=>void;onDetailed:()=>void}){
  const dialog=useRef<HTMLDialogElement>(null);const title=useId();
  useEffect(()=>{const element=dialog.current;element?.showModal();return()=>element?.close();},[]);
  return <dialog ref={dialog} className="algorithm-dialog" aria-labelledby={title} onCancel={onClose} onClick={e=>{if(e.target===e.currentTarget)onClose();}}>
    <div className="section-title"><h2 id={title}>{name}</h2><Button variant="outline" onClick={onClose}>閉じる</Button></div>
    <p className="accent">{algorithm?.tagline??'説明を取得できていません'}</p>
    <p>{algorithm?.overview||'説明が未登録でも、このアルゴリズムで対戦できます。'}</p>
    {algorithm&&<p className="muted">v{algorithm.version} · {algorithm.implementation}<br/>{algorithm.randomness}</p>}
    <Button onClick={onDetailed}>図鑑で詳しく見る</Button>
  </dialog>;
}
