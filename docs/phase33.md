# Phase 33：Adaptive Stopping Validation Lab

## 1. 研究目的・基準版

Phase 32の適応停止規則を変更せず、独立した検証配札で、計算削減が起きる条件と独立評価報酬を調べる。早期停止0も有効な結果であり、早期停止を出すために閾値を変更しない。

Phase 32は `適応サンプリングと独立参照評価の研究基盤を追加` として通常commit・push済み。SHAは `ff340423332b09baebe09aaf79734d017774d790`。Phase 33は未ステージ・未commit・未pushで残す。

## 2. Phase 32からの変更

ゲーム・戦略・Rollout本体・報酬・候補順位・停止式・3標本の系列は変更しない。既存selectへ任意のログ通知、既存ワーカーへ既定では何もしない拡張フックを追加した。通知は乱数も標本も使わず、停止判断へ値を返さない。既定のPhase 32では無効。

最終レビューで、既存のブラウザJSON保存はJavaScriptの数値精度により64ビット派生seedを丸め得ることを確認した。共通UIの出力をAPIのJSONそのもののBlob保存へ修正した。停止規則・サーバーの結果・既存保存行は変わらない。画面のJSON整形表示はJavaScript数値の制限があるため、正確な派生seedの原本はダウンロードJSON／API／CLIを使う。

新しいkind `adaptive_stopping_validation_v1`で検証Plan、進行時点を巡回する事前局面選択、途中チェックポイントの永続化、配札単位の停止率・コスト差を追加した。旧実験行・Hashは変更しない。

## 3. 固定した停止規則とPlan

| 項目 | 固定内容 |
| --- | --- |
| 初期世界／追加バッチ | 16／16 |
| Gap | 上位2候補の平均報酬差が0.5を超えたら停止 |
| Uncertainty | 最上位と全競合の対応差がそれぞれ `2 × paired_SE + 0.05` を超えたら停止 |
| Fixed | 指定上限まで全合法手を同数評価 |
| 同点 | rank昇順、同rankはsuit昇順 |
| パイロット最大世界 | 32 |
| 参照／最終評価 | 独立した各16世界、モデル別 |

閾値・初期数・追加数の変更、診断データの混入、最終評価用配札は設定スキーマで拒否する。将来の別Planでは予算を事前指定できるが、同一Plan内の上限は固定する。

停止検証専用Experiment Planをsnapshot.stopping_planへ保存する。停止条件・局面選択規則・主要比較・アウトカム・分析単位・多重比較上限を固定する。配札seed、モデル、反復数を含む全設定はsnapshot.configへ保存し、全体の条件Hashで保護する。登録後の変更やソース変更後の開始は拒否する。

パイロットの識別子：

- 実験ID：`5cb2fd16-94e8-4523-a399-2a59055d86fe`
- 条件Hash：`49c1b2ceb78670c8096826ae40c85973fd9291891b948181888655505c81985d`
- 停止検証Plan Hash：`a11fbe0b98fc650e21612c337959f1e153cfbf0a3c02f6455953abfd05f1da3e`
- 規則Fingerprint：`b774337d8b3525d0f254d7dc9611e43403fc8db77d2001b2ff962806e4126fe4`

FingerprintにはPhase 32の停止関数、順位関数、対応差計算のソースと固定パラメータを含める。単体テストでこれらの関数ASTが基準コミットと同一であること、ログ有無で選択・評価結果が一致することを確認する。

## 4. 停止判定トレース

各局面・モデル・反復・予算・方式について、開始、チェックポイント、選択完了を記録する。全候補の推定報酬、上位差、競合別の対応SE、条件の各構成要素、追加標本の有無、最終札、停止理由、上限到達を保存する。残り手番・ラウンド、合法手数も付ける。

停止余裕は次の二つを分ける。

- Gap余裕：上位差−0.5。
- Uncertainty余裕：競合ごとの `差−2×SE−0.05`。全条件の最小値も表示する。これは連言の一番厳しい余裕であり、新しい評価関数ではない。

Fixedについても比較用の構成要素を記録するが、実際のcondition_metは常に停止関数の戻り値に基づく。途中SEは探索的な停止指標であり、逐次有効な信頼区間ではない。

正規化した停止理由はearly_stop、max_worlds、max_derived_games、cancelled、invalid_or_insufficient_samples、completed_fixed_budget。時間上限はtimed_outとして別記する。元のPhase 32のraw_stop_reasonも残す。条件が上限時に初めて成立しても、計算削減がなければearly_stopにしない。

中断時は最後まで到達したチェックポイントと、進行中セッションの終端状態を保存する。初期チェックポイント前ならログは空のまま、選択未完了・札未確定として残す。参照・最終評価で中断した場合は、選択完了と実験全体の中断を区別する。

## 5. 局面収集と事前選択

