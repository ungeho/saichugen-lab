# Phase 16：Monte Carlo Rollout戦略

実装・測定日：2026-10-13。戦略名 `monte_carlo_rollout`、バージョン `1`。ゲームルール・勝者判定・終局報酬表・既存5戦略の評価式は変更しない。

## 利用と設定

起動は従来どおり `powershell.exe -ExecutionPolicy Bypass -File .\scripts\dev.ps1`。各プレイヤーの選択欄で新戦略を指定する。人間対戦・AI観戦・比較実験・図鑑に自動反映される。同一局面比較では新戦略のチェックを選ぶ（既存5戦略の初期選択は維持）。

判断の詳細を有効にすると、候補の期待終局報酬・試行数・単独/共同勝利率・平均累計得点・標本標準偏差・近似95%区間、最善と次点の対応報酬差、探索seed、継続戦略、実測時間が表示される。詳細無効時も同じ計算・選択・外部乱数消費になるが、説明表の作成は省く。

画面は登録済み設定を使用する。詳細設定フォームは今回追加せず、変更はPythonのコンストラクタまたは設定付きfactory登録で行う。

```python
from strategy_arena.strategies.monte_carlo import MonteCarloRollout, DESCRIPTION
from strategy_arena.strategies.registry import register

strategy = MonteCarloRollout(trials=16, continuation="Heuristic", seed=42,
                             time_limit_ms=1000)
# アプリ起動前の登録例。同名の二重登録は不可。
register("rollout_16_heuristic", lambda: MonteCarloRollout(
    trials=16, continuation="Heuristic", seed=42), DESCRIPTION)
```

| 設定 | 既定値 | 意味・制限 |
| --- | --- | --- |
| trials | 8 | 候補ごとの試行数。整数1〜64、bool不可 |
| continuation | Random | 全席の継続戦略。既存の軽量5戦略のみ |
| seed | None | 対局・比較側のrngから128bit整数を1回取得。整数指定で固定 |
| time_limit_ms | None | 任意の協調時間上限0〜5000ms。既定は試行数だけで制限 |

最大17候補×64試行＝1088仮想対局/判断、既定の開始局面は136対局。時間上限は継続戦略の呼び出し前後等で確認し、強制終了ではない。上限で途中になった試行は全候補分を破棄し、全候補を評価し終えた試行だけを使う。完了0回なら評価値を捏造せずカード順の先頭へ退避する。合法手1枚も未評価でその札を返し、0枚は例外。

## 構成と再利用

- `strategies/monte_carlo.py`：戦略・設定検証・選択・任意の詳細ログ・図鑑説明。
- `rollouts.py`：既存分岐実験から `sampled_game` と1試行の `rollout_trial` を抽出。
- `branch_simulation.py`：共通処理を使用し、API・進捗・停止・seed領域を維持。既存のsampled_gameのimport経路も維持。
- 既存のUniformSampler、Game.from_deal、公開履歴再生、Game.play、terminal_rewards、clone_strategy、derived_seed、対応差集計を再利用。戦略から分岐ジョブやsimulateを呼ばない。
- registryへ登録し、実験API・CLIのstrategy_parametersへ設定を記録。分岐で継続に選んだ場合も設定を記録。既存戦略だけなら従来どおり空設定。
- RolloutSummaryと共通DecisionExplanationで、対戦履歴・同一局面比較の判断記録を表示。

## 評価と不完全情報

合法手と本人手札をカード順で正規化し、元観測を変更せずに試行する。本人の手札・公開カードを除いた未知札から相手2人の残枚数と余り1枚を一様に配り、52枚の一意性と公開履歴の再生結果をエンジンで検証する。実Game、実際の相手手札・余り札・配札seed・相手の将来乱数にはアクセスしない。同じ本人観測なら実際の隠し手札が違っても判断は同じ。

同一試行の全候補へ同じ世界と席別初期乱数を複製する。最初の本人の一手を候補札で強制し、その手番では本人継続戦略を呼ばない。以後は各席自身のObservationだけを渡して終局まで進める。継続戦略は試行・候補ごとの初期状態を複製し、仮想対局内だけ維持。実対局の内部状態は継承しない。

終局累計から既存エンジンが勝者を決めた後、terminal_rewardsで報酬を計算する。全候補の共通試行数が等しいため、本人の標本報酬合計を最大化する。単独勝者+2/敗者各−1、2人共同勝者各+1/敗者−2、全員0。累計へ加算せず勝者を再判定しない。勝率・累計・分散は表示だけで選択点に混ぜない。同点は数字・スートのカード順で先頭。

継続はRandom / Greedy / Conservative / ScoreAware / Heuristicに限定し、Rolloutや任意の探索戦略を指定すると拒否する。実対局が3席Rolloutでも内側は軽量戦略なので再帰しない。継続戦略を変えると結果と時間も変わる。

公開履歴はカード・得点・進行と整合するが、相手が過去の札を選びやすかったかという行動確率では重み付けしない。完全な事後分布や厳密な情報集合推論とは主張しない。一様配分・継続戦略のモデルの偏りは信頼区間に含まれない。

