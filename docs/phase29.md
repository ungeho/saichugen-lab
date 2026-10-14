# Phase 29：Middle-Position Decision Lab

## 目的と基準版

同じ公開局面で、目先の自己2位率、相手間得点差、中間順位の安全余裕、最終期待終局報酬という4つの目的を比較する。「厳密中間なら目先の2位率より得点配置を考える方が有利になる局面がある」は未検証の仮説として扱う。4規則はこのLabでの札選択規則であり、新しい実戦戦略としてレジストリへ登録していない。

Phase 28は `d0cb8dad37da9cea4cc71ce8fe4b44c6e2102682`、メッセージ「中間順位の層別分析と得点差比較を追加」で通常commit・pushした。公開前に前回監査時の14ファイルのSHA-256一致、公開対象・リモートmainを再確認した。force pushはしていない。Phase 29は未ステージ・未commit・未push。

[Phase 27](phase27.md)・[Phase 28](phase28.md)の探索結果を確証として扱わず、既存の実験行・Hash・条件は変更しない。Phase 28のSQLiteを別DBへバックアップし、既存18実験行のpayload SHA-256が実験後も一致することを確認した。ゲームルール、勝者判定、終局報酬、実戦戦略の挙動は変更していない。

## Safety Margin

自分S、相手A/Bについて、厳密中間は `min(A,B) < S < max(A,B)`。同点は含めない。

| 指標 | 式と意味 |
| --- | --- |
| upper_gap | max(A,B) − S |
| lower_gap | S − min(A,B) |
| minimum_margin | 厳密中間のときだけmin(upper_gap, lower_gap)。近い境界までの距離 |
| margin_balance | abs(upper_gap − lower_gap)。上下の非対称性 |
| signed_minimum_margin | 全状態でmin(upper_gap, lower_gap)。非中間では0以下の補助値 |

現在が非中間ならminimum_marginはnullで、正の余裕に変換しない。候補評価では次境界の得点分布から、厳密中間率と「中間だった世界に条件付けたminimum_marginの平均」を別々に保持する。中間世界が0件なら条件付き平均もnull。符号付き最小差の全世界平均、上下差の平均、条件付きmargin_balanceも補助情報として保存する。

Safety Marginは得点の距離であり、勝率・終局報酬ではない。特に残りラウンドで得点が変わるため、安全余裕が大きいだけで有利とは限らない。

## 4規則の固定定義

規則版は `four-objectives-v1`。今回の短期的な得点配置の評価時点は「現在のラウンドが終了して次ラウンドが始まる境界」。最終ラウンドでは終局境界になる。Phase 28の終局時の相手差変化も候補詳細に残すが、Gap-Controlの選択目的には次境界を使用する。

| 規則 | 最大化する値 |
| --- | --- |
| Self-Middle | 直近ターンで自己が2位になる確率 |
| Gap-Control | 次境界での相手2人の累積得点の絶対差の平均 |
| Safety-Margin | 次境界の厳密中間確率を優先し、許容幅以内の候補間で中間条件付きminimum_marginの平均 |
| Terminal-Value | 最終期待終局報酬 |

Safetyの「同程度」は `safety_tolerance` として事前登録する。既定0で推定確率が等しい場合のみmarginを使う。0〜0.1まで設定可能で、最大確率との差が許容幅以内の候補を残してからmarginを比較する。中間世界のない候補は補助値0としてタイブレーク対象にするが、全候補に中間世界がない場合に限るため、非中間に正の余裕を与えることはない。

最終的な同点はランク昇順・同ランクはスート昇順で固定する。ランダムタイブレークや独自の重み付き複合得点は使用しない。Gap-Controlの最大値が初期差より小さい場合もあり、その場合に「得点差を広げた」とは断定しない。margin_balanceは観察用で、選択得点へ混ぜない。

## 選択と独立評価

1. 本人のObservationから、全合法手を同じ世界標本・席別乱数初期状態で評価する。
2. その一つの候補表から4規則が選ぶ。規則ごとに別の予算を使わない。
3. 選択札・向きを固定し、選択とは別の世界seedで再評価する。同じ札を選んだ複数規則は計算を共有する。
4. 同一評価試行の報酬差から、Safety−Self、Gap−Self、Terminal−Self、Safety−Gapを計算する。

