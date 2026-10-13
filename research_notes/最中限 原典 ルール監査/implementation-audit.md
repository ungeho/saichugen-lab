# 現行実装・テスト・ドキュメント監査

## 現在の実装は何をするか（A〜F）

### Takeaway
2026-10-13に現行ソースを読んだ。得点の3段階は、ターン数字のラウンド内蓄積、ラウンド中央値の者だけへの自身のラウンド得点の加算、最終合計の中央値による勝者判定である。終局で加点・再配分・ボーナスを行う処理は存在しない。以下は実装の事実であり、原典での正当性はWeb調査担当の証拠と別に評価する。

### Cited Findings
すべてのパスはリポジトリルート相対。行番号は2026-10-13現在。

|項目|実装の事実|実装根拠|既存ドキュメントの出典主張（独立再検証前）|
|---|---|---|---|
|A 人数・デッキ|3人。1〜13×4スート=52枚。ジョーカーなし。全52枚が重複なく3×17枚+余り1枚であることを初期化時に検証|[cards.py](../../backend/src/strategy_arena/game/cards.py):12–30、[engine.py](../../backend/src/strategy_arena/game/engine.py):13–24|GPCC一次要約、二次資料共通|
|A 配札|Python Random(seed)でshuffle、cards[p:51:3]を各席へ17枚ずつ、各手札をカード順にsort、cards[51]を余りとして内部保持|cards.py:27–30|シャッフル詳細とseedは実装選択。裏向き余り除外は二次資料|
|A 進行|3ターン×5ラウンド=15回。毎ターン各席から1枚。使ったカードを手札から除去。再配布/交換なし。各2枚残して終了|[rules.py](../../backend/src/strategy_arena/game/rules.py):5–7、engine.py:33–38,47–66|GPCC要約/二次資料|
|A 提出・合法手|自分の未使用手札全体が合法手。スートフォロー/リード/先手なし。APIとrunnerは全席の観測を先に作り、その後席順にchooseを計算、最後に3枚を一括適用。順次計算≠公開の逐次提出|[observation.py](../../backend/src/strategy_arena/game/observation.py):27–29、[api/app.py](../../backend/src/strategy_arena/api/app.py):229–246、[runner.py](../../backend/src/strategy_arena/experiments/runner.py):25–34|裏向き提出は二次資料、同時選択・自由提出はその解釈、同時公開は承認仮仕様|
|B 数字/スート|Cardがfrozen dataclass(order=True)、フィールドrank,suit順で辞書式比較。A=1→K=13。数字優先。同数字は♣=0<♦=1<♥=2<♠=3。異なるカードは全52枚で全順序となりturn同点なし|cards.py:7–20、rules.py:17–20|二次資料による暫定採用。GPCCの省略から原典一致とはいえない|
|C カード中間|3枚distinctを検証、カード順でsortした席indexの中央を唯一のturn winnerとする。同数字でもsuitで解決|rules.py:17–20|数字/suit根拠は二次資料、カード中位獲得はGPCC|
|C 得点中間|sorted(scores)[1]と等しい席をすべて返す。得点順序で勝者を一意化しない|rules.py:10–14|二次資料の同点共同勝者を一般化|
|D ターン得点|R[winner]+=selected_card.rank。非勝者は0加算。スートは数字点へ影響しない。game得点はround末以外不変|engine.py:52–59|GPCC/二次資料|
|D ラウンド得点|3回目のturn数字加算を先に行い、そのラウンド3turn合計Rを比較。game[p]+=R[p] iff R[p]が中央値。他席は0加算。ラウンド得点は次の観測で全員0に戻る|rules.py:23–25、engine.py:53–65|GPCC/二次資料に基づく実装。全員のR合計やround勝利数を加える処理ではない|
|D 最終得点|5回の上記加算合計Gを保持。15回目にも通常round加算が1回ある。追加ボーナス/勝者への得点総計の再加算/敗者ゼロ化/残り2枚の得点は一切ない|engine.py:33–38,55–65|現行実装事実。二次資料の終局表現との厳密な対応は未確認|
|E 同点|2人が同じ得点ならその値は必ず中央値なのでその2人がwinner。3人同点なら全員winner。0同点も同様で、round加算は0。勝利分割/席順優先/別のdraw列なし|rules.py:10–14,23–25、engine.py:37–38|二次資料暫定採用|
|E 集計|共同勝者各人を1勝、勝率合計100%超え可。branch順位は高得点順のbest=1+#higher、worst=3−#lowerで占有範囲表示（1、2、3、1–2、2–3、1–3）。中間勝利と通常順位は別|[metrics.py](../../backend/src/strategy_arena/experiments/metrics.py):summarize、[branch_simulation.py](../../backend/src/strategy_arena/branch_simulation.py):64–69|ゲームルールと実験指標の区別が必要|
|F 通常観測|自身のhand、PublicTurn全履歴、round_scores、game_scores、turn、各席hand_sizesのみ。legal_actions/unseen_cards/actions_byはこれらから算出。seed・余り・敵手札・完全Game参照なし|observation.py:8–40、engine.py:40–45|承認済み仮仕様|
|F 通常API|P1=内部player0視点。相手decision details/contextを伏せる。公開済み実行カード/explanation/その他decision指標は残る。分析trueでも終局前は詳細を伏せる|api/app.py:106–121|プロジェクトUI仕様|
|F 終局分析|終局かつ明示analysis時に相手当時decision詳細/contextを返す。比較履歴で他席視点を許す。同席自身の観測として渡すのでStrategyには依然imperfect。終局通常APIで相手残り手札を直接出さないが、分析履歴の過去handと実行カードから推論可能|api/app.py:112,165–167、[comparison.py](../../backend/src/strategy_arena/comparison.py):position_at|承認された可視化用拡張。対戦時非公開と終局分析を混同しない|
|F 完全リプレイ|研究用export_fullはinitial_hands全席・unused・actionsを保存。通常公開APIの研究export経路はなし。replayはrule/visibility/schema版を厳密一致チェックし旧版を拒否|[research/replay.py](../../backend/src/strategy_arena/research/replay.py):8–29、test_api.py:test_no_research_route|プロジェクト研究データ仕様|

