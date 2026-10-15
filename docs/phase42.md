# Phase 42：Decision Divergence Coverage & Position Stratification

## 研究目的・Phase41の確定

Phase41は `3edd2b5ff84f5ba3ce692e9c55512d7dfdd31fdf`、メッセージ「適応探索の独立配札比較と判断分岐分析を追加」で通常commit・push済み。9ファイルは前回の531 Python / 61 Vitest / 64 Playwright成功・公開監査済み内容とハッシュ一致を確認した。

本Phaseは、Nの事前固定した自然抽出での判断分岐率と、Sの得点層別抽出による探索的発生条件を分ける。分岐0でも追加配札を探さない。Phase38のTimedOutやPhase41の分岐0を改変しない。

## 固定ゲーム・停止・評価仕様

ゲーム、合法手、報酬、既存戦略、Rollout、隠し手札サンプリング、共通世界、タイブレークは変更しない。Fixed128世界、Gap初期16/追加16/閾値0.5、Uncertainty初期16/追加16/全競合の対応差>2×SE+0.05、最大128を維持する。Reference16、Final16、selection/reference/finalの既存独立3ストリームを使う。最終Holdoutは未使用。

## Series Nの事前設計

6配札・各1局面。seed1991000〜1991005、時点割当は序盤・中盤・最終・最終・最終・最終（0始まり手番4/10/14）。収集元をRandom/Heuristic/ScoreAware/Zigzag/Reverse Zigzagの順にordinal%5、席をordinal%3で指定する。配札ごとのseed/収集元/席/手番tupleを満たす観測を採用し、得点・推定Gap・独立評価・分岐の有無は選択に使わない。重複観測に複数originsがある場合も、事前指定originへ投影して収集元と席を保持する。

1配札1局面、1選択反復、Random/Heuristic/ScoreAwareの3継続モデル、Fixed/Gap/Uncertaintyを対応比較する。5収集元の各15ターンを有限生成し、指定3手番の3視点を記録する。最大30収集対局、270候補観測。得点状態を見て配札を取り直さない。収集失敗は欠測として残し、Nの主要結果は未確定とする。

6配札で4時点すべてを含める案は、凍結予測の保守値が250秒を超えるため採用しなかった。直前時点はNでは未評価。Nの自然頻度は、この非一様な事前時点/収集元/席の混合に条件付けられ、ゲーム全局面の一様な頻度ではない。

## Series Sの事前設計

Nとは別seed1991100〜1991103の4配札・最大各1局面。配札順に、highest×中盤、strict_middle×最終ラウンド直前、lowest×最終ラウンド中、tie×序盤を各1枠指定する。手番は10/11/14/4。

同点分類は3人のどこかに同点がある場合をtieとする。全員異なるときだけ対象者をhighest/strict_middle/lowestへ分類する。相手同士の同点も単独順位層へ混ぜない。

5収集元・全3視点の有限候補から指定得点層に一致する観測を収集元順→席→Hashで1件選ぶ。推定値や分岐の見込みを抽出条件に使わない。最大20収集対局、240候補観測。各配札の目標層が見つからなければcollection_missingとし、別配札を探索せず、他の目標枠に転用しない。層別のrequested/attempted/selected/成功率を記録する。

Sの結果は探索的な選別標本。Nと混合せず、自然発生頻度を推定しない。全配札の有限収集が完了し、実際に選ばれた全局面が評価済みならSの処理完了とする。欠測を完全評価数に含めない。

## 予算・凍結モデル・配札独立性

Phase40のモデルHash `d7c08b175193cf6aa1593493ec9a0d8eddc5fb42c94aef1a1ef1740ad53fe3b9` を変更せず使用する。公開コピーは[phase40-frozen.json](../configs/calibration/phase40-frozen.json)。Nの予測143.067594秒/保守239.235004秒、Sは148.747932秒/保守243.910332秒。各250秒、派生対局上限N80,000/S60,000。事前派生対局上限はN52,224/S47,328。予測はSの全目標が見つかる最悪枠数を前提とし、実測後の成功数で事前予測を置き換えない。

payload4MiBは校正範囲外の警告を残す。Sの追加抽出管理コストは別校正しておらず、その警告も保存する。収集・抽出・保存を含む同じ時間上限で技術停止する。係数や安全係数をValidation結果から調整しない。

