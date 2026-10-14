# Phase 26：Zigzag Strategy Lab

## 基準とルール確認

Phase 25を通常commit・pushした基準SHAは `1f26944d40bef87fb357ab495c7902423568f8d4`。ゲームエンジン、得点、終局報酬、既存戦略の選択処理は変更しない。

現在の実装は52枚を17枚ずつ3人に配り1枚余る。数字はK=13からA=1の順で、数字を先に比較し、同数字なら♠>♥>♦>♣。各手で全員1枚を同時に提出し、カードの強さの中間がその札の数字をラウンド内得点として得る。3手のラウンド終了時、その得点が中間の全プレイヤーにラウンド内得点を累積得点へ加算する。他のプレイヤーはそのラウンドの加算0。5ラウンド・15手で終了し、各2枚残る。最終累積得点が中間の全プレイヤーが勝者。

終局報酬は勝者1人なら+2／敗者−1、勝者2人なら各+1／敗者−2、全員勝者なら全員0。累積得点へ加算せず、勝者を再判定しない。詳しい出典区分はcurrent-rules.md、rules-audit.mdを参照。

## ZigzagとReverse Zigzag

Zigzagは残り合法手の最強→最弱、Reverseは最弱→最強。ゲーム内手番の偶奇で切り替えるため、内部状態をリセットする必要がなく、履歴局面から比較しても同じ手を選ぶ。ラウンド境界でリセットしない。観測の合法手と手番番号だけで選ぶ。乱数・得点・探索・相手手札は使わない。詳細表示時だけ本人の手札と本人の公開済み札を合わせて初期順位を復元する。

初期順位は1が最強、17が最弱。Zigzagの先頭4手は1,17,2,16、Reverseは17,1,16,2。17枚を全て使い切るのではなく15手で終わるため、中央付近の2枚が残る。これは構造的性質であり、実際のターン2位やゲーム勝利を意味しない。

## 仮説と順位の定義

H1：端の札の先行消費は実装テストで確認。H2：序盤のターン1位・3位率、H3：終盤のターン2位率、H4：累積得点の中間化、H5：終局報酬改善は相手依存の探索仮説。H6：公開列からの予測可能性は別仮説。結果を見て仮説や区分を変更しない。

序盤1–5手、中盤6–10手、終盤11–15手で固定する。ターン順位は出札の強さの降順で1,2,3。ラウンド順位は3手分のラウンド内得点、累積順位は各ラウンド終了後の累積得点を降順で比較する。最終単独2位は同点のない中間。これらを終局報酬と混同しない。

同点時は占める順位枠を保持する。例：8,8,3なら同点の2人は[1,2]、8,3,3なら同点の2人は[2,3]、全同点なら[1,2,3]。分布の集約では順位枠へ等分する。同点率と単独順位率を別に表示する。ラウンド中間成功率は既存median_playersによる共同中間を含む。

補助指標の厳密中間は他2人の得点のmin < 本人 < max。同点込み中間はmin ≤ 本人 ≤ max。既存勝者判定を置き換える指標ではない。1位との差はmax−本人、3位との差は本人−min。

## 実装構成と記録

strategies/zigzag.pyを既存レジストリ・図鑑へ登録。通常対局、観戦、同一局面比較、一括実験から選択できる。DecisionDetailsの候補評価値はNoneとし、架空の評価を生成しない。

ArenaPlan／EvaluationRequestに既定falseのcapture_rank_traceを追加。順位ログを有効にした実験だけ、終局後の公開履歴と既知の配札から対象席の初期順位・残り順位を研究用に計算する。対戦中のStrategyに完全情報を渡さず、初期相手手札・未使用札はログに保存しない。ログ有無で同じ選択・得点・報酬になることをテストする。

各手のカード、手番・ラウンド、初期順位・残り順位、残り札の初期順位分布、ターン順位、得点を記録。ラウンドごとに内得点・加算得点・累積得点・順位枠・上下との差・中間指標を記録し、終局の順位枠・報酬を保持する。完了6役割順を配札内で平均し、独立配札を等重みで集計する。欠けた配札ブロックは集計しない。

6戦略を同時比較するため、Evaluationの参加上限とDesignPlanningInputの設定数上限を5から6へ拡張した。既存設定の意味・標準のログなし実行は維持する。

## 実験計画

