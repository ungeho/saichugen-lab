"""ルールページ用の説明。判定・得点・配札は既存エンジンを参照する。"""
from dataclasses import asdict
from .game.cards import Card, deck
from .game.engine import Game
from .game.rules import RULE_VERSION, ROUNDS_PER_GAME, TURNS_PER_ROUND, turn_winner, round_awards, median_players

SOURCES = [
    {"id": "implementation", "name": "現行ゲームエンジン", "url": None, "location": "game/engine.py の Game.winners", "status": "現行実装・原典未確認"},
    {"id": "gpcc", "name": "GPCC報告（2009年）", "url": "https://prosym.org/gpcc/files/gpcc09.pdf",
     "location": "1ページ「1 2009年の課題」最中限の段落", "status": "GPCC一次資料で確認"},
    {"id": "secondary", "name": "サン・エム・システム「AIを身近に感じよう」",
     "url": "https://www.sun-m.co.jp/blog/latest-technology/147.html",
     "location": "「用意するもの」「進行について」(1)〜(5)、末尾の残り手札の説明",
     "status": "二次資料に基づく暫定採用"},
    {"id": "approved", "name": "ユーザー承認済みの公開範囲（2026-10-13記録）", "url": None,
     "location": "docs/rules-research.md「実装時の状態一覧」、本プロジェクトの承認履歴",
     "status": "実装上の暫定仕様"},
]
RULES = [
    ("goal", "ゲームの目的", "5ラウンド後のゲーム得点が中間の人を目指します。最も高い得点を取ることが目的ではありません。", "gpcc", "median_players"),
    ("deal", "準備と配札", "3人専用。ジョーカーを除く52枚から各17枚を配り、1枚が余ります。現在の実装ではシード指定でシャッフルします。裏向き除外は次項の二次資料に基づきます。", "gpcc", "deck / deal / Game._initialize"),
    ("unused", "余り1枚", "非公開でゲームから除外します。裏向き除外は二次資料に基づきます。終局後のAPIでの扱いは公開範囲の暫定仕様です。", "secondary", "deal / Game.observe"),
    ("progress", "3ターン × 5ラウンド", "1ターンで各人が手札から1枚ずつ使います。3ターンで1ラウンド、5ラウンドで終局。最後に各人2枚が残ります。", "gpcc", "TURNS_PER_ROUND / ROUNDS_PER_GAME / Game.finished"),
    ("submission", "提出順と合法手", "裏向き提出を、全員が同じ公開局面から選ぶ同時選択として扱います。先手・リードはなく、手札のどのカードでも選べます。スートを合わせる制約はありません。計算は席順でも、途中の選択は次の人に伝えません。同時選択と自由な提出は、裏向き提出の説明に対する現在の実装上の解釈です。", "secondary", "Observation.legal_actions / API.step"),
    ("order", "カードの強さ", "数字が最優先で K > Q > J > 10 > … > 2 > A。同じ数字だけをスートで比べ、♠ > ♥ > ♦ > ♣。同じスートでも数字の大きい方が強くなります。異なる52枚にはすべて順位が付き、ターンの同点はありません。", "secondary", "Card(order=True) / turn_winner"),
    ("turn", "ターン得点", "3枚のうち中間のカードを出した人だけが、そのカードの数字をラウンド得点へ加算します。カードの数値対応は次項の二次資料に基づきます。スートで点数は増減しません。他の2人の得点は変わりません。", "gpcc", "turn_winner / Game.play"),
    ("values", "カードの数値", "A=1、2〜10はその数字、J=11、Q=12、K=13です。ターンでは中間のカードの数値だけを獲得します。", "secondary", "Card.rank / Game.play"),
    ("round", "ラウンドからゲーム得点へ", "3ターンのラウンド得点を比べ、中間の人だけが自分のラウンド得点をゲーム得点へ加算します。他の人には加算しません。その後、全員のラウンド得点を0に戻します。ゲーム得点は次のラウンドに持ち越します。", "gpcc", "round_awards / Game.play"),
    ("ties", "得点の同点・共同勝利", "ラウンドと最終ゲームでは、3人の得点を並べた中央の値と同点の全員が勝者です。2人同点ならその2人、全員同点なら3人とも勝者。勝利を分割する追加の引き分け判定はありません。0点でラウンドに勝ってもゲーム得点の増加は0です。", "secondary", "median_players / round_awards / Game.winners"),
    ("finish", "終了と最終判定", "15ターンで終了し、以降は残り2枚を出せません。ゲーム得点が中間の全員を最終勝者として返します。終局時の追加処理は下の「終局での得点保持」を参照してください。", "gpcc", "Game.finished / Game.winners"),
    ("final_storage", "終局での得点保持", "現在は5ラウンド合計をそのまま保持し、勝者を判定します。終局時に得点を再配分しません。二次資料の終局の得点表現の詳細は原典で未照合です。", "implementation", "Game.winners / Game.observe"),
    ("visibility", "知ることのできる情報", "自分の手札、全員提出後に同時公開された3枚と全履歴、公開得点、進行位置、各人の残り枚数を観測できます。相手の未公開手札・余り1枚・配札シード・未公開の提出札はStrategyへ渡しません。終局の残り手札も通常APIでは非公開です。", "approved", "Observation / Game.observe"),
    ("analysis", "終局後の分析表示", "終了後に明示的な分析表示を開くと、他席の当時の判断ログ・候補手札や履歴局面の視点を確認できます。これは閲覧用の拡張で、対戦中のStrategyの観測条件は変わりません。研究用完全リプレイは別経路です。", "approved", "API.view / check_comparison_player / research.replay"),
]

