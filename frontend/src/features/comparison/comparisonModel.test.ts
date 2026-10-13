import {describe,it,expect} from 'vitest';
import {comparisonTurn,groupChoices} from './comparisonModel';
import type {ComparedStrategy,Game} from '../../model';

function row(name:string,rank:number,suit:number):ComparedStrategy{return {name,version:'1',status:'ok',decision:{card:{rank,suit},desire_to_win:null,estimated_turn_win:null,explanation:''},state_source:'registered_initial_copy',state_note:'',elapsed_ns:1000,derived_seed:'42'};}
const game={finished:false,observation:{turn:3,history:[{index:0},{index:1},{index:2}]}} as Game;
describe('同一局面比較の表示モデル',()=>{
 it('進行中は次の選択直前、履歴では選択した判断直前を使う',()=>{expect(comparisonTurn(game,null)).toBe(3);expect(comparisonTurn(game,0)).toBe(0);expect(comparisonTurn(game,2)).toBe(2);});
 it('終了後の現在表示は最後の合法な判断を使う',()=>{expect(comparisonTurn({...game,finished:true,observation:{...game.observation,turn:15}},null)).toBe(14);});
 it('同じカードをまとめ、ランクが同じでもスートが違えば分ける',()=>{const rows=[row('A',7,0),row('B',7,0),row('C',7,3)];const groups=groupChoices(rows);expect(groups).toHaveLength(2);expect(groups[0].strategies.map(r=>r.name)).toEqual(['A','B']);expect(groups[1].strategies[0].name).toBe('C');expect(rows).toHaveLength(3);});
 it('失敗やカード未提供の結果に、架空のグループを作らない',()=>{expect(groupChoices([{...row('A',7,0),status:'error',decision:null}])).toEqual([]);});
});