Random、Greedy、ScoreAware、Heuristic、Zigzag、Reverse Zigzagの6設定。相手はRH（Random/Heuristic）とGS（Greedy/ScoreAware）。development offset5000–5003の共有独立4配札、全6役割順、288対局。Rolloutなし。時間上限60秒、事前見積7.2–28.8秒、登録見積は保守側28.8秒。

主比較はRandomを基準とする5対応報酬差×2構成と構成間差5の計15family、alpha .05。時間区分・順位・中間化は探索的な記述統計であり、多数の補助指標から有意なものを選ばない。4配札ではHoeffding区間と採用判定を保留する。最終評価用seedは使わない。登録済みPlanのHashは実測節へ記録する。

## 公開履歴と予測可能性

ある手で最強を出したなら、その後の本人の全提出札はそれより弱い必要がある。最弱なら逆。この必要条件を公開列だけで検査し、Zigzag／Reverseとの矛盾・両方可能を表示する。空・短い履歴は識別不能になりやすい。

規則を既知と仮定すれば次が強側か弱側かは手番から分かる。しかし公開列が矛盾しないことは、採用確率が高いという確率推定ではない。現在の残り手札が未知なので正確な次札も特定しない。出力のexact_next_cardはNone。

次フェーズの対策実験は、(1)通常相手、(2)規則だけ既知の相手、(3)公開列から推定する相手を、同じ配札・相手構成・予算で別条件として比較する。未知手札の実物や内部状態を対策へ渡さない。今回は検出器と設計までで、対策戦略本体や3条件の成績測定は未実装。

## UI・実行・Evidence

「Zigzag Strategy Lab」で計画案の準備、見積もり、Draft保存、事前登録、Hash付き開始、進捗・取消、SQLite履歴、JSON保存を操作する。構成ごとの6戦略比較、時間区分別順位、ラウンド／加算／累積得点、順位・中間指標、カード消費例と残り初期順位、公開パターンを表示する。

解析APIは `/api/zigzag/plans/{id}/{version}`、テンプレートはPOST `/api/zigzag/template`。実行は既存Design APIとdesign_cliを利用する。完了結果は明示ボタンで探索的Evidence Seriesへ関連付けられる。通常のゲーム画面・図鑑への戦略反映はレジストリを再利用する。

CLIはPYTHONPATH=backend/srcを設定し、`python -m strategy_arena.experiments.design_cli --plan experiments/presets/zigzag-pilot.json --database research-local/phase26/results.sqlite --register`、別操作で `--run`。参照結果は新しいDBまたは未使用ID・seedで実行する。既存Planの上書きは不可。

## 制限と次の課題

4配札の探索的パイロットで優劣は断定しない。カード消費図は最初の配札・席順の例で、集団全体の結果ではない。順位ログは保存量と後処理時間が増えるため既定無効。順位分布の信頼区間・対策戦略・観測モデルの尤度・自動採用は未対応。相手構成の偏り、同点の影響、より多い独立配札での再現性を次に調べる。

## 実測結果（2026-10-13）

登録Plan Hash：`0bb63983f7d3d2559009b19c23d08e97cff188a454ba5a660faac9ac4d6f3086`。4共有独立配札・2構成・6戦略・全6役割順、288対局を9.265秒で完了。見積範囲7.2–28.8秒・上限60秒以内。旧12実験行のpayload hashは全て維持。探索的Evidence Series `zigzag-pilot-evidence@1`へ明示的に関連付けた。最終seedは未使用。

| 相手 | 戦略 | 単独2位率 | 同点率 | 平均終局報酬 | 序盤ターン2位 | 終盤ターン2位 |
|---|---|---:|---:|---:|---:|---:|
| Random / Heuristic | Random | 45.8% | 0.0% | +0.375 | 30.8% | 32.5% |
| Random / Heuristic | Greedy | 16.7% | 4.2% | -0.458 | 49.2% | 15.8% |
| Random / Heuristic | ScoreAware | 20.8% | 0.0% | -0.458 | 39.2% | 25.0% |
| Random / Heuristic | Heuristic | 33.3% | 4.2% | +0.083 | 33.3% | 30.8% |
| Random / Heuristic | Zigzag | 37.5% | 4.2% | +0.167 | 14.2% | 45.0% |
| Random / Heuristic | Reverse Zigzag | 20.8% | 8.3% | -0.208 | 25.0% | 38.3% |
| Greedy / ScoreAware | Random | 41.7% | 4.2% | +0.333 | 21.7% | 37.5% |
| Greedy / ScoreAware | Greedy | 58.3% | 4.2% | +0.792 | 36.7% | 25.0% |
| Greedy / ScoreAware | ScoreAware | 41.7% | 4.2% | +0.333 | 28.3% | 28.3% |
| Greedy / ScoreAware | Heuristic | 16.7% | 12.5% | -0.250 | 26.7% | 39.2% |
| Greedy / ScoreAware | Zigzag | 33.3% | 12.5% | +0.250 | 12.5% | 54.2% |
| Greedy / ScoreAware | Reverse Zigzag | 29.2% | 8.3% | +0.000 | 15.8% | 54.2% |

