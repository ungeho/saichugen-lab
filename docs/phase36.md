# Phase 36：Runtime Noise & Decision Divergence Lab

## 1. 研究目的

RQ1は同じ探索量での実時間変動、RQ2はAdaptiveとFixedの選択が異なる場合の独立終局報酬差。時間測定と判断品質を別系列・別Plan・別配札で評価する。停止閾値の調整や実戦戦略への組込みは対象外。

## 2. Phase 35からの変更

Phase 35は `007e6c816882920d7a23fcc94c09d2619fe3d9f3` として通常commit・push済み。Phase 36は未ステージ・未commit・未push。新しいnoise_analysis / noise_lab / noise_cliを追加し、既存select、最大経路の再構成、独立三標本、worker、保存・配札予約を再利用する。旧Labの意味、保存行、条件Hashを変更しない。

## 3. 固定停止規則

初期16世界・追加16世界、Gapは最上位と次点の対応差 > 0.5。Uncertaintyは全競合への差 > 2×SE+0.05、SEが不足なら停止しない。Fixedは指定上限まで実行。タイブレークはrank・suit昇順。Phase 35のselect AST、計測有無での選択・候補評価・理由の一致を検証。規則版phase32-frozen-v1、規則Hash `b774337d8b3525d0f254d7dc9611e43403fc8db77d2001b2ff962806e4126fe4`。ゲーム、合法手、報酬、既存戦略、Rollout、サンプラー、共通世界生成、停止関数は変更しない。

## 4. Series Rの設計

開発区分だけで同一局面・同一policy seed・同一モデル・同一予算を反復する。互換repeats=2は固定し、実時間反復数はmeasurement_repeats（2〜10）で別指定。policy seedは反復中に変えない。各方式の選択札・候補評価・探索量が再構成と一致することを毎回確認する。

最大Fixed照合経路を先に1回計算。その後、各モデル／予算でwarmup（0〜2反復）を実行し、measurementを実行。warmupも通常群／profile群の全方式を実行し、実対局数と時間を研究コストへ計上する。通常群とprofile群の混合は禁止。方式×計測モード順を専用seedでshuffleし、順序内番号・日時を保存する。

同一入力内でwall／CPUの平均、中央値、最小、最大、標本SD（ddof=1）、IQR（線形分位点）、CV=SD/平均を記述。平均0等でCVが不適切ならnull。測定反復を独立配札として数えず、局面・モデル・上限・計測モードを合算しない。Rでは参照カード選択・最終報酬評価は実施しない。

## 5. Series Dの設計

開発確認と独立検証を別Planで登録。主要128世界、Gap−FixedとUncertainty−Fixedの判断分岐率・独立評価報酬差。32/64/256は副次条件として設定可能だが今回追加実行していない。R用warmupとprofileはDでは禁止。

各局面・モデル・選択反復で最大Fixed経路を一度計算し、既存規則でAdaptiveの停止を再構成する。各上限の候補値・選択・理由・コストが直接実行と一致することは既存Phase 34/35テストと新規テストで確認する。Dは直接実時間を主アウトカムとして測定せず、再構成コストの時間はnull。研究の最大経路・独立参照・最終評価時間は別計上する。

## 6. 測定環境

2026-10-15（日本時間）。Python 3.12.14、Windows 11 build26200、CPU Intel64 Family 6 Model 198 Stepping2, GenuineIntel、論理CPU20。worker1・プロセス1・並列なし。wallはperf_counter、CPUはprocess_time、停止関数内の計時はperf_counter_ns。測定日時はUTC ISO文字列で保存。CPU時間はプロセス単位で、APIの他スレッド等の影響を完全に分離できない。

Rの計時は既存select呼出前から返却後まで。世界生成・軽量戦略初期化・候補評価・停止判定・標準トレース構築を含む。profile群ではprofile設定／解除も含む。DB書込は開始前／返却後、収集・照合用最大経路・JSON・UIは別。実験中にテストや他Labを並行実行していないが、OSや他アプリを隔離した環境ではない。

