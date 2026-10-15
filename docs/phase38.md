# Phase 38：Pre-Registered Multi-Deal Validation

## 1. 研究目的

128世界のGap/Uncertainty − Fixedについて、実時間・計算量節約、独立終局報酬差、判断分岐と報酬の符号を独立配札単位で評価する。

## 2. Phase 37の確定と変更

Phase 37は `66c71f4fa411cb37116bfdff014172709e5d786f`、メッセージ「低負荷時間計測と判断分岐の配札単位評価を追加」で通常commit・push済み。Phase 38は未ステージ・未commit・未push。既存Runtime Noise & Decision Divergence Labのみ拡張する。新Lab・ナビ・戦略は追加しない。revision省略は従来phase36。旧実験行・Hash・Evidence参照は変更しない。

## 3. 固定停止規則

初期16・追加16世界。Gapは上位と次点の対応差 > 0.5、Uncertaintyは全競合への対応差 > 2×SE+0.05。Fixedは128世界まで。rank/suit昇順の同率処理。Phase 37のselect/stopping AST一致を検証。ゲーム・合法手・報酬・既存戦略・Rollout・サンプラー・共通世界・停止関数は変更しない。

## 4. 事前登録Plan

登録は固定操作、実行は別の明示操作。config・ソースHash・基準commit・実配札Hash・規則Hash・仮説・Plan/Plan Hash・環境をSQLiteへ保存。開始時にsnapshot/Plan/config Hash整合とソース一致を確認する。編集APIなし。変更は別Planとして登録し、配札再利用は予約表で拒否する。

主要比較はGap − FixedとUncertainty − Fixed、主アウトカムは直接wall差と独立終局報酬差。Random/Heuristic/ScoreAwareを同一配札内で等重み集約し、次に配札を等重みにする。モデル別・全層別分析は副次/探索的。欠測を補完せず、中止は予算・時間・実装エラー・ユーザー取消だけ。中間アウトカムで条件変更しない。

## 5. 計算予算見積もり

Phase 37のDは4配札・14,880派生対局・約53.6秒で、直接実行の再計算を含まない。Phase 38の検証案は6配札・各1局面・選択1反復、turn4/10/11/14、3モデル、128世界、参照16・最終16、専用warmupなし。

時点巡回の最大合法手数合計49より、最大経路18,816、直接実行56,448、参照2,352、最終2,352、合計79,968派生対局。モデル別上限26,656、手番上限879,648。収集30対局・450手番は別。未校正時間範囲39.984〜242.904秒、上限80,000対局・250秒。全体上限は開発7,104＋検証79,968＝87,072派生対局。

開発実測は7,104派生対局・14,208手番・5.219秒。終盤1局面の直接wall合計はRandom0.4956秒、Heuristic1.3776秒、ScoreAware1.2983秒。各モデル直接対局1,536・参照64・最終64。独立したSQLiteコピー保存測定5回は約3.5〜4.5ms/回（直列化・接続・commit込み、workerの保存総時間ではない）。序盤の継続長やpayload増大へ秒単価を単純外挿しない。

## 6. Development / Validation / Holdout

開発は配札38000・turn13・128世界・3モデル、最初の局面で16世界warmup1回。費用と動作だけを確認。その後検証1950000〜1950005のPlanを固定する。Final Holdoutは使用しない。

開発後、Planの環境説明（直接計時範囲、測定1回、warmup範囲、副次アウトカム）を明確化した。計算処理は変えず、開発時の全バックエンドをresearch-local/phase38/development-source/に保持。検証は訂正済みPlanで登録した。

## 7. 独立配札管理

research-local内の691個のSQLiteを読取専用で調査し、記録612配札を照合。既存deal_identityで実配札内容Hashを計算し、同一DBのadaptive_deals・middle_seed_reservations・design_seeds・過去実験seed/Hashにも照合する。検証には既存Hash一覧と検出範囲が必要で、空一覧は拒否。作業前の既存830個の.sqliteのSHA-256も保護する。

未記録実験・外部DB・未保存seed・別配札生成実装までの完全照合は保証しない。「照合可能範囲内で重複なし」と扱う。1配札のモデル・局面・反復は独立配札数を増やさない。

## 8. 主要128世界比較と収集

5収集元Random/Heuristic/ScoreAware/Zigzag/Reverse Zigzagの合法軌跡。序盤・中盤・直前・最終ラウンド中、厳密中間・最高・最低・同点が対象。既存の時点巡回と配札・得点層・収集元・Hashの固定規則を使用する。1配札1局面に到達しなければ補完せず失敗として記録。未到達層を埋める後付け選別なし。選択側へは本人Observationのみ渡す。

## 9. 実時間差

