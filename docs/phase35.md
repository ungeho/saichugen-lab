# Phase 35：Stopping Robustness & Runtime Validation Lab

## 1. 研究目的

固定した適応停止規則で、直接実行した意思決定時間と独立評価した終局報酬を比較する。早期停止・高速化0も有効な結果。停止規則の改良、閾値探索、実戦戦略への統合は対象外。

## 2. Phase 34からの変更

Phase 34は `7db4b3395ba0efc5745099f871cce8c9dbeecf74` として通常commit・push済み。今回は新Labのみを追加し、Phase 35は未ステージ・未commit・未pushで残す。既存のゲーム、合法手、報酬、戦略、Rollout、サンプラー、共通世界生成、停止判定を変更していない。Phase 34の最大経路・再構成・独立評価、Phase 33のログ・worker、SQLite・配札予約を再利用する。

## 3. 固定停止規則

初期16世界、追加16世界。Gapは最上位と次点の対応差 > 0.5。Uncertaintyは全競合の対応差 > 2×SE+0.05（SE未提供なら停止しない）。Fixedは指定上限まで実行。同値はrank昇順・suit昇順。基準版Phase 34とのAST一致、トレース有無での選択一致をテスト。規則版 `phase32-frozen-v1`、規則Hash `b774337d8b3525d0f254d7dc9611e43403fc8db77d2001b2ff962806e4126fe4`。

規則版・Hash・実験条件・ソースHash・測定環境をsnapshotと条件Hashに含める。旧Labの定義・保存行・条件Hashの意味を変更しない。

## 4. Development PilotとIndependent Validation

開発用はstage=development_pilot、partition=development、配札0〜999999。独立検証はstage=independent_validation、partition=validation、配札1000000〜1999999、主要128世界を必須にする。不一致stage／区分を拒否。最終評価区分は使わない。両stageの結果を合算しない。

まず開発用Planを登録・固定して動作と費用を確認し、次に検証Planを登録して別配札で実行した。検証開始後に条件・主要比較・停止規則・収集規則を変更していない。実時間測定中にテストや他のLabを同時実行していない（OSの他アプリの負荷は排除できない）。

| stage | 実験ID | 配札 | 局面 | 反復 | モデル | 上限 | 実験全体秒 |
| --- | --- | --- | ---: | ---: | --- | --- | ---: |
| 開発 | f5bdf91f-7463-4881-94a2-5ac63eac5e15 | 33000 | 4 | 2 | Random | 32 | 3.344 |
| 独立検証 | cbe8785e-6539-4703-b25e-0632c12f0136 | 1920000/1920001 | 2 | 2 | Random / Heuristic / ScoreAware | 128 | 44.640 |

開発条件Hash `d5d7d5fe1979c6d7233ba8e7cdb90d27a02fc566998116ed65c01ddf87b786c1`、Plan Hash `6eb3d9a7d336a04a351e4b5b4ca6d1f6bb1fcb69e8c9126c91384c4ce2779961`。

検証条件Hash `dd444678f6f76592298457cf268b03de0d3ff860519b6a528148d677238b4e98`、Plan Hash `53be2e3b7f0ce36a2d3fc0a64c91307337debedbc3ced51773a0507b1402404c`。

小規模の実装・手順検証であり、独立検証も確証的な性能保証ではない。

## 5. 局面収集

到達可能な合法軌跡から5収集元（Random、Heuristic、ScoreAware、Zigzag、Reverse Zigzag）の3席を収集。時点は序盤→中盤→最終ラウンド直前→最終ラウンド中の固定巡回（最終ラウンド開始も同じ巡回枠）。各時点内では実配札使用数を最優先し、得点層・収集元使用数・局面Hash順で選ぶ。結果を見て局面を追加しない。候補数の事前上限もこの巡回枠に合わせて計算する。

開発用はturn=[3,10,11,13]、各1局面。同点（Reverse Zigzag）、最低（Zigzag）、最高（Random）、厳密中間（ScoreAware）を収集した。これらは1配札由来なので独立数は1。

検証用は費用上限を優先してturn=[10,13]、各1局面。配札1920000の中盤・最低得点・Reverse Zigzag収集と、配札1920001の最終ラウンド中・最高得点・Heuristic収集を評価した。検証の序盤・直前・同点・厳密中間は未評価。開発用の層を独立検証の代わりにしない。

## 6. 独立配札管理

実配札Hash、局面Hash、観測Hash、事前局面一覧を保存。既存実験・Plan予約との実配札重複を拒否し、Phase 33/34の1900000/1900001/1910000/1910001は設定でも拒否。独立配札数は反復・モデル・予算を増やしても増えない。自身の手札・公開履歴等のObservationだけを選択処理へ渡す。実対戦の相手手札は渡さない。

