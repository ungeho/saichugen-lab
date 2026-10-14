"""見積もり・登録・Hash固定実行。最終評価seedは使用しない。"""
from .stratification_cli import main
from .adaptive_lab import AdaptiveConfig,AdaptiveJobs,adaptive_estimate

if __name__=='__main__':main(AdaptiveConfig,AdaptiveJobs,adaptive_estimate,'research-local/adaptive.sqlite')
