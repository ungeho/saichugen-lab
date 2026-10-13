# Phase 17：Rolloutの探索品質評価

## 基準と目的

Phase 16は `8b380bec5e85f6368f7aa2f1c49db818f3abb160`（Monte Carlo Rollout戦略を追加）として通常commit・push済み。確定時はPython134件、Vitest13件、Playwright21件、型検査・ビルド成功。Phase 17は未コミットの開発成果である。

試行数・継続戦略・計算コストを分けて調べる。主指標は平均終局報酬。累計得点・単独/共同勝利率を選択目的と混同しない。ゲームルール、勝者判定、報酬表、既存5戦略の式は変更しない。

## 実験計画

- A：Random継続固定、8/16/32/64試行を比較。experiments/presets/rollout-trials.json。
- B：8試行固定、Random / Greedy / ScoreAwareを比較。experiments/presets/rollout-continuations.json。
- C：保存済みA/Bの平均報酬と平均判断時間を散布図で見る。再対戦を発生させない、同じ結果からの分析。

Greedyは今の獲得を優先、ScoreAwareはラウンド得点が中位以下なら獲得・上なら回避する。後者もゲーム全体の報酬を直接最大化しない。Randomとの違いで継続モデルの偏りを比較する。相手は既定でRandomとHeuristic、JSONでは既存5戦略の2席を指定可能。全組み合わせや大規模実験は自動実行しない。

各配札で役割（対象・相手0・相手1）の全6順列を使う。相手が同名でも別roleの初期乱数を持つ6条件として扱う。配札seedは設定間で共通、方策seedはquality-policy:{deal_seed}:{role}をderived_seedへ渡すため設定名・試行数に依存しない。各対局では戦略を新規作成し、対象のMonteCarloRolloutへ設定を明示的に注入する。registryの動的な書き換えはしない。

Rolloutは外部rngを1判断に1回消費するので、試行数が異なっても初期探索乱数を比較しやすい。試行数比較では内側の継続名も同じなので初期席乱数を共有する。継続戦略比較では、既存の内側seedに継続名が含まれるため、世界seedは共通でも席乱数系列そのものは異なる。分岐後の観測・乱数消費も異なり得るので、対局全体で完全な同一乱数を保証するものではない。

## 指標と統計

設定ごとに平均終局報酬、単独/共同勝利率、平均累計得点、使用対局数、記録対局数、独立配札数を表示。計算性能は対象席の判断時間の平均・中央値・p95・最大、全席込みの対局平均秒、開始Rollout数、終局まで実行した数、公平な試行集計に採用した数、判断の時間上限件数を記録する。

通常のchooseは計測明細を返さないため、実験だけでchoose_detailedを呼び、計算量を抜き出した直後に詳細を破棄する。時間はこの明細作成のオーバーヘッドを含み、Phase 16の詳細なしベンチと同じ測定ではない。途中の対局は報酬標本にしないが、終了した判断までの計算コストをpartial_gamesへ保存する。呼び出し自体が異常終了した判断の途中コストは取得できない場合がある。共通局面プローブは対戦のコスト指標に含めない。

1配札の6席順を独立標本とはしない。設定ごとに6席順が揃った配札だけを採用し、その配札内報酬平均を1標本とする。独立配札平均を2000回再標本化する百分位ブートストラップの2.5/97.5%点を区間にする。基準（settingsの先頭）との差は両設定で6席順が揃った共通配札の対応差から同じ方法で計算する。独立した区間を引き算しない。

1配札以下は区間未提供。2配札の区間は極めて粗く、20配札未満は探索的な参考値として表示する。分散0の0幅区間も確実性の証拠ではない。多重比較・設定選択の偏りへの補正は未実装。タイミングを含む数値全体の再現性は保証せず、固定予算での選択・得点・報酬・統計が再現対象。判断時間上限を使うと打切り回数・判断も環境に依存する。

## 実行・保存・再実行