選択標本の最大報酬と独立評価の報酬を別欄に表示する。Terminal-Valueが選んだ札も推定誤差を持つ。同じ札の比較は同じ世界で同じ行動なので、差は恒等的に0、区間[0,0]。異なる札で観測差が0になっただけの場合は、区間を0に縮めない。

SelfとTerminalが不一致の局面を記録・絞り込みできるが、独立評価を不一致局面だけに限定しない。事前に選抜した全局面を評価する。これによって不一致検出と評価の選択バイアスを分ける。

## 公開情報と共通サンプル

Phase 28の収集、`evaluate_stratified`、`rollout_trial`、UniformSamplerを再利用した。実際の相手手札・余り札は探索へ渡さない。自分の手札、公開済み札、残り枚数、公開履歴に矛盾しない一様割当を使う。実配札Hashは識別用で、実手札を評価に使う経路ではない。

同じ試行番号で候補間の世界と席別乱数初期状態を共有する。分岐後のゲーム進行・乱数消費まで同じになる保証はない。継続戦略は選択・評価で同じ3席の設定を使い、各席自身の観測だけを渡す。探索戦略による再帰的rolloutは許可しない。

開発配札は0〜999999、独立評価の系列は1000000+validation_offset。policy_seedと局面Hashから `decision-selection:` / `decision-evaluation:` の別名前空間で世界seedを導出する。既存Arena・Design・Middleの予約との重複を拒否し、最終評価seedは使用しない。同じ条件を別DBで再現しても、新しい独立証拠とは数えない。

## 収集・層別・時点

Random、Heuristic、ScoreAware、Zigzag、Reverse Zigzagを3席に使った合法軌跡から、指定時点の全席を観測する。自作の得点配置や到達不能な局面を混ぜない。配札ID・実配札Hash・観測Hash・局面Hash・収集元・席・turn・ラウンド・seed区分を保持する。同じ局面はoriginsへ収集元をまとめる。

Phase 28の分類版 `strict-middle-v1`、小差5以下・大差10以上・均衡許容幅0を維持した。分析枠の巡回対象に均衡・上側接近・下側接近・両側小差・両側大差を含め、重なる局面を重複計算しない。配札・収集元の使用数を均し、turn12→11→13→14→9→6→3などの固定優先順で決める。対照は最高・最低・同点を巡回する。結果を見た局面選抜ではないが、母集団の無作為標本ではない。

既定収集時点はturn3・6・9・11・12・13・14。turn11は最終ラウンド直前の判断、turn12は最終ラウンド最初の判断で、累積得点の確定境界が異なる。収集した全時点に分析枠を保証せず、空の層を人工的に埋めない。

## 統計と不確実性

選択段階のfamily上限は `max_positions × (17 + 272×7)`、独立評価は `max_positions × (4 + 12×7)`。共通の既存固定標本Hoeffding境界＋Bonferroniを使用する。対応報酬差は絶対上限4とし、同じ試行の差から区間を計算する。独立区間を引き算しない。今回の少数世界では区間が広く、精密な順位付けに向かない。

配札集約では、同一配札内の分析局面の報酬差・一致率を平均し、配札を等重みで平均する。同一配札の複数席・時点・収集元を独立配札に数えない。最大20層×4対比を補正familyとし、世界標本数とは別に独立配札数を記録する。

既存統計関数は10標本未満なら区間を提供しない。現在の収集上限は8配札なので、配札集約の区間は「未算出」。候補別の独立世界評価（既定32世界）には区間を提供する。層別平均は探索的記述であり、選抜・少数配札・世界推定誤差を含む。配札間の一般化や因果効果を証明するものではない。

途中停止・時間切れは完了にせず、完了した局面だけを保存する。中断結果による確証判定はしない。上限は8配札、24分析局面、64選択世界、128評価世界、10000派生対局、120秒。実行前に未校正の上側時間見積もりも確認する。

## 小規模パイロット（2026-10-14）