専用順序seed36001、measurement3反復、warmup1反復を取得前に固定。最大経路の事前計算とwarmupがあるのでcold-start性能ではない。順序とwarmupの因果効果はこの設計だけでは識別できない。

## 7. 時間ノイズ

R開発は配札36000の終盤1局面、Random、32世界。全方式32世界・128派生対局・256手番・停止判定2回で同じ札。通常群の同一探索量における分布を示す。独立配札数1、各n=3。

| 方式 | 平均ms | 中央値ms | 最小ms | 最大ms | SD ms | IQR ms | CV |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Fixed | 42.1290 | 41.9066 | 41.2848 | 43.1955 | 0.9746 | 0.9553 | 2.31% |
| Gap-Adaptive | 43.4020 | 43.8997 | 40.4202 | 45.8860 | 2.7667 | 2.7329 | 6.37% |
| Uncertainty-Adaptive | 41.5457 | 41.6187 | 41.0024 | 42.0159 | 0.5107 | 0.5067 | 1.23% |

この1局面での観測であり、探索量削減の結果ではない。OSスケジューリング、CPU周波数、キャッシュ等の寄与は未解明。方式間の微小差を停止判定の因果的オーバーヘッドや高速化と断定しない。

## 8. 停止判定オーバーヘッド

任意のmeasure_stopping=trueでは通常群に加えてprofile群も実行する。workerスレッドのsys.setprofileで既存stopping関数のcall/return間だけを集計。既存profileがある場合は上書きせず拒否し、例外・キャンセルでも元に戻す。停止判定回数とチェックポイント数を照合する。

profileのコールバック自体は他のPythonイベントでも呼ばれるため、wall時間全体に大きな摂動がある。停止関数内計時はcaller側のgap_statistics・トレース構築を含まないが、関数内generator等の通知負荷は含み得る。未計測の通常群では判定時間null。判定時間をwallから差し引いた値を実際の高速化としない。

| profile群の方式 | wall平均ms | 判定総時間平均μs | 判定回数 | 判定時間/wall平均比 |
| --- | ---: | ---: | ---: | ---: |
| Fixed | 169.8823 | 3.5667 | 2 | 0.00210% |
| Gap-Adaptive | 173.2543 | 4.6333 | 2 | 0.00267% |
| Uncertainty-Adaptive | 180.5857 | 13.9000 | 2 | 0.00768% |

profile群は通常群の約4倍のwall時間で、停止関数内の数μsだけでは差を説明できない。通知機構の負荷と環境要因を含む。これは通常実行の停止判定オーバーヘッドの推定値ではない。より局所的な計測方式は今後の課題。

## 9. 判断分岐の定義

同じ局面・モデル・選択seed・最大予算でAdaptiveの札 != Fixedの札。decision_divergenceへ両札、使用世界数、停止理由、選択seed、最初の選択変化チェックポイント、独立報酬差、停止時Gap／対応SE、合法手数、残りターン数を保存。局面レコードに配札Hash・得点配置・時点・収集元も保存する。

分母は事前選択した全評価対象局面。選択反復を局面内で平均し、局面を配札内で平均し、独立配札を等重みで平均する。分岐例だけを主分析しない。反復やモデルを独立配札に見立てない。Fixed自身との分岐は恒等的に0で、Adaptive比較の証拠にはしない。

## 10. 独立評価

既存のSelection／Reference Selection／Final Evaluationの独立三標本を維持。参照16世界・最終16世界。上限・方式・反復で同じ最終カード別評価表を共有し、比較件数を実標本数に水増ししない。Self-Middleは対応Fixed接頭辞の直近中位率最大札。符号付きRegret = 最終標本上の参照札報酬 − 選択札報酬で負値を保持。参照札は有限標本で真の最適手ではない。

停止後の追加研究サンプルをAdaptiveの判断に戻さない。分岐0は損失リスク0ではなく、報酬差0は同等性証明ではない。最終評価標本で選択seedや閾値を調整しない。

## 11. 配札・seed管理

