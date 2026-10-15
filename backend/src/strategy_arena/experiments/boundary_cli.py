"""B/C/Mの既存CLI互換経路。既定は見積もりのみ。"""
from .stratification_cli import main
from .boundary_lab import BoundaryConfig,BoundaryJobs,boundary_estimate
if __name__=='__main__':main(BoundaryConfig,BoundaryJobs,boundary_estimate,'research-local/decision-boundary.sqlite')