固定設定：`experiments/presets/decision-pilot.json`。4独立配札11000〜11003、5収集元×3席×7時点、12分析局面（厳密中間9・対照3）、選択8世界、独立評価32世界、全席Random継続、Safety許容幅0。

実験ID：`a1b2a19c-de26-4cc9-b05c-bd8a8af2dd6b`。
登録Hash：`b38fe7f16c428683fa1e5f0f42aa8cda69da6cd6e091433adb436bf7384a334d`。
保存結果Hash：`d8ec3a66921650e0675956bfdac99729759ff746d21884944dc9b9c5b9d86638`。
表示結果Hash：`6a7a412ef5ce7e91f0db7f864b1f5f07266ac70d1ff78386792bc6d4bbdefc65`。保存値を読取時に表示用へ整形するため、保存結果Hashと区別する。

420局面を走査し、重複0、厳密中間86・最高86・最低86・同点162を収集した。厳密中間の型は均衡4・上側接近33・下側接近49、両側小差12・両側大差3。各収集元は84局面。以下は収集全体ではなく、選抜して評価した局面の結果。

| 層 | 分析局面 | 独立配札 | Safety−Self | Gap−Self | Terminal−Self | Safety−Gap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 全体 | 12 | 4 | −0.0990 | −0.1797 | −0.1354 | +0.0807 |
| 厳密中間 | 9 | 4 | −0.0404 | −0.1641 | −0.0951 | +0.1237 |
| 均衡 | 2 | 2 | 0 | 0 | +0.2969 | 0 |
| 上側接近 | 2 | 1 | −0.1875 | −0.1875 | −0.1875 | 0 |
| 下側接近 | 5 | 3 | +0.0208 | −0.3125 | −0.3229 | +0.3333 |
| 両側小差（重複タグ） | 3 | 2 | −0.0156 | 0 | +0.2812 | −0.0156 |
| 両側大差（重複タグ） | 1 | 1 | 0 | 0 | 0 | 0 |
| 最高（対照） | 1 | 1 | −0.0625 | −0.0625 | −0.0625 | 0 |
| 最低（対照） | 1 | 1 | −0.0938 | −0.0938 | −0.0938 | 0 |
| 同点（対照） | 1 | 1 | −0.6875 | −0.6875 | −0.6875 | 0 |

数値は独立評価の平均終局報酬の対応差を配札内で平均し、配札を等重み集約した値。すべて探索的な点推定で、配札単位の区間は未算出。小差・大差を接近型へ足して総局面数を数え直さない。

分析時点はturn11が4局面・2配札、turn12が8局面・4配札。最終ラウンド直前のSafety−Selfは−0.1875、Gap−Selfは−0.1719、Terminal−Selfは−0.0391。開始時点では順に−0.0208、−0.2786、−0.2786。異なる配札集合・少数局面なので、時点による効果差とは断定できない。序盤・中盤・turn13以降は今回の分析選抜に含まれず、成績はデータ不足。

規則別の平均終局報酬はSelf-Middle 0.4271、Gap-Control 0.2474、Safety-Margin 0.3281、Terminal-Value 0.2917。これはこの選抜局面・継続仮定の札評価で、戦略全体の対戦勝率ではない。

## 選択一致率

全規則一致は生の局面数で1/12。SelfとTerminalの不一致は10/12、厳密中間だけでは7/9。配札等重みのSelf/Terminal不一致率は全体83.3%、厳密中間79.2%で、単純な局面割合とは区別する。

| 組み合わせ | 全体の配札等重み一致率 |
| --- | ---: |
| Self / Gap | 25.0% |
| Self / Safety | 33.3% |
| Self / Terminal | 16.7% |
| Gap / Safety | 58.3% |
| Gap / Terminal | 58.3% |
| Safety / Terminal | 58.3% |

独立評価はすべての選抜局面で実施した。同じ札の規則間比較は差0と確認できるが、全48対比のうち異なる札の32対比では対応区間が0を除外できず、改善を確証していない。

## 失敗例とケースB仮説

診断は点推定条件と根拠を各局面に保存し、因果説明を自動生成しない。

