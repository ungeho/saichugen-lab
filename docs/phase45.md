# Phase45：Final Strategy Tournament & Research Closure

## 目的と基準版

最も有望な既存戦略を探索的に選び、結果が不明確でもこの大会で研究を一区切りとする。新戦略・停止規則・Rollout・ゲームルール・終局報酬を変更しない。Phase44確定SHAは `6e7d32e4f3acd2c154df059bef99b26fb79c6533`（通常commit/push済み）。Phase45は実装完了時に未ステージ・未commit・未pushで保持し、ユーザーの最終確定指示に基づき通常commit・pushする。

## 参加・除外（Validation前に固定）

Random、Heuristic、ScoreAware、hybrid_combined（版1、総予算64、最低1試行、全席Random継続、時間制限なし）。Hybrid代表は既存の登録combinedを単純規則で選ぶ。Validationや過去Validationの勝敗を選定に使わない。

Monte Carlo Rollout Fixed128は使用不能として除外。`strategies/monte_carlo.py` の通常戦略はMAX_TRIALS=64、128での生成を拒否する。一方、既存 `adaptive_analysis.select` のFixed128は研究用局面評価関数で、通常対戦の登録戦略ではない。これを新しい対戦戦略に変換したり64を128と表記したりしない。したがってFixed128を含むPilotは実行できない。残る最重の参加戦略で実測し、この大会はFixed128の優劣について結論を出さない。Gap/Uncertaintyは追加しない。

## Development Pilotと規模決定

開発配札45000・専用政策seed文字列18446744073709551045で、軽量3席0.008280秒、Hybrid1席0.439679秒、Hybrid3席1.287423秒。Pilotは性能選抜でなくコスト校正のみ。最終評価とは分離する。

4戦略の全20多重集合を重複のない全席順へ展開すると64試合/配札（4³の全割当）。各戦略48席出現/配札、相手2席の16順序構成が等頻度になる。同じ配札の同名戦略・席替え・構成違いを独立標本として数えない。完全対称の比較対象集合に対する成績であり、全ての相手・未知の戦略への絶対的強さではない。

予測は `2 × (48 × Hybrid3席時間/3 + 64 × 軽量3席時間)` = 42.257379秒/配札。保存や環境変動への2倍係数を含む経験的安全余裕で、確率的な完了保証ではない。結果を見る前に、全構成で12配札、予測507.089秒、時間上限600秒、派生対局上限600,000で固定する。上限見積もり552,960派生対局、シミュレーション手番上限4,423,680、予定768試合。

規模決定の規則は、全構成で予測600秒以内の配札数を最大12まで選ぶ。最低2配札が収まらなければ全同名と全異名だけの対称削減構成（8構成・28割当）に縮小する。これでも2配札が収まらなければ実行しない。今回の予測では削減不要。Validation開始後の追加・縮小・継ぎ足しはしない。

## 事前登録と独立性

Validation配札は1994000〜1994011の12個を指定する。既存research-local SQLiteの実験・予約・既存Hashを棚卸しし、seedと実配札Hashの重複を排除する。Pilot45000も除外する。調査外の外部DB・未保存実験の完全性は保証しない。Planには参加戦略版/設定、固定全席順、配札Hash、情報条件、ソースHash、規則/報酬版、予測/予算、終了判定を含める。評価用seedは戦略の観測へ追加しない。政策乱数は戦略名・同名複製番号で分離し、初期系列は構成間で共有するが進行後の乱数消費は一致を強制しない。

実戦は既存 `_play_game` と各席の `Game.observe`、既存registry factoryを利用。相手の実手札・未使用カード・将来札は戦略に渡さない。Hybridの詳細は計算量計測のため一回だけ生成し、候補表は直ちに捨て、判断時間・選択札・派生対局数・手番数のみ保存する。判断ロジックは不変。ゲーム進行の最終得点・勝者を確定してから既存terminal_rewardsを使用し、報酬は累積得点に加算しない。

## 統計と終了判定（実験前固定）

主指標は配札内の戦略全席の平均終局報酬、その後12配札を等重みで平均する。単独勝利・2人同点勝利・3人同点勝利・敗北・累積得点を別項目とする。全同点を2人共同勝利へ混ぜない。意思決定時間と参加試合時間は区別し、参加試合時間には相手の計算も含む。時点別の選択ランク平均は記述的傾向であり戦術の因果説明ではない。

