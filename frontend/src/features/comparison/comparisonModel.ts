import type {Card,ComparedStrategy,Game} from '../../model';

export const cardKey=(card:Card)=>`${card.rank}:${card.suit}`;

export function comparisonTurn(game:Game, selectedTurn:number|null):number{
  if(selectedTurn!==null&&game.observation.history[selectedTurn])return selectedTurn;
  return game.finished?game.observation.turn-1:game.observation.turn;
}

export function groupChoices(results:ComparedStrategy[]){
  const groups=new Map<string,{card:Card;strategies:ComparedStrategy[]}>();
  for(const result of results){
    if(result.status!=='ok'||!result.decision)continue;
    const key=cardKey(result.decision.card);
    let group=groups.get(key);
    if(!group){group={card:result.decision.card,strategies:[]};groups.set(key,group);}
    group.strategies.push(result);
  }
  return [...groups.values()];
}