- Self-Middle：独立評価でも直近2位率がTerminalより高く、報酬は低い例。今回は0局面。
- Gap-Control：独立評価でSelfより相手差が広がる一方、厳密中間率は低い例。今回は0局面。
- Safety-Margin：独立評価でSelfより中間率が高く、報酬は低い例。今回は2局面（厳密中間1・同点対照1）。カード温存への悪影響という因果機序までは測っていない。
- Terminal-Value：独立評価では他規則より報酬が低い例。今回は6局面（厳密中間3・対照3）。選択時の最大値と独立評価の違いを示す診断で、真の期待値を確定したわけではない。

Safetyの例：配札11002・席2・turn11、得点 `[0,1,5]`、局面Hash先頭 `204e91ea1313`。Selfは♣7、Safetyは♥10。独立評価の次境界厳密中間率は0.1875→0.4375、報酬は−0.09375→−0.15625。報酬差−0.0625の補正区間は約[−3.326,+3.201]で、0を含む。

Terminalの例：配札11000・席1・turn12、得点 `[1,18,0]`、局面Hash先頭 `5ef6c6ba6246`。選択時のTerminalは♠3、Safetyは♦9。独立評価ではTerminal報酬0.875、Safety報酬1.90625で、差+1.03125の補正区間は約[−2.232,+4.000]。こちらも優劣の確証ではない。

0件の診断は「その失敗が存在しない」という証明ではない。今回の結果はケースBの因果仮説を支持・棄却するものではない。GapとSafetyの選択目的、直近自己・相手確率、終局報酬を分けて追える基盤が整った段階である。

## 計算時間と再現性

収集20対局、選択512派生対局、独立評価864派生対局、合計1376派生対局。最初の全体時間は7.000秒、局面ごとの選択処理の合計約1.427秒、独立評価処理の合計約4.923秒。残りは収集・保存・集計など。Windows 11、CPU識別子 `Intel64 Family 6 Model 198 Stepping 2, GenuineIntel`。テスト・ビルドと並行した計測なので性能保証ではない。

同じ設定と同じ局面から12局面すべてを再計算し、計時を除く選択札、候補集計、独立評価、対応差、診断の一致を確認した。この確認は追加の独立標本として数えていない。

## UI・API・CLI・保存

上部「Middle-Position Decision Lab」から、見積もり→条件登録→Hash付き実行を行う。層・上下差・小差／大差・時点・収集元・Self/Terminal不一致で絞り込み、4規則を横並びに表示する。選択段階と独立評価の表、対応差と区間、診断例、公開履歴、本人手札、保存履歴、進捗・停止・JSON出力を確認できる。

`/api/decision/estimate`、`/jobs`、`/jobs/{id}`、`/export`、`/start`、`/cancel`、`/design-draft`、`/evidence`を追加。登録だけでは実行しない。SQLiteは既存ExperimentStoreを利用し、kind `middle_decision_v1` で既存結果と分ける。snapshotと結果Hashを検証し、改変された行はInvalidatedとして結果を隠す。中断結果はCompletedにしない。

Design連携は別条件のDraft作成、Evidence連携は参照保存のみ。条件付き世界をEvidenceの独立配札差へ統合せず、自動実行しない。

CLIは既定で見積もりだけ。リポジトリ直下のPowerShellから実行する。

```powershell
$env:PYTHONPATH = 'backend/src'
backend/.venv/Scripts/python.exe -m strategy_arena.experiments.decision_cli --config experiments/presets/decision-pilot.json
backend/.venv/Scripts/python.exe -m strategy_arena.experiments.decision_cli --config experiments/presets/decision-pilot.json --database research-local/my-decision.sqlite --register --output research-local/registered.json
# 登録結果の実験IDを指定。実行時も同じ設定ファイルが必要
backend/.venv/Scripts/python.exe -m strategy_arena.experiments.decision_cli --config experiments/presets/decision-pilot.json --database research-local/my-decision.sqlite --run <実験ID> --output research-local/result.json
```

