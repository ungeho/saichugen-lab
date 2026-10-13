import {describe,it,expect} from 'vitest';
import {theoryVariants,partitionStarts,type TheoryConfig} from './theoryModel';
describe('Theoryの単独・対照・組み合わせ計画',()=>{
 const config:TheoryConfig={theories:[{id:'reserve_strong',enabled:true,weight:1,params:{}},{id:'round_focus',enabled:true,weight:1,params:{}},{id:'public_memory',enabled:false,weight:1,params:{}}]};
 it('対照と単独は有効性だけを変更し、組み合わせと比較戦略を含める',()=>{
  const variants=theoryVariants(config,'theory',64,'Heuristic');
  expect(variants).toHaveLength(5);
  const configs=variants.slice(0,4).map(v=>v.theory_config as TheoryConfig);
  expect(configs.map(c=>c.theories.filter(s=>s.enabled).map(s=>s.id))).toEqual([[],['reserve_strong'],['round_focus'],['reserve_strong','round_focus']]);
  expect(config.theories[0].enabled).toBe(true);
  expect(variants[4]).toEqual({method:'baseline',baseline_name:'Heuristic'});
 });
 it('探索の全条件で総予算を固定する',()=>{
  const variants=theoryVariants(config,'theory_search_adaptive',32,'uniform');
  expect(variants.every(v=>v.total_budget===32)).toBe(true);
 });
 it('重み0は単独候補にせず、大きな全組み合わせは拒否する',()=>{
  expect(theoryVariants({theories:[{...config.theories[0],weight:0}]},'theory',64,'none')).toHaveLength(1);
  const large={theories:Array.from({length:7},(_,i)=>({...config.theories[0],id:String(i)}))};
  expect(()=>theoryVariants(large,'theory',64,'none')).toThrow('最大8設定');
 });
 it('用途別seedの範囲を重複させない',()=>{
  expect(Object.values(partitionStarts)).toEqual([0,1000000,2000000]);
 });
});
