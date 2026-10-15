import {describe,it,expect} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {TournamentResults,tournamentInitial} from './TournamentResults';
import type {AdaptiveJob} from '../adaptive/AdaptivePanel';
describe('Final Tournament',()=>{
 it('64bit seedを文字列で保持し結果参照だけでは実験を開始しない',()=>{expect(typeof tournamentInitial.policy_seed).toBe('string');expect(JSON.parse(JSON.stringify(tournamentInitial)).policy_seed).toBe('18446744073709551045');});
 it('未完了ランキングを表示せず途中配札と終了判断を区別する',()=>{
  const job={status:'TimedOut',elapsed_seconds:1,snapshot:{study_plan_hash:'abc',study_plan:{hybrid_selection:'固定'}},tournament_evidence:{primary_finalized:false,complete_deals:1,partial_deals:1,not_started_deals:2,recorded_games:65,closure:'未完了',uncertainty:'配札単位',ranking:null,comparisons:null}};
  const html=renderToStaticMarkup(TournamentResults({job:job as unknown as AdaptiveJob}));expect(html).toContain('未完了の主要ランキングは表示しません');expect(html).toContain('途中 1');expect(html).not.toContain('<table>');
 });
});