## 乱数・統計

固定試行数では同じ観測・設定・版・seedで同じ判断。候補や手札の表示順に依存せず、詳細有無で乱数消費を変えない。探索seedは文字列で記録し、JavaScriptの大整数の丸めを避ける。

世界seedはderived_seed(seed, "branch-world:{trial}")、席別seedはbranch-policy:{trial}:{seat}:{continuation}:{version}。既存分岐と同じ領域。分岐後の手札により乱数消費・選択は異なり得る。時間上限ありでは完了試行数が速度に依存し、同seedの同一結果を保証しない。

報酬平均の95%区間は平均±1.96×標本標準偏差/√N（−2〜+2で切る）。最善・次点の差は同じ試行の報酬差から既存の対応差関数で計算する。1試行は未提供。分散0でも確実性を保証しない。少数試行の正規近似、最大候補を後から選ぶ偏り・多重比較にも注意。MCTSの探索木・訪問回数による配分、ベイズ推論、学習は未実装。

## 性能測定

Windows・Python3.12.14・単一プロセス。Game(42)で先頭札を0/7/14ターン出した局面、各設定3回、詳細なし・Random継続。「最大」は測定内の最大で、上限保証ではない。

| 経過ターン | 候補数 | 試行/候補 | 平均ms | 最大ms |
| --- | ---: | ---: | ---: | ---: |
| 0 | 17 | 2 | 13.39 | 15.62 |
| 0 | 17 | 8 | 47.34 | 48.36 |
| 0 | 17 | 16 | 91.39 | 92.48 |
| 7 | 10 | 2 | 5.96 | 6.21 |
| 7 | 10 | 8 | 23.56 | 24.25 |
| 7 | 10 | 16 | 48.31 | 49.16 |
| 14 | 3 | 2 | 1.85 | 1.90 |
| 14 | 3 | 8 | 7.32 | 7.59 |
| 14 | 3 | 16 | 14.72 | 15.01 |

8試行は開始局面でも約50ms、全対局も実用的だったため既定に採用。seed42の対局全体はRollout/Random/Heuristicで0.391秒、3席Rolloutで1.142秒。継続戦略変更・同時処理・大量対戦では増える。

### 共通配札・座席回転の参考比較

配札seed0〜5の6独立配札×全6座席順＝36試合、所要14.10秒。Rolloutは8試行・Random継続。全戦略が同じ配札で各席を経験する。

| 戦略 | 勝率 | 単独 | 共同 | 平均累計 | 平均終局報酬 | 平均判断ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| monte_carlo_rollout | 55.56% | 38.89% | 16.67% | 10.36 | +0.444 | 25.765 |
| Random | 36.11% | 22.22% | 13.89% | 9.47 | −0.139 | 0.002 |
| Heuristic | 30.56% | 16.67% | 13.89% | 14.75 | −0.306 | 0.309 |

共同勝利のため勝率合計は100%を超える。独立配札は6件だけで36独立標本とは扱わない。この構成・予算での参考値であり一般に強いとは断定しない。生のローカル記録はGit管理外のresearch-local/に保持する。

## 検証と次の候補

Python134件（既存105＋追加29）成功。合法手、1枚・0枚、全席、固定seed・外部rng・手札順・詳細有無、実手札が異なる同一観測、52枚・残枚数、候補順反転の共通条件、分岐との統計一致、報酬と累計の区別、5継続戦略、設定拒否、64試行、時間切れ、API比較の非破壊、終局・実験・3席Rolloutを確認。既存戦略golden fixture、SQLite互換、分岐停止も成功。構文検査成功。

Vitest13件、TypeScript型検査・Viteビルド成功。Playwright21件（既存20＋追加1）成功。新戦略の対局・比較・実験・図鑑・狭幅表示を確認した。初回は新テストのラベル指定ミスで待機し検証サーバーが時間停止したため、comboboxのアクセシブル名による指定に直して単独成功後、全体も再実行した。既存のStarlette/httpx非推奨警告とViteバンドルサイズ警告は継続。

画面での探索設定編集、継続の席別指定、行動による推定、独立配札の拡充、適応配分、区間の改善、MCTSは今後の候補。大量対戦は基本戦略より重く、既存実験APIは同期処理なので少数配札から実行する。新規依存・ルール変更・commit/pushは行わない。


## 変更ファイル一覧

- README.md
- backend/src/strategy_arena/api/app.py
- backend/src/strategy_arena/branch_simulation.py
- backend/src/strategy_arena/experiments/cli.py
- backend/src/strategy_arena/strategies/registry.py
- backend/src/strategy_arena/rollouts.py（追加）
- backend/src/strategy_arena/strategies/monte_carlo.py（追加）
- backend/tests/test_monte_carlo.py（追加）
- frontend/src/features/game/DecisionExplanation.tsx
- frontend/src/features/game/RolloutSummary.tsx（追加）
- frontend/src/style.css
- frontend/e2e/monte-carlo.spec.ts（追加）
- docs/phase16.md（本書、追加）