既存755DB・893seedを照合し読取エラー0、既存894DBのSHA-256を記録した。過去の全設定seed範囲・予約・実配札Hashを含み、Phase38の未開始/TimedOut配札も既使用とした。未保存・外部DB・未知の旧配札生成は完全保証できない。N/Sは別seed範囲、別Plan Hash、同じDBの配札予約チェックでも重複を拒否する。

## Development Pilot

別開発seed42000のN実行確認は4,896派生対局・2.547秒でCompleted。Sの収集のみ確認はseed42001〜42004、0.436秒で4目標すべて候補を取得し、派生対局0。Sの収集確認は研究用artifactとして保存し、将来の既使用seed照合に含める。Validationの配札は使わず、Developmentの報酬を見てN/Sの条件を変更していない。

## 分岐定義・説明可能性

同一局面/継続モデル/反復のFixedと異なる札が分岐。早期停止なし・分岐なし、早期停止あり・分岐なし、早期停止あり・分岐あり正/負/ゼロの5分類。早期停止なしで異なる札なら異常として記録し主要集約を止める。直接実行照合の既存assert_sameと合わせ、seed/共通世界/タイブレークを調査する。

選択時Gap、Gap符号、停止世界、候補表、停止理由とチェックポイント、Fixed128世界の候補表/順位、Gap変化、選択逆転、独立Final表と対応報酬差を保存済みEvidenceから取得する。選択時の推定値と、Fixedの追加世界・Finalの事後情報を分離する。Finalは選択処理へ渡さない。累積得点は公開局面の値、候補別の将来得点変化が未保存なら推測せずnullとする。Self-Middle差と負のRegretも保持する。

## 統計と完了条件

反復→局面内モデル→局面→独立配札の等重み。分岐配札数、分岐局面数、判断分岐率を別に数える。分岐なしも全体報酬/時間集約に含む。Nの分岐率区間は既存rate_intervalによる独立な[0,1]配札平均のHoeffding境界・2主比較Bonferroni（95%）であり、0件でも上限0にしない。独立性仮定が必要で、小標本では広い。Fixed自身との分岐率0は定義上の恒等値。

wall/報酬差とSの区間は配札percentile bootstrap（2000回、事前seed41001から比較名別に導出）。時点/収集元が固定配分された異質な少数配札の記述で、正式な被覆保証は主張しない。全差0の退化区間を同等性の証明としない。モデル・時点・得点状態・合法手数・収集元の層別は探索的。Sの層別区間から自然頻度を推定しない。

各系列の全配札収集・全選択局面・全3モデル/方式/反復・Reference/Final・対応直接計測・Plan Hash・両上限・SQLite保存を確認する。Nの欠測・異常分岐は主要未確定。Sは欠測枠を記録した処理完了と評価済み局面数を分ける。APIのseries_completedはその系列の全処理完了、primary_finalizedはNだけの主要確定。Sのprimaryは常にnull。片方の未完了でも他方の状態は書き換えない。

## UI・API・CLI・SQLite

既存LabにN/S別プリセット、Summary、Natural Divergence Rate、Stratified Coverage、Explorer、欠測・制限表示を追加する。独立Labはない。既存estimate/jobs/start/cancel/export/実験直接URL/noise_cli/SQLite JSONを利用する。新規スキーマ移行はない。SeriesをPlan/各評価局面/標準保存集計へ付け、Sの標準集計もexploratory_selectedとする。Nの層別はsecondary_exploratory。

派生coverage_evidenceは保存済み生Evidenceと固定設定からGET/export時に再現する。N/S混合集計は拒否する。Sの抽出欠測を0報酬や0分岐として補完しない。64bit導出seedは既存の十進文字列を維持する。通常起動は `powershell.exe -ExecutionPolicy Bypass -File .\scripts\dev.ps1`。

## 実測・回帰・公開監査

以下は保存済みの実測結果。分岐0でも事前配札数で終了し、追加探索していない。

### 再開時の保存状態確認

利用制限による中断報告後、登録ログだけで未実行と判断せず、SQLiteを読取専用で確認した。NはCompleted（6局面、150.703秒）、SはRunning（3局面まで保存、検証Pythonプロセス生存）だった。登録時snapshot/configの完全一致を確認し、再登録・再実行・回復処理を行わず既存ワーカーの完了を待った。Phase41のHEAD/origin/mainは3edd2b5で一致。Phase42は8ファイルの未ステージ変更で、登録済み両Planは変更していない。

### 登録済みPlan