各戦略平均と全6対比の配札対応差に、既存2000回配札bootstrapの探索的95%区間を付す。観測首位は選択の多重性を含むため、全6対比の同時保守境界も別に計算する。報酬差の幅8を用いたBonferroni-Hoeffding境界でA/B/Cを判定：A=観測首位が他の全戦略に対し下限>0、B=少なくとも一戦略のRandom差下限>0だが首位未確定、その他C=Randomに対する優位性未確認。厳しい境界なので小標本でAになりにくい。B/Cでも観測首位と最小実測判断コストの実用候補を示し、追加実験を要求せず終了する。

未完了なら完了配札・途中・未開始を区別し、主要ランキングと終了判定を確定しない。部分試合/計算量は保持し、結果選別による偏りに注意する。Timeout/Cancel/BudgetExceededは既存協調停止で、既存Hybrid一判断の途中には外部チェックを挿入しないため時間超過は一判断分生じ得る。派生対局は判断前に最悪64を確保し、安全側に打ち切る。対戦再開・自動再実行はしない。

## UI・API・CLI・保存

既存Runtime Noise & Decision Divergence Lab内のFinal Strategy Tournamentプリセットを使う。登録/開始/進捗/停止/JSON/履歴/直接URLは既存経路を再利用し、新トップレベル画面は作らない。結果に観測順位、対応報酬差、計算時間、構成と席順、研究終了判定を表示する。

`python -m strategy_arena.experiments.tournament_cli --config <JSON>` は見積もりだけ。既存CLIと同じ --register / --run ID / --database / --output を明示する。uint64政策seedはJSON文字列。既存ExperimentStoreを変更せず新kind final_tournament_v1の行と専用配札予約表に追記し、旧実験行は上書きしない。

以下に登録ID/Plan Hash、実測結果、検証・公開監査を追記する。

## 登録済みPlan

実験ID `fbd6b111-d8cb-40a5-b5a5-d666bc34e628`、Plan Hash `00242a1abfdf1ea902a3057915a8322c086ed653ce145503885a38815c0c8174`。新規専用DB research-local/phase45/tournament.sqlite に登録。ソース96ファイルを凍結保存し、両区分の政策seedを文字列で保存する。棚卸し842DB、1132既使用seed/実配札Hash、読取エラー0。既存1317DBのSHA-256を実行前に記録した。研究用の完全なPlan原本・結果JSON・Pilot・コードスナップショットは公開対象外。

## 実測結果（2026-10-15）

状態Completed、独立配札12/12、途中0、未開始0、全20構成・全64席順×12=768試合。実験wall291.078秒は600秒内、保守予測507.089秒の57.40%。試合wall合計261.390秒との差約29.688秒には進捗保存・ワーカー/読取競合などが含まれ、個別原因の分離測定ではない。実機はWindows 11 10.0.26200、Intel64 Family6 Model198 Stepping2 GenuineIntel、Python3.12.14。派生対局552,960、シミュレーション手番4,423,680、開始と完了の差0、予算/時間による中断0。

### 観測順位

各戦略576席出現、8640判断。ただし独立標本は12配札。以下の95%区間は配札bootstrapの探索的区間。

|観測順位|戦略|平均終局報酬|探索的95%区間|単独勝利率|2人同点勝利率|3人同点率|敗北率|平均累積得点|
|---:|---|---:|---|---:|---:|---:|---:|---:|
|1|hybrid_combined|0.432292|[0.340278,0.526042]|0.435764|0.071181|0.001736|0.491319|10.887153|
|2|ScoreAware|-0.116319|[-0.190972,-0.038151]|0.269097|0.053819|0.001736|0.675347|13.848958|
|3|Heuristic|-0.128472|[-0.208333,-0.053819]|0.262153|0.064236|0.000000|0.673611|13.671875|
|4|Random|-0.187500|[-0.303819,-0.064236]|0.236111|0.067708|0.001736|0.694444|11.126736|

### 全戦略間の対応比較

向きはA−B。同一の12配札平均を対応させる。Random・Heuristic・ScoreAware・Hybridの全6対比を掲載し、好結果だけを選ばない。

