"""公開観測だけで強・弱を交互に消費。15手で終了し2枚は残る。"""
from .base import Decision,DecisionDetails,CandidateEvaluation
from .descriptions import AlgorithmDescription

class Zigzag:
    version='1.0.0'
    def __init__(self,reverse=False):self.reverse=reverse;self.name='Reverse Zigzag' if reverse else 'Zigzag'
    def choose(self,observation,rng):
        legal=observation.legal_actions
        if not legal:raise ValueError('合法手がありません')
        strong=(observation.turn%2==0)!=self.reverse
        card=(max if strong else min)(legal)
        return Decision(card,explanation=f'第{observation.turn+1}手：残り合法手の'+('最強' if strong else '最弱')+'を選択。得点や相手手札は使いません。')
    def choose_detailed(self,observation,rng):
        decision=self.choose(observation,rng);ordered=sorted(observation.hand,reverse=True)
        initial=sorted((*observation.hand,*observation.actions_by(observation.player)),reverse=True)
        details=DecisionDetails(candidates=tuple(CandidateEvaluation(c,explanation='強さ順の端を規則で選びます。数値評価はしません。') for c in ordered),
            reasoning=(decision.explanation,),information_used=('自分の合法手','ゲーム内手番番号','自分の公開済みカード（初期順位の復元だけ）'),
            optional_metadata={'initial_hand_rank':initial.index(decision.card)+1,'remaining_hand_rank':ordered.index(decision.card)+1,
                'side':'strongest' if (observation.turn%2==0)!=self.reverse else 'weakest','action_number':observation.turn+1})
        return Decision(decision.card,explanation=decision.explanation,details=details)

def description(reverse=False):
    return AlgorithmDescription(tagline='弱い札、強い札を交互に使う。' if reverse else '強い札、弱い札を交互に使う。',
        overview='自分が出せる札の強さだけを見て両端から使います。後半に中央の札が残る構造ですが、実際のターン2位や最終勝利は保証されません。',
        steps=('数字、同数字ならスートの順で比較する。','ゲーム内手番の偶奇で強・弱を切り替える。','ラウンドが変わっても切替順を維持する。'),
        information=('自分の合法手','ゲーム内手番番号'),strengths=('探索がなく単純・決定的。','カード消費の比較基準になる。'),
        weaknesses=('得点順位や相手の行動に適応しない。','強さの実証は未検証。'),randomness='なし',implementation='決定的な規則',
        examples=('弱→強→弱→強…' if reverse else '強→弱→強→弱…',),notes=('17枚のうち15枚を使用し、2枚は残る。','ターン2位、ラウンド2位、最終得点2位、終局報酬は別の指標。'))