|系列|実験ID|Plan Hash|
|---|---|---|
|N|f142e6eb-c4fe-47f4-bb57-4d1e5b922851|8dbebe93346d1818855962faf859baf19cce9578aa7b81bdb130f80afcbaa1bb|
|S|7bf91ba0-d350-4d17-8cd5-342fe3636c26|335edaae747ae26ecc6ba2a385e024367943b9f2d017308c467cbcdae0c357fb|

両方をN開始前に登録。条件HashはN `12d73502ffa4fbe13f4190d93853ebc1dc3733744e4e2df3bc1970c021fe3b76`、S `09a1f25b8d6a899ab604e4206e32b6b18e1a62b2d08d444c54f78f1cf9968711`。これはPlan Hashとは別。登録/凍結設定/生結果/実行時ソースはGit管理外のresearch-local/phase42に保存する。

### Nの保存済み結果

Completed、6独立配札・6局面・3モデル・各方式18判断。収集欠測・部分・未開始・異常分岐0。52,224派生対局（policy49,152 / Reference1,536 / Final1,536）、150.703秒で両上限内。平均予測に対して+7.635秒（+5.337%）、保守239.235秒を超えなかった。

|方式|分岐判断/全判断|早期停止|wall差秒（95%探索的bootstrap）|独立終局報酬差|
|---|---:|---:|---|---|
|Gap|0/18|0/18|−0.00756697 [−0.04389867, +0.02324435]|0 [0,0]|
|Uncertainty|0/18|0/18|−0.02424773 [−0.06816632, +0.01972169]|0 [0,0]|

両方式の分岐配札0/6・分岐局面0/6・分岐率0、独立配札の有界平均境界は[0,0.60429205]。判断18を独立標本として使わない。全件128世界で同じカードなので、報酬差0は観測カード一致に由来する。wall差区間は0を含み、早期停止による高速化とは解釈しない。

時点：序盤1・中盤1・最終4、直前0。得点状態：highest2・strict_middle2・lowest1・tie1。全方式のSelf-Middleとの差+0.18055556、符号付き推定Regret−0.08333333。負のRegretを0に切り詰めず、独立参照/Finalの標本誤差を含む値として扱う。分岐例・分岐時の正/負/ゼロ・早期停止後順位逆転の例は各0件で、架空の具体例を作らない。

### Sの保存済み結果（探索的）

Completed、4収集配札・4完全評価局面。highest/middle、strict_middle/before_final_round、lowest/final_round、tie/earlyの各目標1/1、抽出成功率各100%（各1枠しかない）。欠測・部分・未開始・異常0。46,032派生対局（policy43,248 / Reference1,392 / Final1,392）、154.359秒で両上限内。平均予測に対して+5.611秒（+3.772%）、保守243.910秒を超えなかった。Nから条件を変更せず、全選択局面で128最大経路と独立参照/最終・全方式直接計測を実行した。

|方式|分岐判断/全判断|早期停止|wall差秒（探索的95%bootstrap）|独立終局報酬差|
|---|---:|---:|---|---|
|Gap|0/12|2/12 (16.667%)|+0.02300426 [−0.06359147,+0.13296143]|0 [0,0]|
|Uncertainty|0/12|2/12 (16.667%)|+0.05674582 [−0.04195642,+0.22763544]|0 [0,0]|

両方式とも分岐配札0/4・分岐局面0/4。早期停止2件はlowest×最終局面内の3モデル中2モデルで、残る3得点層は各0/3。各層の分岐判断0/3・報酬差0。Sの0率/bootstrap[0,0]は選別標本の記述に限定し、自然頻度や将来の同等性を示さない。series_completed=trueだがprimary_finalized=false/primary=nullとし、selected_sample_summaryだけを公開する。

全方式のSelf-Middle差+0.171875、符号付き推定Regret−0.01041667。分岐0なので分岐時正/負/ゼロは0/0/0、具体的な順位逆転例は未観測。全判断Evidence（分岐なしを含む）は保存する。得点状態を選別したため、Nの6配札と合算して10配札の自然率や効果を推定しない。

### 解釈・Phase43への提案

両Planの技術的完了を確認できたが、適応停止の有効性を確証した実験ではない。Nは早期停止も未観測、Sは2判断ずつ早期停止したが同じカードで、wall差の区間は両方式とも0を含む。単独トップ層を観測できたが、1配札だけでは層の一般的な特徴を推定できない。Nは最終局面を多く配分し、Sは得点層と時点を一対一に割り当てたため、得点効果と時点効果を分離できない。

