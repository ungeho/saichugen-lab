import type {Game} from './model';

export function historyFrame(game:Game, index:number){
  const history=game.observation.history;
  const event=history[index];
  if(!event) return null;
  const previous=history[index-1];
  return {
    beforeRound:previous&&index%3!==0?previous.round_scores:[0,0,0],
    beforeGame:previous?previous.game_scores:[0,0,0],
    afterRound:event.round_scores,
    afterGame:event.game_scores,
    publicHistory:history.slice(0,index),
    ownHandAfter:[...game.observation.hand,...history.slice(index+1).map(t=>t.cards[0])].sort((a,b)=>a.rank-b.rank||a.suit-b.suit),
    handSizesAfter:[17-index-1,17-index-1,17-index-1],
  };
}

export function formatEvaluation(score:number|null|undefined){
  return score===null||score===undefined?'評価なし':score.toFixed(6);
}
