"""診断元を含む見積もり・登録・明示実行。"""
from .stratification_cli import main
from .reliability_lab import ReliabilityConfig,ReliabilityJobs,reliability_estimate

if __name__=='__main__':main(ReliabilityConfig,ReliabilityJobs,reliability_estimate,'research-local/reliability.sqlite')
