"""通常は見積もりのみ。登録と実行は明示指定する。"""
from .stratification_cli import main
from .decision_lab import DecisionConfig,DecisionJobs,decision_estimate

if __name__=='__main__':main(DecisionConfig,DecisionJobs,decision_estimate,'research-local/decision.sqlite')
