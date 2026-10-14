# Phase 37：Low-Overhead Runtime & Divergence Coverage

## 1. 研究目的

RQ1は通常実行を大きく乱さない計測経路、RQ2は独立配札を優先した判断分岐カバレッジ。停止アルゴリズムは開発・調整しない。時間測定と判断品質の結論を分ける。

## 2. Phase 36からの変更

Phase 36は `c20e0e33d632115f74a570f3b7cc07c764c7b95b` として通常commit・push済み。新Labやナビゲーションを作らず既存Runtime Noise & Decision Divergence Labを拡張した。新規lightweight_analysis.pyから既存select・再構成・独立三標本を再利用。Phase 37は未ステージ・未commit・未push。

revision=phase37を明示した新規Planだけ新経路を使用する。省略時はphase36で従来の計測経路を保持する。旧保存行・Plan Hash・Evidence参照・実験ID付きURLは変更しない。Dは1配札1局面、選択反復1を設定でき、配札数を増やす。

## 3. 固定停止規則

初期16世界・追加16世界。Gapは上位と次点の対応差 > 0.5、Uncertaintyは全競合の対応差 > 2×SE+0.05。Fixedは最大予算まで。rank/suit昇順のタイブレーク、サンプリング・共通世界生成・ゲーム・合法手・報酬・既存戦略・Rollout・停止関数は変更しない。Phase 36のselect/stopping ASTとの一致と全modeの再構成一致を検証。規則版phase32-frozen-v1、Hash `b774337d8b3525d0f254d7dc9611e43403fc8db77d2001b2ff962806e4126fe4`。

## 4. 低負荷計測設計

Baselineは標準selectを外側wall/CPUタイマーで計時。Lightweightは同じタイマーに加え、既存selection_observerでcheckpointを数えるだけ。内部の高頻度タイマー、候補評価の複製、乱数の追加消費を行わない。通知はstarted/completedと16世界ごとのcheckpointで、計数したcheckpoint数を既存traceと照合する。標準select自体の候補評価・trace構築は全mode共通。

Detailed ProfileはPhase 36の任意sys.setprofile経路。全イベント通知の摂動を含むので通常の停止処理オーバーヘッドとしない。Baseline/LWの停止関数単体時間は未計測null。直接wall・CPU、世界数、派生対局数、手番数、判定回数、カード・理由・日時・順序・一致結果を保存する。

DB書込は計時開始前／返却後。世界生成・初期化・候補評価・標準traceとmodeのobserver/profile設定解除は計時内。照合最大経路、warmup、測定、収集、参照・最終評価、実験全体は別コスト。warmupを測定分布へ混ぜない。

## 5. Baseline / Lightweight比較

同一局面・policy seed・モデル・予算・方式・反復のBaselineを対応相手とする。符号付き秒差、絶対値の秒差、(mode−Baseline)/Baselineの相対差、CPU差を保存。時間比の平均は各対応反復の比を平均し、平均時間の比とは区別する。Baseline時間0では相対差null。

実行順序はbalanced-runtime-v1。専用seedで初期配置を固定し、方式群と群内modeを循環させる。測定反復は方式数×mode数の倍数（2modeなら6、3modeなら9）を必須にし、各条件が全順序位置を一度ずつ訪れることをテスト。warmupの順序は別に記録し、warmup1回だけを完全バランスとは呼ばない。

時間分布は平均・中央値・min/max・標本SD・IQR・CV。CVは正のwall/CPU時間分布で解釈し、0近傍の符号付き対応差のCVは解釈しない。測定反復は独立配札数を増やさない。

## 6. 測定環境

2026-10-15日本時間。Python3.12.14、Windows11 build26200、CPU Intel64 Family6 Model198 Stepping2, GenuineIntel、論理CPU20。実験worker／プロセス各1、並列なし。perf_counter / process_time、Detailed Profile内はperf_counter_ns。日時はUTC ISOで保存。CPU時間はプロセス単位で他スレッド影響を完全には分離できない。

R開発は未使用開発配札37000、終盤1局面、Random、32世界、3方式×3mode、warmup1・測定9反復、順序seed37001。照合経路とwarmup後の測定でcold-start性能ではない。測定中にテストや他Labを並行実行していないがOS・他アプリを隔離していない。

## 7. 計測摂動・R実測

Rでは全mode・反復が同じ札、32世界・128派生対局・256手番・判定2回となり、Baselineとの選択・コスト一致を確認した。各mode n=9、独立配札1。