|A − B|平均報酬差|探索的95%区間|6対比同時保守境界|
|---|---:|---|---|
|Random − Heuristic|-0.059028|[-0.230903,0.130252]|[-3.881990,3.763934]|
|Random − ScoreAware|-0.071181|[-0.213628,0.071181]|[-3.894142,3.751781]|
|Random − hybrid_combined|-0.619792|[-0.815972,-0.409722]|[-4.000000,3.203170]|
|Heuristic − ScoreAware|-0.012153|[-0.168446,0.118056]|[-3.835115,3.810809]|
|Heuristic − hybrid_combined|-0.560764|[-0.661458,-0.461806]|[-4.000000,3.262198]|
|ScoreAware − hybrid_combined|-0.548611|[-0.690972,-0.406250]|[-4.000000,3.274351]|

Hybrid−Randomは+0.619792、探索的95%区間[+0.409722,+0.815972]。Hybrid−Heuristicは+0.560764 [+0.461806,+0.661458]、Hybrid−ScoreAwareは+0.548611 [+0.406250,+0.690972]。いずれもこの大会での正方向の探索的Evidenceである。一方、事前に固定した分布非依存の保守境界は広く0を含む。結果を見て判定基準をbootstrapへ差し替えない。

### 計算コスト

|戦略|判断平均ms|P95 ms|最大ms|参加試合平均秒|派生対局|シミュレーション手番|
|---|---:|---:|---:|---:|---:|---:|
|hybrid_combined|29.637384|34.822825|62.457400|0.672906|552960|4423680|
|ScoreAware|0.270717|0.425205|17.928600|0.230273|0|0|
|Heuristic|0.286103|0.476405|4.658900|0.230997|0|0|
|Random|0.001726|0.002800|0.036400|0.227228|0|0|

Hybridは約29.64ms/判断で軽量戦略より高コスト。Hybridの時間には計算量取得用の詳細メタデータ生成を含むため、通常のchooseだけの計測と同一ではない。Randomは約0.00173ms/判断で最小。今回、計算量は同一に揃えていない。参加試合時間は相手の判断も含む重複指標で、列を足して大会時間としない。

|戦略|序盤選択ランク平均|中盤|終盤|
|---|---:|---:|---:|
|hybrid_combined|6.719097|6.807292|7.032292|
|ScoreAware|6.923958|6.986458|7.001042|
|Heuristic|6.142361|6.568056|7.413889|
|Random|7.089236|6.697222|7.790972|

時点はturn0–4/5–9/10–14、各戦略各時点2880判断。ランクは既存Cardの数値でA=1。これは行動の記述であり、得点や勝因への因果寄与を意味しない。

## 研究終了判定と推奨

**C：Randomに対する優位性未確認として終了。** これは事前に定めた多重比較の保守基準による結論であり、「Hybridに改善の兆候がない」という意味ではない。探索的な実用候補は観測首位のhybrid_combined既定設定を推奨する。平均報酬+0.432292、Random差+0.619792で、この4戦略集合・12配札では最も有望だった。ただし安定した優位性・確定順位・未知相手への一般化は保証できない。最小コストを優先する場合の候補はRandomで、強さの推奨とは別に示す。

独立配札12という小標本、特定の4戦略から均等に構成した相手分布、単一の政策seed、単一CPU環境、順位選択と多重比較、Fixed128不参加が主な制限。今回の比較からFixed128や未参加戦略の強さを推測しない。結果にかかわらず追加配札・追加フェーズ・停止規則の改良は行わず、Phase45で研究を一区切りとする。

## 結果の再確認

原本はGit管理外の research-local/phase45/validation-result.json と tournament.sqlite。閲覧用 research-local/phase45/results_app.py はそのDBを指定する。既存開発DBへ実験行を移していないので、通常起動の保存履歴には自動混入しない。必要なら通常サーバー停止後、backendから `uv run uvicorn results_app:app --app-dir ../research-local/phase45 --host 127.0.0.1 --port 8000` と既存frontendの `pnpm dev` で閲覧できる。URLは `/research/runtime-divergence?experiment=fbd6b111-d8cb-40a5-b5a5-d666bc34e628`。GETやJSON exportで再実行しない。