開発配札0〜999999、検証1000000〜1999999。Final Holdout区分は使わない。Rは開発系列のみ。Dの独立検証には128世界を必須にする。既存実験・Plan・予約との実配札Hash重複を拒否し、既観測のPhase 33〜35配札も明示拒否。局面Hash・観測Hash・事前局面一覧を保存する。

各Planのseries・stage・条件・規則版／Hash・ソースHash・測定環境・順序仕様・上限をsnapshotに入れ、Plan Hashと条件Hashを保存する。64bit導出seedはSQLite・API・JSON・UIで十進文字列、select内だけPython整数。JavaScript Numberへ変換しない。

合法な収集軌跡のみ、5収集元と3席から選ぶ。序盤→中盤→直前→最終ラウンドの固定巡回、各時点内で実配札使用数・得点層・収集元使用数を均し、Hash順で固定。結果を見て有利な局面を追加しない。未評価層はnot_evaluated、0%を捏造しない。自身の手札・公開履歴だけを選択側へ渡し、実際の相手の隠し札を使わない。

## 12. 開発パイロット結果

全3Planの設定を実行前にJSONで固定し、R→D開発→D独立検証の順に実行。各120秒、最大40,000派生対局。上限到達・キャンセル・未完了なし。

| 実験 | ID | 独立配札 | 局面 | 設定 | 対局数 | 全体秒 |
| --- | --- | ---: | ---: | --- | ---: | ---: |
| R開発 | 598c7b07-3c1f-4ee8-be65-9433d167ff4f | 1 | 1 | Random・32世界・warmup1・測定3・通常/profile | 3200 | 2.969 |
| D開発 | fb08f1a5-5ffd-4e64-99d2-c5e1bae87834 | 1 | 2 | Random・128世界・選択2反復 | 2880 | 1.141 |
| D独立検証 | 6199f23f-b3ce-40e5-9950-f2c033d5a2ee | 2 | 4 | 3モデル・128世界・選択2反復 | 26784 | 100.469 |

R: 条件Hash `2dae1a9f895a2b14a04e39db32b194064aea528193984edda43ede180173db4e`、Plan Hash `595e56626f2f74cb65f3261b02c3d120be311f6e7abf295a631582b971e7a8ae`。

D開発: 条件Hash `aa0c6bea8614e70852553fd160f624fae90e0926edc02cf4203d230be27dc719`、Plan Hash `cacf832b189569fb18930eb0b2c9cca4339e60b9b667d20cc8e4f3cda125fd96`。

Rの照合128対局・256手番、warmup768対局・1,536手番・0.646秒、測定2,304対局・4,608手番・1.952秒、総計3,200対局・6,400手番。収集5対局・75手番は別。D開発は配札36100の直前／終盤2局面、分岐なし、2,880対局・9,216手番。分岐例を見つけるための追加探索は行わない。

## 13. 独立検証結果

D独立検証: 条件Hash `209e7e3e2a210af8e99cfd39c0fbd568042f79890ef1db41f6336faed1981a87`、Plan Hash `cd6e54deca130b6133bbf736d4a234072ea2070fea24b3ba1130963f4170999d`。検証配札1930000/1930001、2独立配札・4局面・選択2反復・3モデル。事前上限26,784対局、実26,784対局・203,040手番、全体100.469秒。内訳最大選択経路23,808対局・180,480手番・88.674秒、参照／最終評価2,976対局・22,560手番・11.155秒。収集10対局・150手番は別。

| 時点（turn） | 配札 | 得点配置 | 収集元 |
| --- | --- | --- | --- |
| 序盤3 | 1930001 | 同点 | ScoreAware |
| 中盤10 | 1930000 | 最低 | Heuristic |
| 直前11 | 1930001 | 最高 | Reverse Zigzag |
| 最終ラウンド13 | 1930000 | 厳密中間 | Zigzag |

各モデル／方式の分母は全4事前局面（各2選択反復）、独立配札数2。3モデルともGap・Uncertaintyの分岐率0、独立報酬差0。分岐したカードは観測されず、分岐例だけの後付け分析は行わない。

