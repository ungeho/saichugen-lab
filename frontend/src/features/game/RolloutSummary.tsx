import type {DecisionDetails} from '../../model';

type RolloutMetadata={kind:string;seed:string;elapsed_ms:number;completed_trials:number;candidate_count:number;completed_games:number;timed_out:boolean;fallback:string|null;parameters:{trials:number;continuation:string};best_vs_runner_up:null|{average_terminal_reward_difference:number;reward_difference_ci95:number[]|null}};

export function RolloutSummary({details}:{details:DecisionDetails}){
  if(details.optional_metadata?.kind!=='monte_carlo_rollout')return null;
  const data=details.optional_metadata as unknown as RolloutMetadata;
  const pair=data.best_vs_runner_up;
  return <section className="rollout-summary" aria-label="Rolloutの探索条件"><h3>仮想対局の実行記録</h3>
    <p>継続戦略 {data.parameters.continuation} · 共通試行 {data.completed_trials} / {data.parameters.trials} 回 · 候補 {data.candidate_count} 枚 · 完了した仮想対局 {data.completed_games} 回 · 計算時間 {data.elapsed_ms.toFixed(2)} ms</p>
    <p>探索seed: <code>{data.seed}</code></p>
    {data.timed_out&&<p className="muted">時間上限に達しました。全候補の評価が完了していない試行は集計していません。</p>}
    {data.fallback&&<p>{data.fallback}</p>}
    {pair&&<p>最善と次点の平均終局報酬差 {pair.average_terminal_reward_difference.toFixed(3)} · 対応する試行差の近似95%区間 {pair.reward_difference_ci95?pair.reward_difference_ci95.map(n=>n.toFixed(3)).join('〜'):'試行不足'}</p>}
    <p className="muted">報酬平均の95%区間は標本分散の正規近似です。1試行では未提供。少数試行や分散0でも、確実な評価とは限りません。補助指標は選択スコアに混ぜません。表示時間は記録作成前までの実測で、再現性の対象外です。</p>
  </section>;
}