得点式：ラウンドr、ターンt、席pの数字点を v(r,t,p)=rank(card) if p=middle(cards) else 0 とする。R(r,p)=Σ[t=1..3]v(r,t,p)。A(r,p)=R(r,p) if R(r,p)=median(R(r,*)) else 0。G(p)=Σ[r=1..5]A(r,p)。W={p:G(p)=median(G)}。勝利後Gを変更する項はない。現在のAPI/保存/分岐のscoreはこのGそのもの。

履歴の重要差：ラウンド終了イベントPublicTurn.round_scoresはリセット直前のR、同イベントgame_scoresは加算後のG。直後Game.observe.round_scoresは0。両者が異なるのは正しい。終局のobserve.round_scoresも0で、最後の3turn合計はhistory[-1].round_scoresにある。[engine.py](../../backend/src/strategy_arena/game/engine.py):60–65。

### Inferences
- 原典に終局追加得点があるとしても、それが次ゲームの持越し/報酬値/ランキング用なのか、現在の1ゲーム勝者を再判定する点なのかはソースなしで推測しない。今あるGとWの式を提示して照合するのが安全。
- ターン得点は正の1〜13なので3turnのR=(0,0,0)は有効プレイでは生じない。しかしG=(0,0,0)の終局は有効配札/プレイで生じる。純関数への0同点入力と到達可能局面を区別すべき。
- 最終Gが同点の2人なら、得点の高い側か低い側かに関係なく2人とも勝者。順位分布で1–2位/2–3位とも勝ちうる。
- 終局分析でturn0手札全席を選択できるため、合計51枚から余り1枚も推定できる。通常Strategy経路の非公開と研究閲覧経路の公開を区別する必要がある。「終局後も何らかの方法で知れない」とは言えない。

### Gaps
- 上表の資料根拠は既存docsの記述の抽出であり、私の担当ではWeb本文を独立検証していない。資料調査担当の一次証拠で更新すること。
- arbitrary Python戦略をセキュリティ隔離する設計ではない。明示的引数の非漏洩は確認できるが、自発的なファイル読出し等を防ぐ機構はない（architecture.mdも明示）。

