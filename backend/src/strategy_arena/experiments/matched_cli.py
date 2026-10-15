"""D/Eの見積もり・明示登録/開始。"""
from .stratification_cli import main
from .matched_lab import MatchedConfig,MatchedJobs,matched_estimate
if __name__=='__main__':main(MatchedConfig,MatchedJobs,matched_estimate,'research-local/matched-boundary.sqlite')
