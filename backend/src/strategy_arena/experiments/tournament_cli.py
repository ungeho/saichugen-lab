"""最終大会も既定は見積もりだけ。登録・実行を明示する。"""
from .stratification_cli import main
from .tournament import TournamentConfig,TournamentJobs,estimate
if __name__=="__main__":main(TournamentConfig,TournamentJobs,estimate,"research-local/tournament.sqlite")
