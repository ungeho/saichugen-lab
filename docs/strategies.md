# 戦略の追加と初期アルゴリズム

## 追加例

```python
from strategy_arena.strategies.base import Decision
from strategy_arena.strategies.registry import register

class MyStrategy:
    name = "MyStrategy"
    version = "1"

    def choose(self, observation, rng):
        return Decision(rng.choice(observation.legal_actions), explanation="自作戦略")

register("MyStrategy", MyStrategy)
```

登録をAPIまたは実験runnerの起動前に実行する。UIは `/api/strategies` の登録一覧を取得する。1試合につき座席ごとに戦略インスタンスを作るため、公開履歴から学んだ状態をインスタンスに保持できる。試合間で学習状態を共有する機構はまだない。

## 比較用5戦略

| 戦略 | 方針 |
| --- | --- |
| Random | 合法手から一様選択 |
| Greedy | 未知カードから相手が一様に選ぶモデルで、ターン中位となる確率を最大化 |
| Conservative | 同じモデルで獲得確率を最小化 |
| ScoreAware | 現在のラウンド得点が中央値以下なら獲得、上なら回避 |
| Heuristic | ラウンド中位からの予想距離、ゲーム得点が過大か、残り手札の選択自由度を粗く加味 |

Greedyは実際の非公開手札を使わない。ある候補札より弱い未知札をL枚、強い未知札をH枚、未知札数をUとすると、獲得確率は `2LH / (U(U−1))`。これは相手の行動傾向をモデル化しない基準値であり、現実の獲得確率の保証ではない。

Decisionには選択カードのほか、任意の獲得意図・予想獲得確率・説明を含められる。計算時間はrunnerが計測する。戦略は最終勝率の最適性を保証しない。将来は完全情報・カスタム情報用の観測を追加し、情報条件を明記して戦わせる。