| 方式 | mode | 平均ms | 中央値ms | SD ms | IQR ms | CV | Baseline対応差平均ms | 相対差の対応平均 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Fixed | Baseline | 44.8129 | 44.0867 | 4.0044 | 3.7346 | 8.94% | 0.0000 | 0.00% |
| Fixed | Lightweight | 42.8183 | 43.4049 | 1.8367 | 1.2031 | 4.29% | -1.9946 | -3.89% |
| Fixed | Detailed Profile | 180.5113 | 177.4222 | 8.0179 | 4.9173 | 4.44% | 135.6983 | 305.50% |
| Gap-Adaptive | Baseline | 43.6462 | 43.8458 | 2.0636 | 3.0419 | 4.73% | 0.0000 | 0.00% |
| Gap-Adaptive | Lightweight | 43.6390 | 42.3512 | 3.7602 | 2.0994 | 8.62% | -0.0072 | -0.06% |
| Gap-Adaptive | Detailed Profile | 180.6085 | 178.5732 | 10.0756 | 8.9814 | 5.58% | 136.9623 | 314.78% |
| Uncertainty-Adaptive | Baseline | 43.7694 | 43.2988 | 2.9879 | 5.0326 | 6.83% | 0.0000 | 0.00% |
| Uncertainty-Adaptive | Lightweight | 42.6868 | 42.6800 | 1.7865 | 1.4865 | 4.19% | -1.0826 | -2.06% |
| Uncertainty-Adaptive | Detailed Profile | 180.2140 | 175.4752 | 11.2322 | 12.9012 | 6.23% | 136.4446 | 312.43% |

Lightweightの最終測定は、Fixed：対応差平均-1.995ms、相対差平均-3.89%、反復範囲-15.73〜+12.48%。Uncertainty-Adaptive：対応差平均-1.083ms、相対差平均-2.06%、反復範囲-11.43〜+14.05%。Gap-Adaptive：対応差平均-0.007ms、相対差平均-0.06%、反復範囲-5.85〜+14.48%。負の時間差も環境ノイズを含み、計数処理が高速化したという因果的結論にはしない。Detailed Profileは約180msで大きな摂動がある。平均が小さくても各呼出の摂動が小さいとは保証できない。OS・キャッシュ・CPU周波数の寄与は未解明。

Rの最大・実派生対局11,648、23,296手番、実験全体8.953秒。照合経路・warmup・測定は結果JSONに別保存。収集5対局・75手番は別。各Planは取得前に40,000対局・120秒以内で固定した。

## 8. 判断分岐カバレッジ

D独立検証は新規検証配札1940000〜1940003。Phase 36の2配札／4局面／2選択反復から、4配札／4局面／1選択反復へ変更し独立配札を優先した。継続モデルRandom/Heuristic/ScoreAware、主要128世界、参照16・最終16世界。最終保留seedは使用しない。

5収集元の合法な軌跡から固定時点巡回で選ぶ。各時点内では実配札・得点層・収集元使用数を均しHash順。結果を見て局面を選ばない。実配札Hash／局面Hash／観測Hashを保存。実際の相手の隠し札を選択側へ渡さず、本人のObservationだけでサンプリングする。

| 配札 | turn / 時点 | 得点配置 | 収集元 |
| --- | --- | --- | --- |
| 1940003 | 3 / 序盤 | 同点 | ScoreAware |
| 1940002 | 10 / 中盤 | 最低 | Reverse Zigzag |
| 1940000 | 11 / 直前 | 厳密中間 | Zigzag |
| 1940001 | 13 / 最終ラウンド中 | 最高 | Random |

Heuristic収集由来の評価局面と最終ラウンド開始は未評価。時点・得点・収集元が交絡し、各層は1独立配札だけなので層別一般化をしない。

## 9. 独立配札数・事前計画

全設定を実行前にJSONで固定してR開発→D開発→D独立検証を順次実行。D開発は配札37100・1局面・Random・128世界・選択1反復、640対局、全体0.390秒。D検証は14,880対局・112,800手番、全体53.641秒。収集は20対局・300手番を別計上。全実験が120秒以内に完了し、途中打切りなし。最終レビューでRのPlanがD用の主要比較名を継承していたため、R専用の主要比較Lightweight − Baselineを明記し、同じ開発設定で新Planを事前登録して再測定した。旧R結果・旧Planは保持し合算しない。DのPlan・結果は変更していない。再測定前のバックエンド全ソースもresearch-local/phase37/pre-plan-metadata-source/に保持した。再測定を含む派生対局総数は38,816。

