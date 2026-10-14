"""既定は見積もり。登録と明示実行を分離。"""
from .stratification_cli import main
from .horizon_lab import HorizonConfig,HorizonJobs,horizon_estimate

if __name__=='__main__':main(HorizonConfig,HorizonJobs,horizon_estimate,'research-local/horizon.sqlite')