Random、Heuristic、ScoreAware、Zigzag、Reverse Zigzagの5収集元で合法軌跡を生成し、各席の観測を取得する。元の層別分類・公開履歴・観測境界を再利用する。

結果を見る前に、序盤→中盤→最終ラウンド直前→最終ラウンド中を巡回する。実配札・得点層・収集元の既選択数が少ない局面を優先し、最後は局面Hashで決める。到達した在庫を選ぶ方式であり、存在しない層を人工的に作らない。選択Hash一覧を分析開始前に保存する。

最高・最低・厳密中間・同点と各時点について、収集数・計画数・評価数・not_evaluatedを表示する。主集約は全事前選択局面。計算削減あり／なしに限定する集約は副次的・事後選抜と明記する。

## 6. 独立配札の管理

検証配札の範囲は1000000〜1999999。最終評価用区分は使用しない。既存実験・Plan・予約seed・実配札内容Hashと照合して重複を拒否する。既存のadaptive_dealsとmiddle_seed_reservationsを再利用し、新しいSQLiteスキーマは追加しない。

同一配札の複数席・収集元・時点・モデル・反復は、独立配札数を増やさない。集約は反復→局面→実配札を等重み。モデルと予算を合算しない。

## 7. Fixedとの比較・主分析

主要比較はGap−Fixed、Uncertainty−Fixed。主要アウトカムは独立最終評価報酬と派生対局数。停止率・手番・時間・Self-Middle差・Regret・層別は副次的な記述とする。

各方式は同じ観測、合法手、継続モデル、最大予算、終局報酬、サンプリング規則、タイブレークを使用する。方式・予算は同じ選択系列の先頭を使い、候補間は共通世界・政策乱数を使う。分岐後の乱数消費の一致は保証しない。

途中結果で実験全体を統計的に打ち切らない。運用上の中断・時間／派生対局上限は明示し、未完了実験の主集約を提供しない。欠測局面を0停止率・0報酬で補完しない。

## 8. 独立参照と符号付きRegret

Phase 32のPolicy Selection、Reference Selection、Final Evaluationを再利用する。参照は独立標本で選び、さらに別標本で固定カードを評価する。Final Evaluationは仮想世界の段階名であり、最終評価用配札seed区分ではない。

`Regret = final(reference) − final(selected)`。有限標本の参照を真の最適手と呼ばず、負値を許す。Fixed差・Self-Middle差・Regretの条件付き区間は、同じ最終世界の対応差から計算する。

## 9. 停止率と不確実性

停止率は配札内で反復と局面を平均し、独立配札平均へ集約する。区間はこの[0,1]に有界な配札平均に対する固定標本Hoeffding境界＋Bonferroni。局面数を二項試行数として扱わない。多重比較の保守的上限は10000、alpha=0.05。

少数配札では区間が[0,1]になり得る。報酬差・コスト差は既存の固定標本集約を再利用し、10配札未満では区間を提供しない。これらは配札一般化の精度が不足していることを示す。観測した差0や有意差なしは同等性の証明ではない。同等性の許容幅・検証は登録していない。

## 10. 計算量と報酬

選択派生対局、完了シミュレーション手番、経過時間、Fixedとの対応コスト差、最大観測コストを記録する。参照・最終評価は研究オーバーヘッドとして別集計する。早期停止だけでなく、未停止を含む全局面の独立報酬を確認する。

中断した派生対局の部分手番はPhase 32同様に未計測。started/completedを分け、手番は完了対局の下限とする。ログの保存時間も実験workerの時間に含まれ、時間は主たる公平性指標ではない。

## 11. 小規模パイロット結果

実行前に研究ローカルJSONへ条件を固定した。既存Phase 32 DBの保護コピーで実施し、旧22実験行が一致することを確認した。元の研究DBは変更しない。パイロットDBはresearch-local/phase33/pilot.sqliteに保持し、通常起動のDBへ自動移行していない。ここに記載した実験IDは専用DBのIDである。

- 独立検証配札：1900000、1900001の2件。
- 収集：5収集元×2配札＝10軌跡。分析4局面、3モデル、各2反復、3方式、最大32世界。
- 参照16世界・最終16世界。選択セッション72件、チェックポイント143件。
- 事前上限：40,000派生対局・120秒（保守的見積もり37,632派生対局）。
- 実測：選択20,064派生対局、研究用3,360、計23,424。シミュレーション200,544手番。収集軌跡150手番は別。
- 経過：95.828秒。選択区間81.772秒、研究用区間13.632秒。
- CPU識別：Intel64 Family 6 Model 198 Stepping 2, GenuineIntel。