| 実験 | ID | 条件Hash |
| --- | --- | --- |
| R開発 | 545a970c-5af0-4f36-a50c-1c9a3fcdadab | e635577a68da1160a8bdac9fbe7f2101ecd42bae83fa119303fc4539bb26cdba |
| D開発 | 1006d53b-11cd-4d6e-8dae-869489b070f1 | 0b1c4dc0d053331782a69b1d283c57477f6986e1868d9c9b5da325560882b3c9 |
| D検証 | 0a472a77-98d9-4525-ab5e-ac661a6b1a0c | e715c40a66d8d1073a2b3ffe92bfcf88d64f8947b01b3909085f63f4579ae5c8 |

R Plan Hash `1dbc4ad5b94a468f30b930b0772a4e99017d91c60f70646e14f3ef286cf83bca`、D開発 `1505b5119fc843c3dc967d4287a440ef93cd1d9e59b5d7946157c810e20c4bbf`、D検証 `099b52f2ae04fb64f4bba3e14adb20fe1d397541c943cb2eb878867a66cd87eb`。基準commit、ソースHash、規則版、revision、mode、順序仕様、配札と予算、仮説をsnapshotに保持。

## 10. 判断分岐率

定義は同じ局面・モデル・選択seed・最大予算のAdaptive札 != Fixed札。分母は全4事前局面・各1選択反復（各モデル・方式で4判断）。反復→局面→実配札の等重み平均。分岐例だけを抽出した比率を全体率としない。

| モデル | 方式 | 分岐 / 全判断 | 発生配札 / 独立配札 | 分岐率 | 独立報酬差 | Self差 | Regret |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| Random | Gap-Adaptive | 0 / 4 | 0 / 4 | 0% | 0.000000 | 0.265625 | -0.046875 |
| Random | Uncertainty-Adaptive | 0 / 4 | 0 / 4 | 0% | 0.000000 | 0.265625 | -0.046875 |
| Heuristic | Gap-Adaptive | 1 / 4 | 1 / 4 | 25% | 0.343750 | 0.328125 | -0.281250 |
| Heuristic | Uncertainty-Adaptive | 0 / 4 | 0 / 4 | 0% | 0.000000 | -0.015625 | 0.062500 |
| ScoreAware | Gap-Adaptive | 0 / 4 | 0 / 4 | 0% | 0.000000 | 0.468750 | 0.000000 |
| ScoreAware | Uncertainty-Adaptive | 0 / 4 | 0 / 4 | 0% | 0.000000 | 0.468750 | 0.000000 |

分岐は配札1940002・中盤最低得点・Reverse Zigzag収集のHeuristic Gapで1件。16世界で♠3、128世界Fixedは♦7。研究用接頭辞の最初の選択変化は48世界。停止時Gap0.5625、対応SE約0.491331、合法手7・残り5ターン。独立最終16世界での対応報酬差は+1.375。全4配札平均では+0.34375。

停止後の情報を選択へ戻していない。Gapの派生対局差は配札平均−196、早期停止率25%。他5比較は分岐・早期停止・報酬差0。分岐例が得られたことや正の報酬差をGapの優越性と解釈しない。

## 11. 分岐の見逃し可能性

配札ごとのpositions／decisions／divergent_decisions／any_divergence／rateを保存し、主比較と同じモデル・方式・予算ごとに表示する。同一配札内の局面・反復・モデルを独立な二項試行として扱わない。

0発生の比較でも4配札では不確実性が大きい。各独立配札で同じ発生確率pという仮定例では、0件となる確率は(1−p)^4。p=10%なら65.61%、p=25%なら31.64%、p=50%でも6.25%。これは実際の頻度の推定・信頼区間ではなく、時点などで確率が異なる実験へそのまま適用しない。

少数配札のためevent_intervalはnull。分岐0を損失リスク0、報酬差0を同等性証明としない。Fixed自身との恒等比較には見逃し例を付けない。Heuristic Gapは1発生なので0件用の例を適用しない。

## 12. 判断品質の独立評価

既存のPolicy Selection／Reference Selection／Final Evaluationの三標本と役割別seedを維持。最終評価は選択へ使わない。参照札は有限標本で真の最適手ではない。Self-Middleは対応Fixedの接頭辞で直近中位率が最大の札。符号付きRegret=独立最終標本上の参照札報酬−選択札報酬、負値を保持。

モデル、予算、stage、収集元の異なる結果は無条件に合算しない。全事前局面での報酬差を主分析にし、分岐した1例だけの+1.375は探索的な説明と区別する。新しいsummaryでは収集元別も独立配札単位で記録する。

## 13. 統計的制限