Zigzagでは序盤ターン2位率が低く、終盤に上がる傾向がこの配札集合で見えた。しかし終盤ターン2位率の上昇は、最終単独2位率や平均報酬の改善を保証しなかった。RHでZigzagの平均報酬はRandomより約.208低く、GSでも約.083低かった。一方HeuristicよりはRHで約.083、GSで.500高かった。相手依存と配札依存があり、4配札から優劣を断定しない。Reverseも終盤ターン2位率が上がったが、最終成果は同じではなかった。

| 相手 | 戦略 | 各ラウンド終了時の厳密中間率（1→5） | 累積平均得点（1→5） |
|---|---|---|---|
| Random / Heuristic | Zigzag | 0.0% / 8.3% / 20.8% / 41.7% / 37.5% | 1.50 / 3.25 / 4.54 / 6.21 / 8.46 |
| Random / Heuristic | Reverse Zigzag | 0.0% / 29.2% / 12.5% / 33.3% / 20.8% | 0.00 / 1.79 / 4.12 / 7.42 / 9.62 |
| Greedy / ScoreAware | Zigzag | 0.0% / 0.0% / 12.5% / 20.8% / 33.3% | 0.00 / 1.46 / 2.83 / 4.00 / 6.33 |
| Greedy / ScoreAware | Reverse Zigzag | 0.0% / 4.2% / 12.5% / 20.8% / 29.2% | 1.04 / 1.04 / 2.33 / 4.54 / 5.92 |

H1の交互消費は構造テストで支持される。H2・H3はこのパイロットの記述傾向に限る。H4の累積中間化とH5の報酬改善は確定しない。H6は公開列との必要条件の診断だけで、対策相手との実証は未実施。次は追加の独立配札と別構成で再現性を確認し、その後に公開履歴だけの対策実験へ進む。配札数見積もりは既存Design/Evidenceの推薦で予算を確認し、無断で大規模化しない。

## 最終検証

Python全316件成功。最終の軽量履歴API追加後はZigzag対象7件を再確認。Vitest 28件成功、TypeScript型検査とViteビルド成功。Playwrightは既存35件成功、新規Zigzagの登録・解析・JSON・Evidence・通常対局テストを最終版で再実行。テンプレート取得やEvidence関連付けの非同期完了を適切に待つようテストを修正した。

履歴APIは順位ログ付きPlanのID・版だけを軽量取得し、一覧表示のたびに全過去Planの分析を再計算しない。バンドルサイズ警告とStarlette非推奨警告は既存どおり残る。Phase 26は未ステージ・未commit・未push。取得資料・DB・ログ・完全結果はresearch-local以下で公開しない。

## 変更ファイル一覧

- `README.md`
- `backend/src/strategy_arena/api/app.py`
- `backend/src/strategy_arena/experiments/arena.py`
- `backend/src/strategy_arena/experiments/design_lab.py`
- `backend/src/strategy_arena/experiments/evaluation_lab.py`
- `backend/src/strategy_arena/strategies/registry.py`
- `frontend/src/main.tsx`
- `backend/src/strategy_arena/experiments/zigzag_analysis.py`
- `backend/src/strategy_arena/experiments/zigzag_lab.py`
- `backend/src/strategy_arena/strategies/zigzag.py`
- `backend/tests/test_zigzag.py`
- `docs/phase26.md`
- `experiments/presets/zigzag-pilot.json`
- `frontend/e2e/zigzag.spec.ts`
- `frontend/src/features/zigzag/ZigzagPanel.tsx`
- `frontend/src/features/zigzag/zigzagModel.test.ts`
- `frontend/src/features/zigzag/zigzagModel.ts`