## ドキュメント・テスト・境界の整合性はどうか

### Takeaway
得点/順序/同点/終局に関して現行current-rulesとソースの明白な不一致は見つからなかった。過去の設計案やREADMEに古い記述があるが、挙動の修正ではなく記述上の整理候補。テストは実装の一貫性を強く確認するが、原典との一致の証明ではない。

### Cited Findings
- [README](../../README.md)「同一局面比較」末尾に「分岐シミュレーション未実装」が残り、後半「同じ局面から分岐シミュレーション」の実装済み説明と矛盾。今回writerが修正する場合、理由は既存機能の記述更新と明記する。
- [architecture.md](../../docs/architecture.md)は明示的に構成案だが、state.py/game/replay.pyは実在しない（実際research/replay.py）、API「本人向け観測のみ応答」は終局分析を省略、コードrevision/実行環境/モデル識別子全保存等は実装目標で全部保存されているわけではない。エンジン/Strategy境界の説明はおおむね一致。
- [current-rules.md](../../docs/current-rules.md)には同時選択・自由提出は現在の解釈、同時公開は承認済み仮仕様、終局追加処理原典未確認、分析表示例外を明示。原典全文未確認という冒頭記述も整合。
- [rules-research.md](../../docs/rules-research.md)のGPCC一次資料分類は「原典全文ではない」注意付き。新たな証拠が見つかれば、以前本文未取得だったという経緯を残して現状更新する。原典/著者原案/GPCC紹介/研究モデルを混同しない。
- [test_rules.py](../../backend/tests/test_rules.py):100seed配札保存、全52順序、全C(52,3)=22100組のカード中間、中央値tieの5入力（上側2人/下側2人/全員4点/0同点）、invalid rank/suit/bool/duplicateを検証。
- [test_engine.py](../../backend/tests/test_engine.py):50seed15turn+全prefix replay、全round reset、終局hand2枚/合法手空/追加play拒否、独立履歴計算との得点一致(seed10)、invalid action非破壊、Observation不変と敵手札swap非干渉、全turn全席の未知カード数35−2tと一様sampling構成を検証。
- [test_rule_guide.py](../../backend/tests/test_rule_guide.py):表示定数・ランク/suitとengine整合、固定カード例5、rank1/7/13のsame-rank3枚全提出順、実3turn例(8,8,3)・(0,0,12)、純関数最終例4、APIサンプルと対戦非変更を検証。test_published_card_examplesという名前だが例は資料掲載例ではなくプロジェクトで作った人工例（writerは「資料由来」と解釈しない）。
- [test_branch_simulation.py](../../backend/tests/test_branch_simulation.py):14件。サンプルworld/同seed/状態非変更/共有rng/継続設定/統計tie/入力/timeout/cancel/失敗/最終tieの既存回帰を含む。
- 実行結果：`backend/.venv/Scripts/python.exe -m pytest backend/tests --basetemp=backend/.test-tmp-audit-verified` → **77 passed, 1 warning in 1.69s**。既存httpx→httpx2のTestClient非推奨警告のみ。初回sandbox内実行はTestClient付近で停止し中断、通常権限で上記再実行成功。テストコードは変更なし。
- backend/srcの全.pyおよびfrontend/src全ファイルのSHA256 baselineを同ディレクトリbaseline-hashes.jsonに保存。ゲーム/戦略/API/UI/分岐の非変更を作業後比較可能。