| 配札 | turn（0始まり） | 進行 | 得点層 | 収集元 | 合法手 |
| --- | ---: | --- | --- | --- | ---: |
| 1900000 | 3 | 序盤 | 同点 | Heuristic | 14 |
| 1900001 | 6 | 中盤 | 最低 | Random | 11 |
| 1900001 | 11 | 最終ラウンド直前 | 最高 | ScoreAware | 6 |
| 1900000 | 13 | 最終ラウンド中 | 厳密中間 | Zigzag | 4 |

収集自体はReverse Zigzagも含む。分析の収集元は結果前の選択規則で決まり、全収集元を無理に分析へ含めない。上表以外の層×時点は未評価として表示する。

### 主集約（モデル別、配札を等重み）

| モデル | 方式 | 早期停止率 | 平均派生対局 | Fixedコスト差 | 独立報酬 | Fixed報酬差 | Self-Middle差 | 符号付きRegret |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Random | Fixed／Gap／Uncertainty | 0 | 280 | 0 | 0.507813 | 0 | 0.218750 | -0.179688 |
| Heuristic | Fixed／Gap／Uncertainty | 0 | 280 | 0 | 0.351563 | 0 | -0.265625 | 0.023438 |
| ScoreAware | Fixed | 0 | 280 | 0 | 0.195313 | 0 | 0.070313 | -0.070313 |
| ScoreAware | Gap | 0.125 | 268 | -12 | 0.195313 | 0 | 0.070313 | -0.070313 |
| ScoreAware | Uncertainty | 0 | 280 | 0 | 0.195313 | 0 | 0.070313 | -0.070313 |

各モデル・方式は8選択でも、独立単位は2配札である。停止率の保守的区間はいずれも[0,1]。報酬差・コスト差の配札一般化区間は不足のため未提供。最大観測コストは1選択448派生対局。

停止理由はcompleted_fixed_budget 24件、max_worlds 47件、early_stop 1件。キャンセル・不正標本・上限打切りはこのパイロットでは発生していない。

### 早期停止の観測例（副次分析）

最高得点・最終ラウンド直前のScoreAware、反復1でGapが16世界で停止した。上位差0.5625、閾値超過余裕0.0625。全競合のUncertainty最小余裕は-0.3363であり、そちらの停止条件は不成立だった。

選択は♦3でFixedの32世界選択と一致。派生対局は192→96（96削減）、手番は768→384。独立評価報酬は0.125、Fixedとの差は同じ札なので恒等的に0。この1例から、未観測局面での報酬維持や最高得点層での優位性は主張しない。

## 12. 停止しなかった要素の整理

Gapの上限到達23件のうち22件は最後も差閾値が不成立、1件は上限32世界で初めて成立し計算削減にならなかった。Uncertaintyは24件すべてで、32世界でも少なくとも一つの競合に対する余裕が非正だった。

| モデル | 上限時のGap余裕範囲 | 上限時のUncertainty最小余裕範囲 |
| --- | --- | --- |
| Random | -0.500〜-0.344 | -0.487〜-0.074 |
| Heuristic | -0.500〜-0.250 | -0.805〜-0.345 |
| ScoreAware | -0.500〜0.125 | -0.844〜-0.083 |

これらは不成立の構成要素の記述であり、因果原因の識別ではない。候補の価値差、不確実性、合法手数、残り長さ、継続モデル、予算を別々に残す。2配札から「合法手が多いほど不安定」などの関係を確定しない。

## 13. 統計的制限

独立配札2件・4選抜局面の小規模検証である。局面Hashに基づく選択は結果を見る前だが、全局面の代表標本とは限らない。停止率区間は非常に広い。初期標本と最終標本の評価値差は、選択や標本誤差の影響を受ける。閾値の調整は行っていない。

停止した局面だけの解析は副次的・探索的であり、主分析へ戻さない。選択・参照・最終世界は独立でも、反復間は最終評価表を共有する。反復を独立配札と数えない。継続モデル間の報酬を合算しない。

## 14. UI・API・CLI・直接リンク

画面は `戦略研究 / 中間順位・意思決定研究 / Adaptive Stopping Validation Lab`。上位カテゴリは5つのまま。20画面を登録する。共通のAdaptivePanelを再利用し、停止率・保守的区間・主集約・全トレース・未評価層の表示を追加した。モデルと予算をグラフ上でも分ける。

APIは `/api/stopping/estimate`、`/api/stopping/jobs`、`/{id}`、`/{id}/export`、`/{id}/start`、`/{id}/cancel`、`/{id}/design-draft`、`/{id}/evidence`。汎用Design Planへは別条件追試Draftを作成し、既存Evidence Seriesへは参照のみ保存する。異なる実験の効果・配札数へ自動合算しない。

`/research/stopping?experiment=<ID>`で保存履歴を開く。再読込、戻る・進む、条件復元に対応し、GETだけで実験を再実行しない。不正ID・別LabのIDは404。URLには実験IDだけを入れる。