サンプラーは既存の一様未公開札割当で、公開履歴・残り枚数と整合するが、相手の行動選択確率を学習した事後分布ではない。

## 7. 直接実行時間の測定設計

`perf_counter`の呼出直前に`process_time`の開始値も取り、既存selectを呼び出して返却直後にwall/CPU時間を記録する。select内の世界生成、軽量継続戦略初期化、候補評価、停止判定、標準トレース構築を含む。DB書込、JSON、UI、収集、照合用最大経路、独立参照・最終評価は直接計時の外。計時中のprogressコールバックは何もしない。測定開始条件の保存と進捗保存は開始前／返却後に行う。キャンセル・実行時間上限のcheckはselect内でも有効。

各測定にwall_seconds、cpu_seconds、実派生対局数・完了手番数・使用世界数・選択札・理由・停止判定回数（チェックポイント数）を保存。停止判定単体の処理時間は分離していないためnull。未完了測定のwall/CPU時間もnullにし、途中の時間を完成意思決定時間としない。派生対局数から秒数を推定して実測と呼ばない。

`counterfactual_policy_cost`はPhase 34の再構成コストで秒数null。`direct_measurement`は直接実測。`actual_research_compute_cost`は照合経路＋全方式の直接実行＋独立参照・最終評価。実験全体時間には収集・保存等も含む。照合経路等の研究用経過時間には進捗保存が含まれ得るため、直接計時と同じ測定範囲ではない。

## 8. 測定環境と実行順序

Python 3.12.14、Windows 11 build 26200、CPU Intel64 Family 6 Model 198 Stepping 2, GenuineIntel、論理CPU20。実験worker1・プロセス1・並列なし。CPU時間はプロセス単位であり、APIの他スレッド等の影響は完全には分離できない。

方式順は `runtime-order-v1` の専用seed35001から局面・モデル・反復・予算別にshuffleする。policy seedとは独立で、結果を見て順序を変えない。各実行の順序・順序内番号を保存。2反復は異なるpolicy標本も兼ねており、完全に同一選択経路だけを時間反復したものではない。

専用ウォームアップはなし。ただし照合経路・参照・最終評価を先に実行するのでキャッシュが温まり得る。cold-start性能とは呼ばない。CPU周波数、スケジューリング、キャッシュ、他アプリの負荷は排除できない。

## 9. 再構成との一致検証

各局面・モデル・反復ごとにPhase 34の最大Fixed経路を計算し、各方式・予算の結果を再構成する。その後、同じ整数seedで各方式を直接実行し、選択札・理由・使用世界数・派生対局数・手番数・候補評価まで照合する。不一致ならジョブをFailedとし、完成集約へ混ぜない。研究用の後続結果を直接selectへ渡さない。

開発24測定、独立検証36測定、計60測定すべて一致。時間は再現性対象外だが、同じ設定・seedの選択と独立評価値の再現性をテストする。

## 10. 主要128世界比較

独立検証の全事前局面で、反復平均→局面平均→実配札平均。負の時間差が観測上の短縮。主要はGap − FixedとUncertainty − Fixedの直接wall時間差・独立評価報酬差。以下の差だけで高速化や品質維持を確証しない。

| モデル | 方式 | wall秒 | Fixed時間差秒 | CPU秒 | 早期停止率 | 対局差 | 手番差 | 独立報酬 | 報酬差 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Random | Fixed | 0.216730 | 0.000000 | 0.214844 | 0% | 0 | 0 | -0.578125 | 0.000000 |
| Random | Gap-Adaptive | 0.170708 | -0.046022 | 0.171875 | 25% | -196 | -980 | -0.578125 | 0.000000 |
| Random | Uncertainty-Adaptive | 0.220524 | 0.003794 | 0.218750 | 0% | 0 | 0 | -0.578125 | 0.000000 |
| Heuristic | Fixed | 1.239157 | 0.000000 | 1.238281 | 0% | 0 | 0 | -0.796875 | 0.000000 |
| Heuristic | Gap-Adaptive | 1.265011 | 0.025853 | 1.257812 | 0% | 0 | 0 | -0.796875 | 0.000000 |
| Heuristic | Uncertainty-Adaptive | 1.100164 | -0.138993 | 1.089844 | 50% | -88 | -344 | -0.796875 | 0.000000 |
| ScoreAware | Fixed | 1.220082 | 0.000000 | 1.214844 | 0% | 0 | 0 | -0.625000 | 0.000000 |
| ScoreAware | Gap-Adaptive | 1.204153 | -0.015929 | 1.199219 | 0% | 0 | 0 | -0.625000 | 0.000000 |
| ScoreAware | Uncertainty-Adaptive | 1.205749 | -0.014333 | 1.199219 | 0% | 0 | 0 | -0.625000 | 0.000000 |