### Inferences
推奨する今後の追加テスト（今回追加不要）：
1. Game.from_dealのinvalid人数/17枚でない/重複/欠落/余り重複の明示ケース（実装は検証するが専用テストなし）。
2. median_players長さ!=3、turn_winner長さ!=3の明示テスト（現在duplicateはある）。
3. round全員同点(4,4,4)を純関数だけでなく有効な3turnで実現した統合テスト。
4. 全15turn同席winner→終局G全員0の統合テスト、終局のwinners取得によってG不変の明示テスト。
5. ラウンド境界直前/直後のPublicTurn.RとObservation.R差を明示したテスト。現状resetはテスト済みだが最終eventR値の期待値検証は限定的。
6. engine observer current合法手の15hardcodeとrules終了定数3×5の同期テスト（現在ルールページconstantテストで現状15を確認するが将来ルール変更時の漏れ候補）。
7. 「最大/最小点」を決め打ちで追加しない。ラウンド中央値は独立したR各最大39から単純に全員39と置けず、3turn/52unique制約で到達可能性が変わる。

### Gaps
- 今回Vitest/Playwright/buildは未実行。監査は文書のみでPython現状確認が主。77件成功が原典一致を検証するわけではない。

## エンジンで再現した具体例と変更影響

### Takeaway
下記はすべて現行エンジンで実行した人工例で、資料の対戦例や原典の期待値ではない。Gの途中蓄積と終局Wは独立して確認できる。

### Cited Findings
人工例1（[rule_guide.py](../../backend/src/strategy_arena/rule_guide.py):round_example / rule_guide）：開始R=G=(0,0,0)。

|turn|P1|P2|P3|中間|加算後R|G|
|---|---|---|---|---|---|---|
|1|♣8|♣K|♣A|P1♣8|8,0,0|0,0,0|
|2|♦A|♦8|♦K|P2♦8|8,8,0|0,0,0|
|3|♥A|♥K|♣3|P3♣3|8,8,3|8,8,0|

round勝者P1,P2、game加算(8,8,0)、次obsR=(0,0,0)。1roundのみなのでゲーム未終了、Game.winners=()で最終勝者まだなし。手札の残りを全deckからuniqueに補充しGame.from_dealで有効52枚配札として実行する。

人工例2：開始R=G=0、提出(♣A,♣K,♣2)、(♦A,♦K,♣4)、(♥A,♥K,♣6)。P3が2,4,6を得てR=(0,0,12)。round中央値0のP1,P2が勝者だがG加算0。次obsR=0。資料由来期待値なし。

人工例3：`Game(0)`を作り毎turn全席で最小hand[0]を提出。開始G=0、実際の15turnログは以下。P表記は画面1基準。

|turn|提出P1/P2/P3|中間席|R（round内累計）|G|
|---|---|---|---|---|
|1|♥A / ♥2 / ♣A|P1|1,0,0|0,0,0|
|2|♠A / ♣3 / ♦A|P1|2,0,0|0,0,0|
|3|♣2 / ♥3 / ♠2|P3|2,0,2|2,0,2|
|4|♦2 / ♣4 / ♦3|P3|0,0,3|2,0,2|
|5|♠3 / ♠5 / ♣5|P3|0,0,8|2,0,2|
|6|♦4 / ♥7 / ♦5|P3|0,0,13|2,0,2|
|7|♥4 / ♣9 / ♣6|P3|0,0,6|2,0,2|
|8|♠4 / ♦9 / ♦6|P3|0,0,12|2,0,2|
|9|♥5 / ♠9 / ♥6|P3|0,0,18|2,0,2|
|10|♠7 / ♣10 / ♠6|P1|7,0,0|2,0,2|
|11|♣8 / ♦10 / ♦7|P1|15,0,0|2,0,2|
|12|♥8 / ♥10 / ♦8|P1|23,0,0|2,0,2|
|13|♠8 / ♥J / ♠10|P3|0,0,10|2,0,2|
|14|♥9 / ♠J / ♣J|P3|0,0,21|2,0,2|
|15|♦J / ♣Q / ♦Q|P2|0,12,21|2,12,2|

最終G=(2,12,2)、Game.winners=(0,2)=画面P1/P3。P1/P3は通常得点順位2–3位同点だが中間共同勝利。終局obsR=0、全員hand2枚。追加ボーナスなし。

人工例4（全turn同winner）：`cs=deck(); Game.from_deal((cs[:17],cs[17:34],cs[34:51]),cs[51])`、各turn全員hand[0]。毎turnP2中間となる。roundRは(0,15,0)、(0,18,0)、(0,20,0)、(0,22,0)、(0,24,0)、各roundgame加算0。最終G=(0,0,0)、全員共同勝利。deck()順はrank昇順・suit昇順。資料由来の期待値ではないが有効配札・使用枚数制約を満たす例。

