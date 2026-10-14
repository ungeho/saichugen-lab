"""既定は見積もり。登録／実行を分離する。"""
from .stratification_cli import main
from .runtime_lab import RuntimeConfig,RuntimeJobs,runtime_estimate
if __name__=='__main__':main(RuntimeConfig,RuntimeJobs,runtime_estimate,'research-local/runtime.sqlite')
