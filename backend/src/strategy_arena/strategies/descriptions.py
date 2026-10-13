"""図鑑の解説はここで一度だけ定義。計算ログとは区別する。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ParameterDescription:
    name: str
    meaning: str
    default: str


@dataclass(frozen=True)
class AlgorithmDescription:
    tagline: str = "説明はまだ登録されていません"
    overview: str = ""
    steps: tuple[str, ...] = ()
    information: tuple[str, ...] = ()
    strengths: tuple[str, ...] = ()
    weaknesses: tuple[str, ...] = ()
    randomness: str = "未登録"
    implementation: str = "未登録"
    parameters: tuple[ParameterDescription, ...] = ()
    examples: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


COUNTING = ("自分の手札と合法手", "公開済みカード（未知札の計算に使用）", "カードの順位")
MODEL_NOTE = "相手が未知札から無作為に出すと仮定した基準モデルです。相手の癖や実際の手札は読みません。"

DESCRIPTIONS = {
    "Random": AlgorithmDescription(
        tagline="どのカードにも同じチャンスを。",
        overview="出せるカードの中から、どれも同じ確率で1枚選びます。得点やカードの強さで選び分けません。",
        steps=("出せるカードを確認する。", "その中から一様な乱数で1枚を選ぶ。"),
        information=("自分の合法手",), strengths=("他の戦略と比べるための基準になります。",),
        weaknesses=("得点順位や残りターンを見て方針を変えません。",),
        randomness="毎回、合法手から無作為に選びます。", implementation="ランダム",
        examples=("合法手が3枚なら、それぞれを選ぶ確率は1/3です。評価点は付けません。",),
    ),
    "Greedy": AlgorithmDescription(
        tagline="今のターンを、とにかく取りにいく。",
        overview="未知札の中に各候補より弱い札と強い札が何枚あるかを数え、中位になりやすいカードを選びます。",
        steps=("自分の手札と公開札を52枚から除き、未知札を求める。", "候補ごとに弱い未知札と強い未知札を数える。",
               "相手の2枚に挟まれて中位になる確率を計算する。", "確率が最大の候補から1枚選ぶ。"),
        information=COUNTING, strengths=("今のターンの獲得を優先したい局面に狙いが合います。",),
        weaknesses=("取りすぎでゲーム得点が首位になっても回避しません。",),
        randomness="最高評価が同じ候補から無作為に1枚選びます。", implementation="ルールベース（カードカウンティング）",
        examples=("ある候補より上と下の未知札が多ければ、相手2人の札に挟まれやすいと考えます。",),
        notes=(MODEL_NOTE, "ゲーム勝率で優位とは限りません。"),
    ),
    "Conservative": AlgorithmDescription(
        tagline="今のターンは、できるだけ譲る。",
        overview="Greedyと同じ方法で中位になる確率を計算し、その確率が最も低いカードを選びます。",
        steps=("自分の手札と公開札から未知札を求める。", "各候補が中位になる確率を計算する。",
               "確率を負の数にして評価する。", "獲得確率が最小の候補から1枚選ぶ。"),
        information=COUNTING, strengths=("今のターンを取りたくない局面に狙いが合います。",),
        weaknesses=("得点が足りなくても獲得に切り替えません。",),
        randomness="最高評価が同じ候補から無作為に1枚選びます。", implementation="ルールベース（カードカウンティング）",
        examples=("候補より弱い未知札が0枚なら、基準モデルではそのカードの獲得確率は0です。",), notes=(MODEL_NOTE,),
    ),
    "ScoreAware": AlgorithmDescription(
        tagline="点が少なければ取り、多ければ譲る。",
        overview="現在のラウンド得点で、自分が中位以下なら獲得を狙い、中位より上なら獲得を避けます。",
        steps=("3人のラウンド得点の中央値を調べる。", "自分の得点が中央値以下なら獲得、上なら回避を選ぶ。",
               "各候補の獲得確率に方針の符号（+1または−1）を掛ける。", "その評価が最大の候補から1枚選ぶ。"),
        information=COUNTING + ("現在のラウンド得点",), strengths=("ラウンド中の取りすぎ・取り足りなさで行動を変えます。",),
        weaknesses=("ゲーム全体の得点や残りターン数は選択に使いません。",),
        randomness="最高評価が同じ候補から無作為に1枚選びます。", implementation="ルールベース（得点による方針切替）",
        examples=("ラウンド得点が(8,3,1)で自分が8点なら譲り、3点なら獲得を狙います。",), notes=(MODEL_NOTE,),
    ),
    "Heuristic": AlgorithmDescription(
        tagline="今の得点と、次に残すカードを一緒に考える。",
        overview="獲得・回避の方針に、目標得点からの予想距離と、残す手札がランク7からどれだけ離れているかを加えて各カードを点数化します。",
        steps=("ラウンド得点を見て獲得・回避を決める。ゲーム得点が中位より上なら回避へ切り替える。",
               "相手2人のラウンド得点平均に、残りターン1回につき3点を足して目標を作る。",
               "獲得した場合と譲った場合の、目標までの距離を獲得確率で重み付けする。",
               "残すカードがランク7からどれだけ離れているかの平均を求める。",
               "方針×獲得確率 − 予想距離/13 + 残す札の平均距離×0.03 が最大の候補を選ぶ。"),
        information=COUNTING + ("ラウンド得点", "ゲーム得点", "ラウンド内の残りターン数", "選択後に残る自分の手札"),
        strengths=("目先の獲得だけでなく、得点と残すカードを合わせて判断できます。",),
        weaknesses=("目標に足す3点や係数は固定で、相手の行動傾向に合わせた学習はしません。",
                    "手札のランク7からの距離は粗い基準であり、有利さの保証はありません。"),
        randomness="最高評価が同じ候補から無作為に1枚選びます。", implementation="ルールベース（複数基準の加重評価）",
        examples=("獲得確率が高くても、目標から離れる量が大きければ別の候補を選ぶことがあります。",),
        notes=(MODEL_NOTE, "3点、13、0.03は現在の固定係数です。外部から変更するパラメータは未提供です。",
               "得意・苦手は設計上の狙いです。勝率による検証済みの主張ではありません。"),
    ),
}