Phase43では、今回の0分岐を理由に配札を追加せず、新しい事前Planで時点×得点層の交絡を解く開発設計を検討する。予算校正範囲外の保存負荷・追加収集管理コストを別のDevelopmentで測る、複数の同条件非重複Planを統合する際の階層的集計・区間被覆を検証する、独立参照16/Final16の標本誤差を固定基準で点検することが候補。係数更新や停止規則変更は別研究として扱う。

1Plan上限8配札、採用最低20配札、最終Holdout未使用を維持する。本Phaseから採用・強弱・同等性を断定しない。独立性は記録済みseed/実配札Hashに対する確認範囲であり、外部/未保存履歴の完全検出は保証しない。凍結校正環境が異なる場合、登録は既存チェックで拒否する。DB・生Evidenceはローカルのみで、新規cloneには自動配布しない。

### 早期停止したが分岐しなかったEvidence

Sのlowest×最終局面（Random収集）のRandom継続は、Gapが16世界・Gap0.5625、Uncertaintyが32世界・Gap0.84375で停止した。128世界の最終Gapは1.0078125。ScoreAware継続は両方式16世界・Gap1.125で停止し、128世界の最終Gapは0.515625。いずれも♥9を選び、128世界でも順位1位。追加標本でGapは増える場合と減る場合があるが、今回は選択札は逆転しなかった。これらの128世界特徴と独立Finalは事後分析で、停止時の入力へ戻していない。

### 実装ファイルと互換性

- backend/src/strategy_arena/experiments/divergence_coverage.py：N/S抽出、厳密得点層、欠測/異常/完了監査、配札単位Evidence。
- backend/src/strategy_arena/experiments/noise_lab.py：Phase42設定・Plan・既存ワーカー/保存/API結果への接続。
- backend/tests/test_divergence_coverage.py：14ケース（得点同点、選択不変、origins投影、系列分離、欠測、異常、再読込など）。
- frontend/src/features/noise/NoisePanel.tsx：既存Lab内のプリセット、系列別SummaryとExplorer、条件・不確実性の表示。
- frontend/src/features/noise/noise.test.ts：安全なN/S初期設定。
- frontend/e2e/divergence-coverage.spec.ts：実APIの両Plan、N/S表示分離、直接URL/再読込/狭幅画面。
- README.md、docs/phase42.md：日本語の利用案内・設計・実測・制限。

noise_cliは既存config/estimate経路でN/S凍結設定を読み込めることを確認した（再登録・再実行なし）。旧SQLiteスキーマやPhase38〜41の生記録は更新しない。新規DBへの移行、分散ジョブ、任意コード実行は追加しない。


### 回帰検証・公開監査（2026-10-15）

|検証|結果|
|---|---|
|Python pytest|545件成功、142.95秒|
|Vitest|62件成功|
|Playwright|65件成功、3.1分、Phase42実APIテストもskipなし|
|TypeScript / Vite|型検査・ビルド成功|
|CLI|N/Sの既存見積もりコマンド成功、再実行なし|
|空白検証|git diff --checkと未追跡新規ファイルの個別検証成功|

既存のStarlette/httpx非推奨警告、Vite 500kB超のバンドル警告は残る。ゲーム・報酬・戦略・Rollout・サンプラー・停止/独立評価の実装を変更していない。実験時バックエンド87ファイルと現在のバイト一致、原Phase40モデル/公開コピー/両Plan内の係数・Hash一致、両登録snapshot/configの不変性、SQLite生Evidenceからの派生結果完全一致を確認した。

測定環境はWindows 11（10.0.26200）、Intel64 Family6 Model198 Stepping2 GenuineIntel、Python3.12.14。N→Sを直列実行し、全件回帰テストは両実験終了後に行った。全体経過は既存monotonic、直接処理区間は既存perf_counter系を維持し、負の未計測残差を0へ切り詰めない。

公開候補324ファイル・変更8ファイルを監査し、秘密情報候補0。除去済み10パスは追跡/ステージ/main履歴に含まれず、ignore有効。research-local、第三者資料、ローカルDB、ログ、環境設定、生成Evidence/画面画像を公開対象へ追加していない。既存894DBのSHA-256は不変、今回複製DB内の他実験44行は各系列実行前後で一致した。Phase38〜41のドキュメントも変更していない。

ローカルmain・origin/main・GitHub mainはいずれも `3edd2b5ff84f5ba3ce692e9c55512d7dfdd31fdf`。旧mainはmainの祖先ではない。Phase42のステージは空で、commit/pushしていない。専用E2Eサーバーは停止し、8000/5173の待受が終了したことを確認した。研究DB・元資料・バックアップは削除していない。