変更時の影響（提案のみ）：
- スート/数字順：Card比較、turn_winner、heuristicのunknownより下/上カウント、手札sort、decision例、全22100組テスト、対戦/分岐統計、replay期待値、UI順序表。
- turn点/round点/終局点：Game.play/winners、round_awards、戦略の得点目標、公開履歴得点、比較snapshot hash、branch復元validation/rollout/wins/rank、SQLite scores/過去成績の非混合、例、goldenfixture。終局追加「点」が勝者判定後の別報酬ならGを書き換えるより別フィールドの設計を先に確認。
- 同点：median_players/round_awards、共同勝利rate、CI定義、branchrank別表示、統計win_definition、UI説明、全ゼロ例。
- ターン数/配札：rules定数だけでは足りずObservation.legal_actions=15、runner.metrics divisor15、Game._initialize17/52、samplercounts、branchvalidation、UIターンbounds、APImax14/hand17、Replay/比較snapshot各versionを確認。
- 公開：Observation/unseen_cards/UniformSampler/Strategy、API分析条件、ログredaction、比較positionhash、サンプリング仮定を改版。
- 既存version保存：実験APIはrule_version+info条件+戦略version+Python版をJSON payloadとしてSQLiteへ保存。完全Replayはrule/visibility/schemaを保存して旧版拒否。branchはposition.rule_versionを保持、sampler/state_policy/name/versionを保持、永続保存はなし。改版時は旧結果を同一条件で集計しない。公開仕様versionは実験payload独立項目には未記録（imperfectとrule_versionだけ）なので将来追加候補。資料出典を訂正するだけで挙動不変なら、挙動RULE_VERSION変更が必須とは限らず監査revisionを分ける提案が適切。

### Inferences
ルール変更判断の前に、終局追加得点の目的・加算先・勝者再判定の有無を原典/研究資料から特定すべき。今回コード変更不要という指示を守り、疑義は監査の変更候補へ記録する。

### Gaps
原典の期待値を持つ具体例は私の担当資料にはない。Web調査担当の発見があれば人工例と明確に分けて追加する。

追記（親調査から得た2003年本文の証拠に対する実装影響。本文を私自身は未閲覧）：p32 §3.2(5)で5round合計のmedianから勝者を確定し、(6)とp33表2で終局報酬を与えるとのこと。3勝者なら全員0、2勝者なら勝者各+1/敗者−2、1勝者なら勝者+2/敗者各−1。この表2報酬とGを区別すること。

現行Game.winnersは手順(5)に対応するが、手順(6)の独立した符号付き終局報酬フィールドを保持しない。現行experiment.scores、SQLite成績average_score、branch.average_score/score_std/average_score_difference/順位分布、rule_guide final_examplesはすべて非負のGに基づき、表2報酬の平均や分散ではない。現行win_rateは手順(5)の勝者に基づくため、表2を後から別指標として計算しても勝率自体は変わらない。しかし表2の期待報酬と勝率は同じ最適化目標ではない（1人勝ち+2、2人勝ち+1、3人勝ち0が区別される）。Greedy/ScoreAware/Heuristicは現行G/Rの中央値を考慮しており、終局表2報酬の最適化を明示しているわけではない。特に全員0のGで全員勝者を1勝とする勝率指標と、表2全員0報酬は意味が異なる。

将来の変更候補は別のterminal_payoffs等を計算・記録・表示し、Gを判定用のround-totalとして保持すること。Gへ表2を足して勝者を再判定すると手順(5)→(6)の順序を壊すので推奨しない。現行保存resultsのwinnersだけでも表2報酬は復元可能だが、資料ルール/指標versionと算出由来を明示し、古いscoresフィールドを符号付き報酬に上書きしない。平均得点というUI名称の曖昧さは「5ラウンド獲得点の合計」と「終局報酬の平均」を将来区別する候補。今回は報告と文書のみ。
