from pathlib import Path
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from datetime import datetime

DATA_DIR = Path("/opt/arbstack/data").resolve()

def write_tick(df: pd.DataFrame, venue: str, pair: str):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d")
    file = DATA_DIR / f"{venue}_{pair}_{ts}.parquet"
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_to_dataset(table, root_path=str(file), basename_template=None)