| モデル | Gap分岐率 | Uncertainty分岐率 | 独立報酬差 | Self-Middle差 | 符号付きRegret | Gap早期停止率 | Uncertainty早期停止率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Random | 0% | 0% | 0 | 0.5078125 | -0.2578125 | 25% | 25% |
| Heuristic | 0% | 0% | 0 | 0.0625000 | 0.0156250 | 0% | 0% |
| ScoreAware | 0% | 0% | 0 | 0.3359375 | -0.0703125 | 0% | 0% |

Randomの早期停止は中盤最低局面の♣Kで、Gapは反復0が16／反復1が32世界、Uncertaintyは16／96世界。停止後128世界までFixed札の変化なし。その他モデルで早期停止なし。全事前層の報酬差・分岐率は0だが、各得点／時点層は1独立配札しかなく一般化しない。収集元も時点・得点配置と交絡し、収集元効果を切り分けない。Random収集由来の評価局面や最終ラウンド開始は未評価。

## 14. 統計的制限

Rは1配札の同一入力の3時間反復で、配札推論をしない。時間CIや因果的ノイズ分解は未提供。profile群を通常群へ混ぜず、warmupも測定分布に混ぜない。

Dは反復→局面→配札の集約、モデル・上限・stageを合算しない。主要128世界のGap／Uncertainty差、他層・予算は探索的。最低独立配札数を満たす場合のみ既存有界Hoeffding＋Bonferroni（比較数上限10000）を使用。今回は2配札で報酬差CIを提供しない。停止用SEは逐次有効保証ではない。任意統計停止をせず、Cancelled／TimedOut／BudgetExceeded／Failedと完了を分け、未完了局面の主集約を提供しない。途中記録・実行メーターは保存し未測定時間を0にしない。

## 15. 実験直接リンク・API・CLI

Navigation Registryの戦略研究／中間順位・意思決定研究に新Labを登録。上位5カテゴリ維持。`/research/runtime-divergence?experiment=<ID>` で直接読込、再読込、戻る進む、条件復元。他Lab ID／不正IDは404。GETや新規系列プリセット選択だけで実験を開始しない。

API namespace `/api/runtime-divergence` のestimate / jobs / jobs/{id} / export / start / cancel / design-draft / evidence。専用kindのSQLite experimentsを使い旧行を更新しない。Evidence参照は異条件の局面結果を対応差へ合算しない。

```powershell
$env:PYTHONPATH="backend/src"
backend/.venv/Scripts/python.exe -m strategy_arena.experiments.noise_cli --config research-local/phase36/r-development-config.json --database research-local/phase36/reproduction.sqlite --register
```

既定は見積もりのみ、実行は別途 `--run <登録ID>`、JSON保存は `--output`。同じDBでは配札再予約を拒否。厳密再現には記録されたソース・設定・版を用い、実時間の一致は保証しない。パイロットDBはresearch-local/phase36/pilot.sqliteであり、通常の開発DBには追加していない。当該IDを画面で読む場合はこのDBを指定して起動する。

## 16. テスト結果・修正記録

停止規則AST・計測有無・再構成照合、profile復元、warmup／測定分離、時間分布、CV、固定seed・順序、D分母、独立三標本、seed文字列、保存・旧行不変、途中キャンセル、URL・原文JSONをテスト。Python全463件・Vitest57件成功、型検査・ビルド成功。Playwright全57件成功。既存のStarlette/httpx非推奨、色設定・大きなJSバンドル警告のみ。

回帰検証で新LabのStudyConfigというimport名が既存探索品質APIを上書きしていたため、NoiseConfig / NoiseJobsの別名importに修正した。パイロットはCLIで当該APIを経由しておらず、解析・選択・停止・乱数・評価には影響しない。修正後に既存探索品質・Theory・Hybridを含む全体を再検証する。

パイロットの環境prior_computationに、継承した「専用ウォームアップなし」という旧文言が残っていた。構造化されたwarmup=true／warmup_repeats=1とphase=warmupの実行記録が実態を示す。記録済みPlan・Hash・旧文言を上書きせず、この訂正を残す。新規Planの説明文はRの実際のwarmupとDの非計時を示すよう修正した。