Phase 37と同じ外側perf_counter/process_timeとcheckpoint計数のみ。内側の高頻度timer/profileなし。保存・収集・参照・最終評価は計時外。任意warmupは最初の局面だけ16世界で別コスト。モデル別専用order seedの初期順を局面ordinalで循環し、6配札で各方式が各位置を2回訪れる。

最大照合経路と独立評価の後なのでcold-startではない。環境ノイズを含む実測であり、派生対局差から時間を推定しない。

## 10. 派生対局数差

方式ごとの反実仮想コストと研究全体の実コストを区別。照合最大経路・全方式直接実行・参照・最終・warmupを実計上。部分実行はexecution_cost/runtime_measurementsに保存。未計測時間はnull。

## 11. 判断分岐率

Adaptive札 != 対応Fixed札。全事前対象を分母に、配札ごとの発生・率を集計する。分岐時の報酬差を正・負・ゼロに分けた個数は探索的な条件付き分析で、全対象の平均報酬差とは区別する。

## 12. 独立評価報酬差

Policy128・Reference16・Final16世界。役割別seedを分離し、最終評価世界を共有して対応比較する。評価情報を選択へ戻さない。参照札は真の最適手ではない。Self-Middle差・有限標本参照差・負を含む符号付きRegretを保持する。

## 13. 配札単位集約

モデル別・層別は反復→局面→配札の等重み。主要2比較は配札内3モデル等重み→配札等重み。配札別wall/CPU/報酬差・分岐を保存。6配札×3モデルを18独立標本とは数えない。

## 14. 統計的制限

6独立配札では検出力が低い。記述統計を優先し時間CI・主要等重み報酬差CIは未提示。モデル別の既存有界区間も小標本の制限がある。報酬差0を同等性、有意差なしを性能維持の証明としない。層別はさらに小標本で因果機序を解明しない。

## 15. UI・API・CLI・SQLite

既存Labの新規条件に「事前登録型複数配札検証」を追加。Plan Hash・固定状態・予算・seed用途・完了配札数・主要対応差・モデル別結果・分岐符号を表示。照合一覧をJSONで指定する必要がある。

既存estimate/jobs/start/cancel/detail/export/Evidenceを再利用。SQLiteスキーマを破壊しない。64bit導出seedはAPI・SQLite・UI・JSONで十進文字列。JSON出力はAPI原文BlobでJavaScript Numberへ変換しない。

```powershell
$env:PYTHONPATH="backend/src"
backend/.venv/Scripts/python.exe -m strategy_arena.experiments.noise_cli --config research-local/phase38/validation-config.json --database research-local/phase38/reproduction.sqlite --register
```

保存IDで `--run <ID>` を別途指定。配札予約済みDBで再登録しない。厳密再現は同じソース・設定が必要で、時間一致は保証しない。

## 16. 実験直接リンク

`/research/runtime-divergence?experiment=<ID>`を維持。直接表示・再読込・戻る進む・条件復元・不正/他Lab ID拒否・表示時の非自動実行は既存基盤。Evidenceは参照であり異なる条件を合算しない。

## 17. テスト結果

Python全491件・Vitest58件・Playwright全61件成功。TypeScript型検査・Viteビルド成功。既存のStarlette/httpx非推奨、色設定、バンドルサイズ警告のみ。固定Plan/Hash・上限・重複・3標本・順序・再現性・配札集約・負Regret・旧行不変・部分計時/取消・URL・文字列seedを検証する。

## 18. 公開監査

研究データ・DB・計測スクリプトはresearch-localのみ。除去済み10パス・秘密情報・DB/ログを公開対象へ含めない。公開候補306件・変更8件を監査し、除去済み10パスは無追跡/ignore有効、秘密情報候補0、既存830個の.sqliteのハッシュ一致。diff --checkを実施。Phase 38はcommit/pushしない。

## 19. 既知の制限

少数配札・各層不足・参照/最終16世界・均一未公開カードサンプリングの制限。高度な行動推論なし。複数Lab間の排他はなく計測中はテスト/他Labを実行しない。取消は協調方式。中断・超過・失敗は完了集約へ補わない。

## 20. 次の研究課題

追加配札は別Plan・別タスクで予算を確認する。十分な配札でクラスターブートストラップと主要比較族の区間を検討。今回の分岐を結果選別して検証へ再投入しない。停止規則変更は別版の開発から始める。

## 21. 実施結果：検証は未完了

検証ID `43b32912-36f2-41aa-99e7-0025dd5b7f9e`。Plan Hash `82a2817460f430d85cc2ecba986dbb7a0c45290bf6c2f340fde18c96c76a69d3`。条件Hash `40ac095acb1fa84775e875c549507d47d24052dedcdf601c5f586db244030f01`。固定後に変更しなかった。

