"""Series R/Dの見積もり、登録、明示実行。"""
from .stratification_cli import main
from .noise_lab import StudyConfig,StudyJobs,study_estimate
if __name__=='__main__':main(StudyConfig,StudyJobs,study_estimate,'research-local/runtime-divergence.sqlite')
