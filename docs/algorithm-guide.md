# アルゴリズム図鑑と判断ログ

## 既存機能との関係

ゲームエンジンとカード順位・得点のルールは変更しない。Strategyの `choose(observation, rng)` とDecisionの既存5フィールドは維持する。説明は戦略登録に、選択時の計算記録はDecisionに、表示時点の復元は既存の公開履歴に追加する。

## 図鑑への登録

```python
from strategy_arena.strategies.base import Decision
from strategy_arena.strategies.descriptions import AlgorithmDescription
from strategy_arena.strategies.registry import register

class FirstCard:
    name = "FirstCard"
    version = "1"

    def choose(self, observation, rng):
        return Decision(observation.legal_actions[0], explanation="手札の先頭を選びました")

register("FirstCard", FirstCard, description=AlgorithmDescription(
    tagline="先頭のカードを出す。",
    overview="合法手の配列で最初にあるカードを選びます。",
    steps=("合法手を確認する。", "最初の要素を選ぶ。"),
    information=("自分の合法手",),
    randomness="なし",
    implementation="ルールベース",
))
```

第三引数は省略できる。説明不足でも登録・対戦でき、図鑑に「未登録」と表示する。既存5戦略の説明は `strategies/descriptions.py` にまとめ、フロントエンドや各APIには同じ文章を書かない。バージョンは戦略インスタンスのversionを取得する。

ParameterDescriptionはパラメータ名・意味・既定値の説明。図鑑自体は設定変更UIではない。現在の基本5戦略は外部設定パラメータを持たず、Heuristicの固定係数を調整可能であるかのようには表示しない。

## 任意の詳細判断

既存戦略はchooseのままでよい。詳細を提供する戦略だけ `choose_detailed(observation, rng)` を実装し、Decisionの末尾に追加したdetailsを返す。

| フィールド | 意味 |
| --- | --- |
| Decision.card | 選択した行動。従来フィールドをそのまま利用 |
| Decision.explanation | 実際の選択理由。空なら未提供と表示 |
| Decision.details | 任意のDecisionDetails。未提供ならNone |
| details.candidates | 実際に扱った候補のCandidateEvaluation一覧 |
| candidate.card / score | カードと評価値。評価しない場合はscore=None |
| candidate.explanation / components | 候補の評価理由と、実計算に使った数値の内訳 |
| details.reasoning | 実際に行った判断手順 |
| details.score_label | 評価値の意味・尺度・優先方向 |
| details.information_used | 実際に使った情報 |
| details.estimates | 推定・仮定の説明。真の手札の代用品と断定しない |
| details.optional_metadata | JSON保存可能な追加情報 |
| record.context | 実行環境が残す判断前の得点・残り枚数・公開履歴長・未知札数 |

`decide` が詳細有効時にだけchoose_detailedを呼ぶ。詳細メソッドがなければchooseに戻す。**詳細メソッドは同じ入力・乱数状態で通常メソッドと同じ行動と乱数消費を保つこと。** 選択をやり直して理由を後付けする方式は使わない。初期5戦略は共通の計算経路で、途中の値を有効時だけ保存する。

Randomは合法手から一様選択したこととその候補だけを記録し、評価値を作らない。その他の戦略は実際のvaluesと同じ値を候補へ記録する。同点判定は評価差1e-12未満。UIでは小数第6位まで表示するが、判定に丸めた値は使わない。候補の尺度はその戦略の内部基準であり、戦略間の強さを表す共通スコアではない。

戦略が「詳細なし」であればdetails_statusはnot_provided、記録無効ならdisabled。相手の詳細をまだ開いていない場合はhiddenとする。

## APIと公開範囲

- `GET /api/strategies`: 従来どおり名前の配列。
- `GET /api/algorithms`: 登録戦略の図鑑情報と実バージョン。
- `GET /api/algorithms/{name}/statistics`: SQLite保存結果からの条件別成績。
- `POST /api/games`: capture_detailsを受理。ゲーム画面では既定true。
- `GET /api/games/{id}?analysis=true`: ゲーム終了後だけ相手の詳細も表示する。対戦中はtrueでも表示しない。
- `POST /api/experiments`: capture_detailsは既定false。trueの場合のみ各試合へdecision_traceを保存。