パイロット時点のbackend全ソースとハッシュをresearch-local/phase36/pilot-backend-source/に保全。最終ソースとの差分はAPI型別名修正とPlan環境文言（api/app.py、experiments/noise_lab.py）の2件で、noise_analysis.py、既存select・ゲーム・サンプラー等の計算処理は同一。旧条件Hashを新文言で再解釈しない。

## 17. 公開監査

原資料・DB・ログ・生成結果はresearch-local/にだけ保存。作業前のDBハッシュを記録し、旧実験行26件→R追加前、27件→D開発前、28件→D検証前が不変であることを確認。除去済み10パス、秘密情報・ローカルDBの公開対象混入を最終監査する。Phase 36は未ステージ・未commit・未push。

## 18. 既知の制限

小標本、時間ノイズ原因の因果分離なし、profileの大きな摂動、通常群の停止判定単体時間未計測、cold-start比較なし、順序効果・warmup効果を分離した実験なし。Dの64/256/32副次実験は未実施。分岐が観測されていないため分岐時の報酬損失を評価できない。

全Lab共通の実行制限はなく、同一Labのworker1件ずつ。再起動中断・取消・予算／時間上限を完了と混ぜない。停止は協調方式で、未完了1対局の部分手番はメーター未計測。登録前時間見積もりは未校正で、今回D実100.469秒は上側見積81.352秒より遅かったが120秒以内。実行時にも上限を確認する。

## 19. 次の研究課題

同じ停止規則で未使用配札を増やし、分岐率と報酬差を事前計画で評価する。分岐例探索は開発区分に留め、独立検証の分岐率と混ぜない。より局所的で低負荷な停止判定計測、温冷条件を分けた実験、完全バランス順序、十分な測定反復・独立配札での時間クラスターブートストラップを検討する。閾値調整は別版・別開発Planと未使用検証へ戻す。

## 変更ファイル一覧

- backend/src/strategy_arena/experiments/noise_analysis.py：Rの計測・分布、任意profile、Dの分岐記録・全局面集約。
- backend/src/strategy_arena/experiments/noise_lab.py：別系列Plan、設定上限、保存の拡張。
- backend/src/strategy_arena/experiments/noise_cli.py：見積もり・登録・明示実行。
- backend/src/strategy_arena/api/app.py：別名型で新APIを登録し旧APIとの衝突を回避。
- backend/tests/test_noise_lab.py：19件の重点テスト。
- frontend/src/features/noise/NoisePanel.tsx、noise.test.ts：系列切替、時間分布・分岐・環境・文字列seed。
- frontend/src/features/workspace/registry.tsx、workspace.test.ts：23画面・中間順位9Lab・上位5カテゴリ。
- frontend/e2e/noise.spec.ts、workspace.spec.ts：R/D・URL・原文JSON、全Labの履歴モックによるテスト分離。
- README.md、docs/phase36.md：日本語案内・設計・実測・訂正記録。

テストDBを繰り返し再利用すると登録処理の履歴走査が5秒を超え、古いテストの既定待ちに達した。DBを削除せず新しい隔離DBで最終検証する。最近の実験テストも新Lab一覧を含めて明示モックし、実履歴の件数・表示順に依存しないようにした。多数履歴での登録・読込速度の改善は今回の対象外。

最終確認：Python全463件、Vitest57件、Playwright全57件、TypeScript型検査・Viteビルド成功。PC1440px／モバイル390pxでSeries R/Dの実結果・横幅・ブラウザエラーなしを確認。公開候補298ファイル・今回13ファイル、秘密情報候補0。除去済み10パスの追跡・ステージ・main履歴への再混入なし、ignore有効。作業開始時の既存DB1313件のSHA-256を保持。git diff --checkと新規8ファイルの空白検査成功。ゲーム・戦略・Rollout・報酬・停止関数に差分なし。Phase 36は未ステージ・未commit・未push。