Heuristic Gapは計算量削減なしで約+25.9ms、ScoreAwareは両方式とも削減なしで約−14〜16ms。これらを性能改善・悪化と断定しない。Random GapとHeuristic Uncertaintyでは計算量削減も観測されたが、独立配札2件のみ。

## 11. 他予算比較

32/64/128/256世界を設定できる。副次予算は独立検証では無条件に追加実行していない。開発32世界は4局面で早期停止0、全方式の独立報酬平均0.6953125、Fixedとの差0。平均wall時間はFixed0.080534秒、Gap0.083771秒、Uncertainty0.079857秒。64・256世界の実験結果は未評価（全上限の直接照合は自動テストで実施）。異なるstageや予算を合算しない。

## 12. 停止率と計算量

検証では中盤最低得点局面のRandom反復0 Gapが16世界、Heuristic反復1 Uncertaintyが96世界、終盤最高得点局面のHeuristic反復0 Uncertaintyが96世界で停止。その他の適応測定は128世界まで到達。Fixedも常に128。上限ちょうどで条件成立しても早期停止削減には数えない。

独立検証の実研究コストは33,712派生対局・130,928手番、内訳は照合経路と直接実行の合計32,656対局・126,800手番、独立参照／最終評価1,056対局・4,128手番。直接実行と再構成の内訳はJSONに別保存。収集10対局・150手番は別計上。全体44.640秒、計算区間の合計43.570秒。

開発は8,928対局・67,680手番、収集5対局・75手番は別、全体3.344秒。事前上限は開発8,928対局、検証34,848対局。両方120秒以内の設定・実行であり、途中停止・打切りなし。

## 13. 独立評価報酬

policy、reference、finalは別domain-derived seed。最終評価は参照札選択にも直接意思決定にも使わない。最終標本は方式／反復／予算で共有し、比較件数を独立標本数に水増ししない。参照16世界・最終16世界。Self-Middleは対応Fixed接頭辞の直近中位率最大札。Regret = 同じ独立最終標本上の参照札報酬 − 選択札報酬。負値を保持する。参照札も最大予算札も真の最適手ではない。

検証の各モデルで全方式の選択一致率1、報酬差0。RandomのSelf差+0.03125／Regret−0.265625、Heuristic−0.046875／−0.171875、ScoreAware+0.078125／−0.21875。同等性の許容差は登録しておらず、報酬維持・同等性を証明しない。

## 14. 停止後の判断変化

検証の早期停止札はRandom Gapが♣5、Heuristic Uncertaintyが中盤♦6・終盤♠3。すべて同上限Fixed札と同じで、停止後128世界までのチェックポイントに札変化なし。独立報酬差0。停止後変化がなくても真の最適性は保証しない。追加対局数・手番数・最初の変更世界数（未変更null）を記録。上限を超えて256まで計算する実験は今回は行わない。

## 15. 層別頑健性

時点・得点配置・継続モデル・収集元・予算を分けて表示し、各層の独立配札数を出す。主分析は全事前局面であり、早期停止だけを選ばない。Matrixは未評価層をnot_evaluatedとし、0%を捏造しない。検証の中盤最低得点Reverse Zigzag層と終盤最高得点Heuristic層はそれぞれ1独立配札。収集元と時点・得点が交絡しており、相手モデル差と収集元効果を切り分けられない。

開発では全4時点を扱ったが独立検証の序盤・直前等は未評価。継続3モデルの結果を合算せず、他の未観測層への一般化を主張しない。

## 16. 統計的制限

主要独立単位は実配札。検証2件では報酬差の信頼区間を提示しない。既存の有界Hoeffding＋Bonferroniは最低独立配札数を満たす場合だけ、比較数上限10000で使用。時間は非有界かつ環境依存なので本実装は記述平均と対応差のみ、時間CIはnull。十分な配札数での事前固定クラスターブートストラップ等は今後の課題。

停止用SEは探索的判断で逐次有効区間ではない。実験全体を有利な統計値で任意停止しない。Cancel／TimedOut／BudgetExceeded／Failedは完了と区別し、未完了局面の完成集約を提供しない。途中開始した測定・研究チェックポイント・実行メーターを保存し、未知の時間や報酬を0にしない。

## 17. 実験直接リンク・API・CLI

戦略研究／中間順位・意思決定研究の新Lab。上位5カテゴリは維持。`/research/stopping-runtime?experiment=<ID>` で直接読込・条件復元・再読込・戻る進む。GETで実験を開始しない。他Lab ID／不正IDは404。

API namespace `/api/stopping-runtime`：`/estimate`、`/jobs`、`/jobs/{id}`、`/export`、`/start`、`/cancel`、`/design-draft`、`/evidence`。SQLite experimentsの専用kindで保存し旧行は更新しない。Planはsnapshot＋Hashで事前固定。DraftとEvidenceは既存の参照機能であり、異なる条件を対応差へ混ぜない。

