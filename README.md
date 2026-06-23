# Blockworks to Dune Sync

This workflow uses already-scraped historical CSVs as seeds, then updates the
datasets every 24 hours with GitHub Actions.

Both Dune tables are stored in long format so they are easy to query.

## Datasets

| Dataset key | Blockworks chart | State CSV | Dune table | Columns |
| --- | --- | --- | --- | --- |
| `pair_category` | Solana: Spot DEX Volume by Pair Category | `data/solana_spot_dex_pair_category_volume.csv` | `solana_spot_dex_pair_category_volume` | `block_date`, `type`, `volume` |
| `spot_volume_by_dex` | Solana: Spot Volume by DEX | `data/solana_spot_volume_by_dex.csv` | `solana_spot_volume_by_dex` | `block_date`, `dex`, `volume` |

Historical seed CSVs:

- `data/historical_solana_spot_dex_volume_by_pair_category.csv`
- `data/historical_solana_spot_volume_by_dex.csv`

Maintained state CSVs:

- `data/solana_spot_dex_pair_category_volume.csv`
- `data/solana_spot_volume_by_dex.csv`

## GitHub Actions Setup

1. Add a repository secret named `DUNE_API_KEY`.
2. Keep the historical seed CSVs committed to the repo.
3. The workflow in `.github/workflows/blockworks_dune_sync.yml` runs daily at
   `15:00 Turkey time` (`12:00 UTC`) and can also be run manually from the
   Actions tab.

The action uploads both maintained CSVs to Dune, then commits any updated CSVs
back to the repo.

## How Updates Work

For each dataset, the first run reads the historical seed CSV and writes the
maintained state CSV. Future runs read the maintained state CSV instead of
rebuilding history.

Each run merges only:

- dates newer than the current max `block_date`
- dates inside `REFRESH_LOOKBACK_DAYS`, default `7`, to catch late source updates

The DEX table uses Blockworks' `total_exchange_*` columns only, because the same
chart also contains prop-AMM and orderbook subgroup columns that would double
count volume if summed with totals.

## Local Test

From the repo root:

```bash
SKIP_DUNE=true python blockworks_dune_sync.py
```

To test only one dataset:

```bash
SKIP_DUNE=true python blockworks_dune_sync.py --datasets spot_volume_by_dex
```

On Windows PowerShell:

```powershell
$env:SKIP_DUNE = "true"
python .\blockworks_dune_sync.py
```

To upload to Dune locally:

```powershell
$env:DUNE_API_KEY = "your_key_here"
python .\blockworks_dune_sync.py
```

## Dune Tables

The script uses Dune's CSV upload endpoint:

```text
POST https://api.dune.com/api/v1/uploads/csv
```

Uploading the same table name replaces the table contents with the current
maintained CSV. Dune exposes uploaded tables as:

```sql
select block_date, type, volume
from dune.<team_or_user_handle>.dataset_solana_spot_dex_pair_category_volume;

select block_date, dex, volume
from dune.<team_or_user_handle>.dataset_solana_spot_volume_by_dex;
```

Example daily totals:

```sql
select block_date, sum(volume) as volume
from dune.<team_or_user_handle>.dataset_solana_spot_volume_by_dex
group by 1
order by 1;
```
