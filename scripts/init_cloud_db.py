import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cloud_store import initialize
if __name__=='__main__':initialize();print('Cloud database schema initialized.')