通常の対戦APIでは本人の詳細だけを返す。終了後の明示的な分析表示は候補手札を含むため、当時の非公開手札も閲覧可能になる。これは振り返り用の表示で、Strategyへの観測・情報条件imperfectとは別。過去に承認した「終局後も対戦APIで手札を自動公開しない」方針は既定表示で維持し、今回の候補可視化は明示的な終了後分析に限定する。

contextは実行環境の記録であり、その全項目を戦略が参照したことは意味しない。図鑑の解説、選択時の戦略の計算記録、実行環境が保存する文脈は表示を分ける。過去の公開情報は選択ターンの直前までとし、未来の公開札を混ぜない。

## 履歴と成績

画面は既存のPublicTurnとDecision配列を同じターン番号で対応させる。得点・本人の手札は公開行動からその時点へ復元する。過去表示中の新しい手の送信は無効にし、最新へ戻してから対戦を続ける。

成績はルール、情報条件、本人と相手全員のバージョン、相手の組合せ（同名の人数も保持）、記録済み設定をキーに分ける。旧データの設定未記録と新しい既定設定を別に扱う。ルール・情報条件・バージョン・結果形式が不足する実験は合算せず、対象外件数を表示する。

対戦回数は保存実験内の試合数、参加回数は戦略が占めた席数。同じ戦略が1試合に2席いる場合、対戦回数と参加回数は異なる。勝率と平均得点は参加席ごと。再実行して保存した試合も含め、独立な試合数であるとは主張しない。勝率の信頼区間はこの図鑑集計では提供しない。

## 性能と既知の制限

バッチ既定経路では詳細メソッド・文脈生成・Decisionのシリアライズを呼ばない。時間の合計だけを保持する。詳細を有効にすると候補数に応じてログサイズと実行時間が増えるため、少数試合から試す。

現在の図鑑は登録中バージョンの説明。過去バージョンの説明文は保存していない。ゲームセッションの詳細はメモリ上にあり、サーバー再起動で失われる。既存の完全リプレイはカード配置・行動を再現するが、判断理由を再生成しない。バッチで保存したdecision_traceや過去ファイルの読み込み・再生UIは未対応。

成績は現在のJSON形式のSQLiteを順に読んで集計する。実験数が非常に多くなったら索引や集計キャッシュを追加する。現在は複雑なDB移行を導入しない。

同じObservationを複数戦略へ渡す機能は、後続の [同一局面比較](position-comparison.md) として追加した。先に人間が選ぶ比較、AI生成戦略の登録自動化、説明・判断のバージョン履歴は今後の拡張候補。

## 今回の変更ファイル

| 対象 | ファイル（リポジトリ相対） |
| --- | --- |
| 説明登録・詳細判断 | backend/src/strategy_arena/strategies/base.py、baselines.py、registry.py、descriptions.py |
| API・成績・バッチ | backend/src/strategy_arena/api/app.py、experiments/catalog_statistics.py、storage.py、runner.py、cli.py |
| 図鑑・簡易説明 | frontend/src/features/algorithms/AlgorithmCatalog.tsx、AlgorithmQuickView.tsx |
| 判断パネル・履歴 | frontend/src/features/game/DecisionInspector.tsx、frontend/src/history.ts |
| 画面統合・型・見た目 | frontend/src/main.tsx、model.ts、style.css |
| テスト | backend/tests/test_algorithm_catalog.py、fixtures/baseline_v1.json、frontend/src/history.test.ts、frontend/e2e/algorithms.spec.ts |
| 日本語資料 | README.md、docs/algorithm-guide.md、strategies.md、rules-research.md、validation.md |

Windows用setup.ps1・dev.ps1は既存のまま使用し、起動も検証した。ゲームエンジンは変更していない。
