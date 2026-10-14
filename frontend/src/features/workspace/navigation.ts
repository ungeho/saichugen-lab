import {useEffect,useState} from 'react';
import {findPage,pages} from './registry';
export const recentKey='saichugen.workspace.recent';
export const groupKey='saichugen.workspace.middle.open';
export function readRecent():string[]{
  try{const value:unknown=JSON.parse(localStorage.getItem(recentKey)??'[]');return Array.isArray(value)?[...new Set(value.filter((id):id is string=>typeof id==='string'&&pages.some(p=>p.id===id)))].slice(0,6):[];}catch{return [];}
}
export function remember(id:string){
  if(!pages.some(p=>p.id===id))return;
  try{localStorage.setItem(recentKey,JSON.stringify([id,...readRecent().filter(x=>x!==id)].slice(0,6)));}catch{/* 保存不可でも画面は利用可能 */}
}
export function useWorkspaceRoute(){
  const [path,setPath]=useState(location.pathname);
  useEffect(()=>{const pop=()=>setPath(location.pathname);addEventListener('popstate',pop);return()=>removeEventListener('popstate',pop);},[]);
  const page=findPage(path);
  useEffect(()=>{document.title=`${page?.title??'画面が見つかりません'} | Saichugen Lab`;if(page)remember(page.id);},[page]);
  const navigate=(id:string)=>{const next=pages.find(p=>p.id===id);if(!next)return;if(location.pathname!==next.path){history.pushState(null,'',next.path);setPath(next.path);}};
  return {page,navigate};
}