時間は1配札・9反復で、CIや因果的な計測負荷推定を提供しない。順序を完全バランスにしても環境ノイズは残る。CPU時間は量子化の影響もある。CVは正の時間分布だけを解釈し、0近傍・符号付き差のCVを効果指標にしない。

Dは4独立配札・最終16世界。主比較は128世界のGap／Uncertainty、モデル別に記述。既存の有界Hoeffding＋Bonferroni（比較数上限10000）は最低独立配札数を満たす場合のみ、今回報酬差CIは未提供。見逃し例は共通pの独立配札仮定を明示し、モデルを足して独立数12とはしない。

有利な結果が出るまで任意停止・局面追加しない。配札、1配札1局面、選択反復、モデル、予算、対局数・時間上限を事前固定。取消／予算超過／時間超過／失敗では未完了を完了集約へ補わない。

## 14. UI・API・CLI・SQLite

既存URL `/research/runtime-divergence?experiment=<ID>`、API `/api/runtime-divergence`、noise_cli、SQLite experimentsのkindを維持。新Labや上位ナビは追加していない（23画面・5カテゴリ）。旧版を読め、新版はrevisionとPlan versionで区別。既存実験行・Plan Hash・Evidence参照を上書きしない。

UIでBaseline / Lightweight / Detailed Profile、時間分布とBaseline対応差・相対差、順序・warmup・環境、配札単位の発生・見逃し例を確認できる。旧版にない配札別集約は未記録と表示。URL直接表示・再読込・戻る進む・条件復元を維持し、GETだけでは実行しない。他Lab ID／不正IDは拒否。

64bit導出seedはSQLite・API・JSON・UIで十進文字列。select内だけPython整数。JSON保存はAPI原文Blobで精度を保つ。

```powershell
$env:PYTHONPATH="backend/src"
backend/.venv/Scripts/python.exe -m strategy_arena.experiments.noise_cli --config research-local/phase37/r-development-config.json --database research-local/phase37/reproduction.sqlite --register
```

既定は見積もり、登録後に `--run <ID>` を別途明示。配札予約済みDBで再登録しない。厳密再現には同じソース・設定・版を使用する。時間一致は保証しない。パイロットはresearch-local/phase37/pilot.sqliteに保存し、最終R再測定はpilot-final.sqliteに保存し、通常開発DBには追加していない。

## 15. テスト・公開監査

基準AST、全mode選択・対局／手番一致、全順序位置バランス、warmup分離、旧版行の不変性、配札集約・分母・見逃し仮定、seed、保存・中断・既存URLを検証。Python全476件・Vitest57件・Playwright全59件成功。型検査・Viteビルド成功。既存のStarlette/httpx非推奨、色設定、大きなJSバンドル警告のみ。

既存DBのハッシュを作業前に記録し、コピーで実験。R前の旧29行、D開発前30行、D検証前31行の不変性を確認。DB・ログ・取得資料・生成データはresearch-local/だけに保存する。公開監査で除去済み10パス・秘密情報候補を確認する。

## 16. 既知の制限

Rは1局面の測定で、低負荷差を一般化できない。Lightweightで停止関数単体時間は測らず、Detailed Profileは大きな摂動を持つ。Dは4配札だけで層別は各1配札、検出力は不足。Dの32/64/256副次実験は未実施。時間見積もりは未校正で、実行中も120秒・最大派生対局を確認する。

1Lab1workerで全Lab共通の制御ではない。取消は協調方式、再起動時はInterrupted。部分結果は開始記録・チェックポイント・実行メーターを保持し、未計測時間を0としない。多数履歴の登録／読込速度、統計的な停止規則改良、実戦用AI統合は対象外。

## 17. 次の研究課題

低負荷経路を複数局面・異なるCPU負荷で検証し、反復と環境制御を事前計画する。独立配札をさらに増やす際も1配札1局面を優先し、層別の不足を事前に記録する。今回の分岐例を後付けで検証標本へ再追加しない。十分な独立配札で配札単位の区間推定を検討する。停止閾値を変える場合は開発区分・別版・未使用検証へ戻す。

## 18. 変更ファイルと最終確認

変更はREADME.md、noise_lab.py、NoisePanel.tsx、noise.test.tsの4件、新規lightweight_analysis.py、test_lightweight_lab.py、lightweight.spec.ts、本書の4件。最終Planメタデータ訂正後も関連Pythonテストを再実行した。公開監査は公開候補302件・変更8件、除去済み10パスは無追跡・ignore有効、秘密情報候補0件。git diff --checkと新規ファイルの空白検査を実施。Phase 37のステージ・commit・pushは行わない。