def judge(cards):
    cards = tuple(cards)
    winner = turn_winner(cards)
    change = tuple(cards[winner].rank if p == winner else 0 for p in range(3))
    return {"cards": [asdict(c) for c in cards], "weak_to_strong": sorted(range(3), key=lambda p: cards[p]),
            "winner": winner, "round_delta": change, "game_delta": (0, 0, 0),
            "rule": "数字優先、同数字はスートで比較。中間のカードの数字を獲得。",
            "explanation": f"P{winner + 1}の{cards[winner].label}が中間なので、ラウンド得点が{cards[winner].rank}増えます。ラウンド途中の例なのでゲーム得点は変わりません。"}

def round_example(title, actions):
    used = {c for turn in actions for c in turn}
    remaining = iter(c for c in deck() if c not in used)
    hands = [tuple(turn[p] for turn in actions) + tuple(next(remaining) for _ in range(14)) for p in range(3)]
    game = Game.from_deal(hands, next(remaining))
    events = [game.play(turn) for turn in actions]
    return {"title": title, "turns": [asdict(e) for e in events],
            "round_scores": events[-1].round_scores, "winners": median_players(events[-1].round_scores),
            "game_delta": events[-1].game_scores, "next_round_scores": game.observe(0).round_scores}

def rule_guide():
    initial = Game(0).observe(0)
    turn_inputs = [
        ("数字がすべて異なる", (Card(2, 3), Card(8, 0), Card(13, 2))),
        ("同じ数字はスートで決まる", (Card(7, 3), Card(7, 0), Card(7, 2))),
        ("1枚のスートが変わると勝者も変わる", (Card(7, 1), Card(7, 0), Card(7, 2))),
        ("同じスートでは数字を比較", (Card(1, 3), Card(10, 3), Card(13, 3))),
        ("数字はスートより優先", (Card(8, 0), Card(7, 3), Card(9, 1))),
    ]
    return {"rule_version": RULE_VERSION, "visibility_version": "private-hands-v1",
            "implementation_name": "GPCC資料・公開二次資料に基づく実装",
            "constants": {"players": len(initial.hand_sizes), "cards": len(deck()), "initial_hand": len(initial.hand),
                          "unused": len(deck()) - sum(initial.hand_sizes), "turns_per_round": TURNS_PER_ROUND,
                          "rounds": ROUNDS_PER_GAME, "turns": TURNS_PER_ROUND * ROUNDS_PER_GAME,
                          "remaining_hand": len(initial.hand) - TURNS_PER_ROUND * ROUNDS_PER_GAME},
            "rank_order": sorted({c.rank for c in deck()}, reverse=True),
            "suit_order": [c.suit for c in sorted((Card(1, s) for s in range(4)), reverse=True)],
            "sources": SOURCES,
            "rules": [{"id": key, "title": title, "text": text, "source": source, "implementation": impl}
                      for key, title, text, source, impl in RULES],
            "turn_examples": [{"title": title, **judge(cards)} for title, cards in turn_inputs],
            "round_examples": [
                round_example("同点の2人に加算", (
                    (Card(8, 0), Card(13, 0), Card(1, 0)),
                    (Card(1, 1), Card(8, 1), Card(13, 1)),
                    (Card(1, 2), Card(13, 2), Card(3, 0)))),
                round_example("0点で勝つと加算は0", (
                    (Card(1, 0), Card(13, 0), Card(2, 0)),
                    (Card(1, 1), Card(13, 1), Card(4, 0)),
                    (Card(1, 2), Card(13, 2), Card(6, 0))))],
            "final_examples": [{"scores": scores, "winners": median_players(scores)} for scores in
                               ((10, 25, 40), (10, 10, 4), (0, 0, 12), (6, 6, 6))],
            "uncertainties": [
                "原典全文との一致は未確認。『原典で確認済み』と断定できる項目はありません。",
                "GPCC資料と二次資料の共通記述に矛盾は見つかりませんでした。GPCCに記載のないカード順序・同点・公開手順を二次資料や承認済み仮仕様で補っています。異なるルールセットかどうかは未確認です。",
                "二次資料の終局の『勝者はその得点総計を得ます』という表現について、追加の得点管理は原典で未照合。現在は5ラウンド合計を保持して勝者だけを判定します。",
                "最初の依頼にあった17トリック・スートフォロー・固定3点・総得点51は採用していません。"],
            "examples_origin": "ターン例はturn_winner、ラウンド例はGame.play、最終例はmedian_playersで表示時に計算しています。"}