```powershell
$env:PYTHONPATH="backend/src"
backend/.venv/Scripts/python.exe -m strategy_arena.experiments.runtime_cli --config research-local/phase35/development-config.json --database research-local/phase35/reproduction.sqlite --register
```

既定は見積もりのみ。実行は登録後に `--run <ID>`、JSON保存は `--output` で別途指定。配札予約済みのDBで同じ条件を新規登録し直さない。厳密再現は同じソース・設定・版で新DBを使用する（実時間は一致保証なし）。

新Labの64bit導出seedはSQLite・API・JSON・UIで十進文字列として扱う。選択内部だけでPython整数を使い、JavaScript Numberへ変換しない。safe範囲内の入力seedは整数設定。JSONダウンロードもAPI原文Blobを保存する。旧Labの表現やHashは変更しない。

パイロットと独立検証のDBはresearch-local/phase35/pilot.sqlite。通常の開発DBへ成果を混入させていないため、これらIDを画面で開くには当該DBを指定して起動する必要がある。

## 18. テスト・公開監査

重点検証：基準AST・トレース有無、全4上限の直接照合、seed再現・64bit文字列、測定範囲（進捗保存を除外）、実行順序、測定環境、規模上限、独立三標本、配札集約、保存・旧行不変、途中測定キャンセル、ID付きURL・他Lab拒否・JSONとUIのseed一致。Python 444件、Vitest 55件、Playwright 55件成功。TypeScript型検査・Viteビルド成功。既存のStarlette/httpx非推奨警告、色設定警告、大きなJSバンドル警告のみ。

開発実験前にDBファイルのSHA-256を記録。既存DBをコピーした上で実験し、開発開始前24実験行、検証開始前25実験行の一致を確認した。原資料・DB・ログ・測定生成物はresearch-local/以下だけに保存する。

## 19. 既知の制限

独立配札2件・最終評価16世界で一般化や同等性は判断できない。未評価層・副次予算多数。専用ウォームアップやcold-start比較、停止判定単体時間、時刻・CPU周波数校正、時間CI、全Lab共通の同時実行制限は未対応。workerはローカル、再起動でRunningはInterrupted。途中局面は実行メーターと開始記録を残すが、未完成測定のwall/CPU時間は未知。部分対局の未完了手番はメーターに含めない。

選択経路の照合研究を追加実計算するため、適応方式が速くても研究全体が同じだけ短縮されるとは限らない。通常のAI対局へ停止方式を組み込む変更は行っていない。

## 20. 次の研究課題

規則を固定して独立配札と未評価層を事前に拡張する。十分な配札で時間差のクラスターブートストラップ、計時専用の同一経路反復、ウォーム／コールド条件の分離、実行順序の完全バランスを検討する。停止規則を調整する場合は開発区分へ戻し別版・別Plan・未使用検証データを用いる。

## 変更ファイルと最終公開監査

- backend/src/strategy_arena/experiments/runtime_analysis.py：直接計時、再構成照合、独立評価の再利用、seed文字列、配札集約。
- backend/src/strategy_arena/experiments/runtime_lab.py：stage分離、Plan・見積もり・開始記録・中断保存・未評価層。
- backend/src/strategy_arena/experiments/runtime_cli.py：見積もり・登録・明示実行CLI。
- backend/src/strategy_arena/api/app.py：新namespaceとworker終了処理。
- backend/tests/test_runtime_lab.py：23件の重点テスト。
- frontend/src/features/runtime/RuntimePanel.tsx、runtime.test.ts：実測・頑健性Matrix・観測情報・環境・seed表示。
- frontend/src/features/workspace/registry.tsx、workspace.test.ts：22画面・中間順位8Lab・5上位カテゴリ。
- frontend/e2e/runtime.spec.ts、workspace.spec.ts：直接URL・原文JSON・64bit seed・全画面回帰。
- README.md、docs/phase35.md：日本語の案内と実測記録。

公開候補290ファイル、今回13ファイルを確認し秘密情報候補0。除去済み10件は追跡・ステージ・main履歴へ再混入せず、ignoreが有効。research-local/、PDF、取得画像・抽出資料、DB、ログ、実.envは公開対象外。作業開始時に記録した既存DBのSHA-256一致、旧実験行の不変性、ゲーム・戦略・Rollout・報酬・停止関数の差分なしを確認した。

PC1440px・モバイル390pxで表示・横幅・ブラウザエラーなしを確認。モデル×予算の未評価セル表示追加後に対象Playwright 2件、型検査・ビルドを再確認した。git diff --checkと新規8ファイルの空白検査成功。開発・検証実験時と最終バックエンドのソースHashも一致。Phase 35は未ステージ・未commit・未push。
