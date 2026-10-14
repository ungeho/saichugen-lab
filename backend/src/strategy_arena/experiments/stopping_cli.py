"""既定は見積もり。検証条件の登録とHash固定実行を分離する。"""
from .stratification_cli import main
from .stopping_lab import StoppingConfig,StoppingJobs
from .adaptive_lab import adaptive_estimate

if __name__=='__main__':main(StoppingConfig,StoppingJobs,adaptive_estimate,'research-local/stopping.sqlite')