250.032秒で事前時間上限によるTimedOut。6配札収集済み、完全評価4配札/4局面、5番目の局面は部分実行、最後の局面は未評価。主要6配札の集約はnullであり、主要実時間差・報酬差は未確定。再実行・条件延長・配札追加はしなかった。

実派生対局は開始62,882・完了62,881、完了派生対局の手番515,051（実行中1対局の部分手番は未計測）。完了局面だけのコスト45,872対局・327,952手番と混同しない。収集30対局・450手番は別。計測43件中42件完了、1件はnull。開発を含む派生対局は開始69,986・完了69,985、全実験経過計255.251秒。既存行は開発前32件・検証前33件が不変。

以下は完了した4配札だけの**探索的な部分記述**で、事前6配札を対象とした主要結果ではない。時間上限による欠測はランダムとは限らず、速度や品質の推論へ使わない。方式順序も6配札の完全な巡回が終了していない。

| モデル | 方式 | 部分wall差平均秒 | 部分報酬差 | 派生対局差 | 早期停止率 | 分岐率 | 分岐時 正/負/ゼロ | Self差 | 符号付きRegret |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| Random | Gap-Adaptive | -0.113947 | -0.078125 | -364 | 50.00% | 50.00% | 1/1/0 | 0.343750 | 0.015625 |
| Random | Uncertainty-Adaptive | -0.006344 | 0.000000 | 0 | 0.00% | 0.00% | 0/0/0 | 0.421875 | -0.062500 |
| Heuristic | Gap-Adaptive | -0.099072 | 0.000000 | 0 | 0.00% | 0.00% | 0/0/0 | 0.359375 | 0.140625 |
| Heuristic | Uncertainty-Adaptive | -0.124140 | 0.000000 | 0 | 0.00% | 0.00% | 0/0/0 | 0.359375 | 0.140625 |
| ScoreAware | Gap-Adaptive | 0.000930 | 0.000000 | 0 | 0.00% | 0.00% | 0/0/0 | 0.593750 | -0.390625 |
| ScoreAware | Uncertainty-Adaptive | -0.021045 | 0.000000 | 0 | 0.00% | 0.00% | 0/0/0 | 0.593750 | -0.390625 |

部分分母は各比較4独立配札で、検証全体の分岐率として50%を報告しない。Random Gapの分岐2件は独立評価上の報酬差が正1/負1。未完了2枠をゼロとして分母6へ埋めない。Heuristic/ScoreAwareでは派生対局差0でもwall差が正負に振れ、環境ノイズを含む。符号付き時間差のCVは解釈しない。

完全評価した局面：1950003/turn4/序盤/同点/Random、1950004/turn10/中盤/最高/Heuristic、1950001/turn11/直前/最低/Zigzag、1950002/turn14/最終/厳密中間/Reverse Zigzag。予定されたScoreAware収集の序盤同点は部分評価、最後のReverse Zigzag収集の中盤厳密中間は未評価。最終ラウンド開始は対象外。層別は各1配札の記述に留め、報酬の因果説明をしない。層別の部分値はresearch-local/phase38/partial-exploratory.jsonに保存し、主要結果としてAPIへ登録しない。

保存先はresearch-local/phase38/pilot.sqlite、登録/結果/設定JSONも同ディレクトリ。旧開発DBを上書きしていない。検証時の全ソースをvalidation-source/に保存し、snapshotの全ソースSHA-256一致を確認した。検証後のAPI応答でPhase 38のコスト範囲説明を明確化したが、保存Plan/結果と計算処理は変更していない。厳密再現には保存した検証時ソースを使う。

次の作業では、時間単価を候補数×残りターン×モデル別に校正し、SQLite進捗保存の増大も含めた新しいPlanを別途検討する。今回のPlanを延長・再開して主要結果を完成させない。

## 22. 測定環境と変更ファイル

2026-10-15日本時間。Windows-11-10.0.26200-SP0、Python 3.12.14、CPU Intel64 Family 6 Model 198 Stepping 2, GenuineIntel、論理CPU 20。1 worker・並列なし。検証中は全件テスト/他Labを実行していない。OSや他アプリの活動は隔離しておらず、CPU時間はプロセス単位。

変更はREADME.md、experiments/noise_lab.py、NoisePanel.tsx、noise.test.tsの4件。新規はexperiments/multideal_analysis.py、tests/test_multideal_lab.py、e2e/multideal.spec.ts、本書の4件。ゲーム、戦略、Rollout、停止関数に差分なし。

完了画面と実際のTimedOutデータ（読取応答だけを差し替え、追加計算なし）のデスクトップ/390pxモバイル表示も確認した。pageerrorなし、横方向の画面はみ出しなし。TimedOutでは主要集約を表示せず、完了4/事前6・62,881完了派生対局・時間超過理由を表示する。
