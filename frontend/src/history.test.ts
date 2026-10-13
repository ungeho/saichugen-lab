import {describe,it,expect} from 'vitest';
import {historyFrame,formatEvaluation} from './history';
import type {Game} from './model';

const game:Game={finished:false,winners:[],strategies:['Random','Greedy','Heuristic'],decisions:[],observation:{player:0,turn:4,hand:[{rank:9,suit:0}],hand_sizes:[13,13,13],round_scores:[6,0,0],game_scores:[3,0,0],history:[
  {index:0,cards:[{rank:2,suit:0},{rank:1,suit:0},{rank:3,suit:0}],winner:0,round_scores:[2,0,0],game_scores:[0,0,0]},
  {index:1,cards:[{rank:4,suit:0},{rank:3,suit:1},{rank:2,suit:1}],winner:1,round_scores:[2,3,0],game_scores:[0,0,0]},
  {index:2,cards:[{rank:5,suit:0},{rank:7,suit:1},{rank:3,suit:2}],winner:0,round_scores:[7,3,0],game_scores:[0,3,0]},
  {index:3,cards:[{rank:6,suit:0},{rank:8,suit:1},{rank:9,suit:2}],winner:0,round_scores:[6,0,0],game_scores:[0,3,0]},
]}};

describe('判断時点の復元',()=>{
 it('最初の判断に未来の公開札や得点を含めない',()=>{const frame=historyFrame(game,0)!;expect(frame.beforeGame).toEqual([0,0,0]);expect(frame.publicHistory).toEqual([]);expect(frame.ownHandAfter.map(c=>c.rank)).toEqual([4,5,6,9]);});
 it('ラウンド境界でラウンド点だけをリセットする',()=>{const frame=historyFrame(game,3)!;expect(frame.beforeRound).toEqual([0,0,0]);expect(frame.beforeGame).toEqual([0,3,0]);expect(frame.publicHistory).toHaveLength(3);});
 it('評価なしとゼロを区別し、尺度を変換しない',()=>{expect(formatEvaluation(null)).toBe('評価なし');expect(formatEvaluation(0)).toBe('0.000000');expect(formatEvaluation(-2.5)).toBe('-2.500000');});
 it('存在しない履歴には値を作らない',()=>{expect(historyFrame(game,15)).toBeNull();});
});