将来研究を再開する場合は、新しい目的・未使用配札・事前固定した評価条件・別Planを用意し、今回のPlan/結果/終了判定を変更しない。Fixed128を参加させるなら、その通常戦略化は別途明示的な開発承認を要する。現時点では再開を要求しない。

## 対戦構成の実数

各席の入替は全unique順列。以下は12配札合計。全同名では1席順、2同名では3席順、全異名では6席順。

|3戦略の多重集合|席順数/配札|総試合数|
|---|---:|---:|
|Random / Random / Random|1|12|
|Random / Random / Heuristic|3|36|
|Random / Random / ScoreAware|3|36|
|Random / Random / hybrid_combined|3|36|
|Random / Heuristic / Heuristic|3|36|
|Random / Heuristic / ScoreAware|6|72|
|Random / Heuristic / hybrid_combined|6|72|
|Random / ScoreAware / ScoreAware|3|36|
|Random / ScoreAware / hybrid_combined|6|72|
|Random / hybrid_combined / hybrid_combined|3|36|
|Heuristic / Heuristic / Heuristic|1|12|
|Heuristic / Heuristic / ScoreAware|3|36|
|Heuristic / Heuristic / hybrid_combined|3|36|
|Heuristic / ScoreAware / ScoreAware|3|36|
|Heuristic / ScoreAware / hybrid_combined|6|72|
|Heuristic / hybrid_combined / hybrid_combined|3|36|
|ScoreAware / ScoreAware / ScoreAware|1|12|
|ScoreAware / ScoreAware / hybrid_combined|3|36|
|ScoreAware / hybrid_combined / hybrid_combined|3|36|
|hybrid_combined / hybrid_combined / hybrid_combined|1|12|

## 検証結果・公開監査・変更ファイル

Python pytest579件成功（177.24秒）、Vitest68件成功、Playwright全68件成功（4.0分）、TypeScript型検査・Viteビルド成功。最後のUI修正後もVitest/型検査/buildと関連E2E8件、独立した旧系列↔大会履歴切替E2Eを再確認した。Starlette/httpx非推奨・Vite bundleサイズ・Playwright色設定の既存警告は残る。

全768試合の一意性、12配札の集約、全席終局報酬と合計0、計算量、SQLite再読込、Plan/config/result Hash、凍結backend96ファイル一致を別途検証。ゲーム・戦略・Rollout・サンプラー・停止規則・本番保存実装・Phase40モデルは確定版と一致。既存1317DBのSHA-256不変。Phase38〜44の資料やPlanを変更していない。

公開候補348ファイル・変更11ファイルを監査し、秘密情報候補0。除去済み10資料は追跡/ステージ/main履歴に存在せずignore有効。research-local/、DB、ログ、取得資料、ローカル環境設定は公開候補外。新規ファイルを含む空白検査とgit diff --checkを実施。実装完了時はインデックスが空でPhase45のcommit/pushなし。最終確定ではこの11ファイルだけを明示的にステージし、通常commit・pushする。

変更はREADME、api/app.py、experiments/tournament.pyとtournament_cli.py、test_tournament.py、AdaptivePanel.tsx、NoisePanel.tsx、TournamentResults.tsx、tournament.test.ts、e2e/tournament.spec.ts、本資料。ゲーム本体や既存戦略は編集していない。UIは既存Lab内に統合し、大会の観測順位/構成/席順/対応報酬/計算時間/終了判断を表示する。旧系列との履歴切替でReactの状態呼出順を保ち、大会画面には追加研究用のDraft/Evidence操作を出さない。

今回の成果は、既存戦略のうちhybrid_combinedを探索的な実用候補として示し、確証的優位性は未確認という制限を残して研究終了できる状態である。追加実験や次フェーズは自動実行しない。

## 最終確定

ユーザーの指示に基づき、研究結論と実験結果を変更せず、コミットメッセージ「最終戦略トーナメントと研究終了判定を追加」で通常commit・pushする。確定前に全11ファイルが前回最終検証時のハッシュと一致することを確認したため、全件テストは再実行せず、公開監査・Plan/結果/凍結ソース照合・空白検査を再実施した。追加実験・戦略開発・機能追加・追加Phaseは行わず、研究を終了する。最終SHAはGit履歴と完了報告に記録する。