CLIは既存基盤に接続する。既定は見積もりだけ。

```powershell
$env:PYTHONPATH = 'backend/src'
backend/.venv/Scripts/python.exe -m strategy_arena.experiments.stopping_cli --config research-local/stopping-config.json
backend/.venv/Scripts/python.exe -m strategy_arena.experiments.stopping_cli --config research-local/stopping-config.json --database research-local/stopping.sqlite --register --output research-local/stopping-registered.json
backend/.venv/Scripts/python.exe -m strategy_arena.experiments.stopping_cli --config research-local/stopping-config.json --database research-local/stopping.sqlite --run <登録ID> --output research-local/stopping-result.json
```

## 15. 検証・既知の制限

Python 397件、Vitest 51件、Playwright 51件成功。TypeScript型検査・Viteビルド成功。git diff --check成功。既存のStarlette/httpx非推奨警告、色設定警告、大きなJSバンドル警告は維持した。重点項目は停止式のAST一致、ログ有無の選択一致、構成要素と余裕、理由分類、配札単位の集約、欠測、条件Hash、合法局面、保存・再読込、実行中キャンセル、誤ID、既存Phase 32回帰。

同一Labは1件ずつだが全Lab共通の同時実行制限ではない。ジョブはローカルworkerで、再起動時のRunningはInterruptedとなる。開始していない比較を実行済みとして補完しない。部分手番は未計測。上側時間見積もりは未校正で、序盤の長いRolloutは特に重い。条件を変えるときは別の未使用配札で別Planを作る。

今回の設定上限は少数配札向けであり、十分な検出力を持つ大規模検証や同等性検証は提供していない。他の既存Labへの実験ID対応拡大、履歴ページングは今回の対象外。

## 16. 次の研究課題

規則を固定したまま別の未使用検証配札を追加し、早期停止が出た層だけでなく全事前局面で結果を確認する。閾値を調整する場合は開発用へ戻し、この検証データを使った調整結果を確証と呼ばない。標本数の拡張、比較可能なPlan間の独立配札集約、逐次有効な境界、部分手番の計測を別タスクとして検討する。


## 変更ファイル・最終監査

| ファイル | 内容 |
| --- | --- |
| backend/src/strategy_arena/experiments/stopping_analysis.py | 停止構成要素・余裕・理由・配札集約 |
| backend/src/strategy_arena/experiments/stopping_lab.py | 固定設定・Plan・事前局面一覧・中断保存 |
| backend/src/strategy_arena/experiments/stopping_cli.py | 登録と明示実行のCLI |
| backend/src/strategy_arena/experiments/adaptive_analysis.py | 既定で無効な選択ログ通知 |
| backend/src/strategy_arena/experiments/adaptive_lab.py | 既定で無効なPlan／実行拡張フック |
| backend/src/strategy_arena/api/app.py | 新namespaceとworker終了処理 |
| backend/tests/test_stopping_lab.py | 20件の停止不変性・保存・統計・キャンセル検証 |
| frontend/src/features/stopping/StoppingPanel.tsx | 停止検証の主集約・トレース・未評価層 |
| frontend/src/features/stopping/stopping.test.ts | 固定初期条件と主／副次分析の分離 |
| frontend/src/features/adaptive/AdaptivePanel.tsx | 共通UIの再利用・API原文JSON保存 |
| frontend/src/features/workspace/registry.tsx | 新Lab登録、5カテゴリを維持 |
| frontend/src/features/workspace/workspace.test.ts | 20画面・6関連Labの登録検証 |
| frontend/e2e/stopping.spec.ts | URL・停止規則拒否・結果・JSON原文一致 |
| frontend/e2e/workspace.spec.ts | 全画面のURL・グループ到達検証 |
| README.md | 日本語で新機能を案内 |
| docs/phase33.md | 設計・実測・制限 |

PC 1440pxとモバイル390pxの表示・横幅・ブラウザ実行エラーなしを確認した。スクリーンショットはresearch-local/phase33/のみ。CLIの既定見積もりも確認した。JSON保存修正後はPhase 32・33の対象Playwright 4件と型検査・ビルドを再実行し、API原文との一致を確認した。浅いcloneで基準コミットがない場合、停止関数の履歴照合テストにはPhase 32コミットの追加取得が必要。

公開候補274ファイル、今回の変更16ファイルを監査。秘密情報候補0、除去済み10パスの追跡・ステージ・main履歴への再混入なし。research-local/、PDF、画像、抽出資料、DB、ログ、実.envは公開対象外。ゲーム・戦略・Rollout本体・報酬の差分なし。作業前にハッシュを記録した1307個の.sqlite/.sqlite3/.dbファイルの一致、パイロットコピー内の旧22実験行の一致を確認した。git diff --check成功。Phase 33は未ステージ・未commit・未pushである。