パイロットのSQLite、JSON、ハッシュ監査、再現確認はGit管理外の `research-local/phase29/` に保管する。既存設定から継承したvalidation_trials等は互換用で、Phase 29の独立評価予算はevaluation_trialsを使う。max_validateは0に固定し、Phase 28式の一部ペアだけを検証する経路は使わない。

## 実装構成と検証

新規は `experiments/decision_analysis.py`、`decision_lab.py`、`decision_cli.py`、対応Pythonテスト、`frontend/src/features/decision/`、Playwrightテスト、プリセット、本資料。APIとmain.tsxに入口を追加した。

変更ファイル一覧（リポジトリ相対パス）：

```text
README.md
backend/src/strategy_arena/api/app.py
backend/src/strategy_arena/experiments/stratification_cli.py
backend/src/strategy_arena/experiments/stratification_lab.py
backend/src/strategy_arena/experiments/decision_analysis.py
backend/src/strategy_arena/experiments/decision_lab.py
backend/src/strategy_arena/experiments/decision_cli.py
backend/tests/test_decision_lab.py
frontend/src/main.tsx
frontend/src/features/decision/DecisionPanel.tsx
frontend/src/features/decision/decisionModel.ts
frontend/src/features/decision/decisionModel.test.ts
frontend/e2e/decision.spec.ts
experiments/presets/decision-pilot.json
docs/phase29.md
```

Phase 28基盤にはconfig_type・局面結果generator・集約関数の小さな差し替え点を追加し、ワーカー・収集・予算・停止・保存・参照処理を共用した。既定のPhase 28経路の選抜・評価条件は維持した。CLIも設定型とJobs型を引数化して共用している。既存ゲーム、報酬、戦略、サンプラー、統計関数の挙動は変更していない。

Python全345件、Vitest全36件、Playwright全40件、TypeScript型検査・Viteビルド成功。少数配札では区間を出さない既存仕様に新規テストの期待値を修正した後、Pythonを全件再実行した。既存の非推奨警告とバンドルサイズ警告は残るが、動作を妨げない。Windowsのsetup.ps1／dev.ps1は変更していない。

最終公開監査では追跡・追加可能な240ファイルを走査し、秘密情報候補0件、除去済み10パスの追跡・ステージなしとignore有効、PDF・取得画像・抽出テキスト・DB・ログの混入なし、旧mainの祖先混入なしを確認した。`git diff --check`と新規ファイルを含む末尾空白チェックも成功。変更15ファイルのHash・対象一覧は `research-local/phase29/final-audit.json` に記録する。Phase 29は未ステージで残す。パターン走査は未知の秘密情報を完全に検出する保証ではない。

## 制限と次の研究課題

- 4配札、選択8世界、評価32世界では探索誤差が大きい。Terminalが独立評価で劣っても、他規則の一般的優位性を意味しない。
- 局面・時点の選抜は確率標本ではなく、同一配札内に依存がある。層別平均を無条件に合算せず、配札単位の数を表示する。
- 今回の分析時点は最終直前・開始に偏り、序盤・中盤・最終途中の効果を比較するデータがない。時点別の分析枠を事前固定する追試が必要。
- Gap-Controlの評価時点は次境界。終局時の相手差を目的とする規則は別条件として比較する必要がある。
- Safetyの条件付きmarginは中間世界が少ないと不安定。確率優先を崩さず、許容幅・世界数の感度を別計画で調べる必要がある。
- サンプラーは一様割当で、相手の政策や行動傾向の事後確率を表さない。継続戦略による偏りも残る。
- 独立世界による固定札評価は、独立配札による一般化検証や、規則を毎手使用する実戦対局ではない。
- カード温存・未来の合法手への因果効果、ケースBの得点配置調整の機序は未測定。
- 同一規則の札を共有して計算を減らす一方、全候補のペア統計も既存処理で計算するため、将来の高速化余地がある。履歴一覧は全結果を返すため、多数保存時には軽量化が必要。
- 停止は協調式。進捗は処理ブロック数で、残り時間の正確な予測ではない。

次は、時点別の独立した配札、固定した複数の継続戦略、選択世界数を増やした条件を比較し、規則の選択がどこで安定するかを調べる。大規模な自動実験や最終評価seedの利用は行わない。