従来のWindows起動方法を維持する。

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\dev.ps1
```

アプリの「探索品質」タブでプリセットを選び、JSONを確認・編集し、見積もり後に実行する。設定・結果をJSON保存でき、設定JSONの貼付で再実行できる。保存済み実験は同じ画面で再読込する。設定変更時は見積もりを無効化し、古い規模で開始しない。

リポジトリ直下からCLIでも実行可能。既定は見積もりだけ、--runが明示実行。

```powershell
uv run --project backend python -m strategy_arena.experiments.quality_cli --config experiments/presets/rollout-trials.json
uv run --project backend python -m strategy_arena.experiments.quality_cli --config experiments/presets/rollout-trials.json --database research-local/phase17/results.sqlite --output research-local/phase17/export.json --run
```

独立配札を増やす場合は設定JSONのdeal_seedsへ重複のない非負整数を追加する。Python Randomの符号違いseedで同じ配札を別標本と数えないため、負の配札seedは拒否する。GUI/CLI双方で、最大20配札・8設定・360対局・概算50万Rollout、各設定1〜64試行、1実験300秒まで。同時実行1件。例として64試行×20配札はRollout上限超過で拒否されるので、予算を見積もって段階実行する。時間制限・中断は判断呼出し間等の協調方式で、重い1判断の間は直ちに止まらない。

既存ExperimentStoreのexperimentsテーブルへexperiment_kind=rollout_quality_v1のJSONを新規保存する。テーブル・旧データの移行や削除はしない。対象UUIDの新規ジョブだけをUPDATEして進捗を保存。通常実験・図鑑の集計へ無条件に混ぜない。専用APIのexportでは全行を返すが、通常の進捗GETでは対局行を省く。

保存情報はID、基準SHA、実行時HEAD・dirty状態・PythonソースのSHA256・CPU/Python、ルール/報酬版、設定、配札ID/seed、role/席順、相手、戦略版、得点・勝者・報酬、各判断の時間と計算量、状態。基準SHAはPhase 16の確定版で、未コミット評価器そのもののSHAではないためsource_sha256とdirtyも確認する。実装が違う結果を無条件に合算しない。今回A/Bの保存fingerprintは一致し、共通8/Randomの12対局について得点・勝者・報酬の一致も確認した。測定後の入力検証追加等で最終作業ツリーのfingerprintは保存時と異なる場合があるが、測定に使った非負seedの選択・評価処理は変更していない。

中断・時間切れ・失敗はcompletedにしない。完了対局を保存し、6席順が揃わない配札は報酬統計から除外して除外数を表示する。プロセス再起動後に残るrunning/cancelling記録はAPI閲覧時にinterruptedとして扱い、自動再開しない。対局途中からの再開・分散実行・強制終了は未対応。

## 同一局面の判断記録

最初の配札で全席が先頭合法札を12ターン出した、共通の5候補局面を各設定で評価する。実際の設定別対局は途中から局面が異なるため、同じターンの判断を同一局面と誤認しないための別プローブである。人工的な局面であることを画面に明記する。

本人のObservation（自分の手札・公開履歴・得点・ターン・残枚数）、そのJSONのSHA256局面ID、設定、選択札、候補報酬評価、seedを保存。実際の相手手札や余り札を観測として保存しない。配札seedは研究上の再現メタデータなので再構成は可能だが、AIへは渡さない。設定間で選択が変わったか表示する。

## 実装とAPI

- experiments/rollout_quality.py：設定、プリセット、見積もり、共通対局、プローブ、統計。
- experiments/quality_jobs.py：単一ワーカー、中断、保存、履歴。
- experiments/quality_cli.py：JSON実行、見積もり、Ctrl+C、エクスポート。
- runner._play_gameに任意の戦略・rng・中断checkを注入する拡張。既存の呼び出しは既定動作のまま。
- rolloutsとMonteCarloRolloutへ開始/終局カウンタを追加。選択・seed消費・評価式は変えず、途中破棄された仮想対局も数える。
- QualityStudyPanel、qualityModel：条件・表・区間の上下端点・散布図・基準差・保存・中断・局面詳細。

GET /api/quality-studies/presets、POST /estimate、POST /api/quality-studies、GET /api/quality-studies、GET /{id}、GET /{id}/export、POST /{id}/cancelを追加。通常実験のGETで専用実験IDを指定した場合も専用集計を返す。

## 実測結果

パイロット6対局で時間と保存を確認後、2独立配札（seed0,1）、policy_seed42、全6席順、相手Random/Heuristic、判断時間上限なしでA48対局、B36対局を順次実行した。CPUはIntel Core Ultra 7 265K、20コア/20論理プロセッサ、Windows・Python3.12.14。新たな大規模実験は行っていない。


### A：試行回数

実験ID 6b32f850-6076-4fda-bcc8-9e52c81fdd1c。全体所要 72.47秒。各設定12対局・2独立配札。

| 設定 | 平均報酬 | 95%区間 | 単独 / 共同 | 平均累計 | 判断ms 平均 / 中央 / p95 / 最大 | 対局平均秒 | 実行Rollout |
| --- | ---: | --- | --- | ---: | --- | ---: | ---: |
| 8 / Random | 0.000 | 0.000〜0.000 | 33.3% / 0.0% | 12.50 | 26.09 / 25.54 / 46.47 / 57.07 | 0.397 | 14400 |
| 16 / Random | 1.167 | 1.000〜1.333 | 66.7% / 8.3% | 13.50 | 54.32 / 53.20 / 92.57 / 105.06 | 0.820 | 28800 |
| 32 / Random | -0.250 | -0.667〜0.167 | 25.0% / 8.3% | 11.17 | 106.39 / 102.40 / 186.12 / 211.15 | 1.601 | 57600 |
| 64 / Random | 0.917 | 0.500〜1.333 | 58.3% / 8.3% | 8.42 | 212.03 / 201.16 / 390.34 / 423.56 | 3.186 | 115200 |

基準との差（対応配札2件）：
- 16/Random/None: +1.167、95%区間 1.000〜1.333
- 32/Random/None: -0.250、95%区間 -0.667〜0.167
- 64/Random/None: +0.917、95%区間 0.500〜1.333

共通局面 cf3c16e3d699e6cfe99450dc0e432d3721725f954afd73c55c75aa740a553c9d の選択：
- 8/Random/None → ♠12、探索seed 157225747671806667095506918570563519193
- 16/Random/None → ♠8、探索seed 157225747671806667095506918570563519193
- 32/Random/None → ♠8、探索seed 157225747671806667095506918570563519193
- 64/Random/None → ♦13、探索seed 157225747671806667095506918570563519193

判断の時間上限件数は全設定0。開始・終局実行・集計採用のRollout数は一致した。プローブの実行数は対戦指標と別扱い。設定別の全候補評価と本人観測はGit管理外の結果JSON/SQLiteに保存。

### B：継続戦略

実験ID 8890646f-8628-48df-b4a3-88f26135aad6。全体所要 192.66秒。各設定12対局・2独立配札。

| 設定 | 平均報酬 | 95%区間 | 単独 / 共同 | 平均累計 | 判断ms 平均 / 中央 / p95 / 最大 | 対局平均秒 | 実行Rollout |
| --- | ---: | --- | --- | ---: | --- | ---: | ---: |
| 8 / Random | 0.000 | 0.000〜0.000 | 33.3% / 0.0% | 12.50 | 25.34 / 24.67 / 45.10 / 48.09 | 0.385 | 14400 |
| 8 / Greedy | 1.083 | 0.833〜1.333 | 58.3% / 16.7% | 12.00 | 520.06 / 342.36 / 1580.18 / 1664.93 | 7.806 | 14400 |
| 8 / ScoreAware | 0.083 | 0.000〜0.167 | 25.0% / 25.0% | 9.00 | 522.36 / 339.13 / 1588.85 / 1680.19 | 7.841 | 14400 |

基準との差（対応配札2件）：
- 8/Greedy/None: +1.083、95%区間 0.833〜1.333
- 8/ScoreAware/None: +0.083、95%区間 0.000〜0.167

共通局面 cf3c16e3d699e6cfe99450dc0e432d3721725f954afd73c55c75aa740a553c9d の選択：
- 8/Random/None → ♠12、探索seed 157225747671806667095506918570563519193
- 8/Greedy/None → ♦11、探索seed 157225747671806667095506918570563519193
- 8/ScoreAware/None → ♠12、探索seed 157225747671806667095506918570563519193

判断の時間上限件数は全設定0。開始・終局実行・集計採用のRollout数は一致した。プローブの実行数は対戦指標と別扱い。設定別の全候補評価と本人観測はGit管理外の結果JSON/SQLiteに保存。

Aは合計72.47秒、Bは合計192.66秒で、pilotを含む計90対局のみ実測した。16試行がこの小標本では最も高い点推定、64試行はより遅く、32試行は低かった。試行数と報酬は単調ではない。Greedy継続は報酬の点推定を上げたが約20倍の判断時間になり、ScoreAwareは同程度の時間増に対して報酬差が小さい。効率の一般的な最適設定は決められない。

2配札だけのブートストラップ区間は標本の2点に強く依存する。8/Randomの0幅区間は配札平均が偶然一致したためで、真の不確実性0を示さない。探索seed・設定比較の結果は再現可能でも、この標本で「16/Greedyが強い」と確定しない。

## テスト

Python157件（追加23）、Vitest15件（追加2）、構文検査、TypeScript型検査、Viteビルド成功。Playwrightは新規2件の実行・保存・再読込・3グラフ・中断・不正計画・390pxを確認し、既存21件を含む全23件も成功した。最初の狭幅テストでグラフのグリッド幅が残ったため専用画面のminmax(0,1fr)とmin-widthを修正した。既存の非推奨警告・大きなバンドル警告は継続。

共通deal/role rng、全6席順、固定設定の得点・報酬再現、配札数、配札クラスタ区間、対応差、未完配札除外、Rolloutカウンタ（破棄試行も含む）、SQLite旧JSON不変・再読込、中断・時間切れ・失敗の未完了状態、再起動時中断扱い、入力上限、観測の範囲、通常対局/戦略/分岐の回帰を検証した。


## 制限とPhase 18候補

独立配札が2件では推論精度や強さの一般化はできない。区間が0を跨がなくても強さの証明にはしない。一様サンプリング・軽量継続の偏りは残り、有限標本の最大選択や多重比較も未補正。単一ローカルプロセス前提で、複数サーバー間の同時実行制御はしない。実行時ソース変更は避け、保存したfingerprintを比較する。

Phase 18は独立配札の計画的拡充、追加相手構成での追試、判断プローブの局面数追加、事前に固定した比較計画、適応的試行配分、時間予算別の公平な比較を候補にする。既定8試行を今回の2配札だけで変更しない。


## Phase 17変更ファイル

- README.md
- backend/src/strategy_arena/api/app.py
- backend/src/strategy_arena/experiments/catalog_statistics.py
- backend/src/strategy_arena/experiments/runner.py
- backend/src/strategy_arena/experiments/storage.py
- backend/src/strategy_arena/rollouts.py
- backend/src/strategy_arena/strategies/monte_carlo.py
- backend/tests/test_monte_carlo.py
- frontend/src/main.tsx
- frontend/src/style.css
- backend/src/strategy_arena/experiments/quality_cli.py
- backend/src/strategy_arena/experiments/quality_jobs.py
- backend/src/strategy_arena/experiments/rollout_quality.py
- backend/tests/test_rollout_quality.py
- docs/phase17.md
- experiments/presets/rollout-continuations.json
- experiments/presets/rollout-trials.json
- frontend/e2e/quality-study.spec.ts
- frontend/src/features/quality/QualityStudyPanel.tsx
- frontend/src/features/quality/qualityModel.test.ts
- frontend/src/features/quality/qualityModel.ts
