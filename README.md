# Blockworks to Dune Sync

This workflow uses the already-scraped historical CSV as the seed, then updates
the dataset every 24 hours with GitHub Actions.

## Files

- `data/historical_solana_spot_dex_volume_by_pair_category.csv`
  - The one-time historical seed CSV.
  - Keep this in the repo so the workflow does not need to rebuild history.
- `data/solana_spot_dex_pair_category_volume.csv`
  - The maintained state CSV.
  - The script creates this on the first run, updates it daily, uploads it to
    Dune, and the GitHub Action commits it back to the repo.
- `blockworks_dune_sync.py`
  - Reads the seed/state CSV, fetches the latest Blockworks execution, merges
    new dates plus a short lookback window, and uploads the combined CSV to
    Dune.

## GitHub Actions Setup

1. Copy this folder's contents into the root of your GitHub repo.
2. In GitHub, add a repository secret named `DUNE_API_KEY`.
3. Commit these files, including the historical seed CSV.
4. The workflow in `.github/workflows/blockworks_dune_sync.yml` runs daily at
   `02:15 UTC` and can also be run manually from the Actions tab.

The action commits only this file after each successful run:

```text
data/solana_spot_dex_pair_category_volume.csv
```

## How Updates Work

The first run reads:

```text
data/historical_solana_spot_dex_volume_by_pair_category.csv
```

Then it writes:

```text
data/solana_spot_dex_pair_category_volume.csv
```

Future runs read the maintained state CSV instead of rebuilding from the
historical seed. They merge only:

- dates newer than the current max `block_date`
- dates inside `REFRESH_LOOKBACK_DAYS`, default `7`, to catch late source updates

Blockworks' row endpoint returns a current execution snapshot, so the script
still fetches that snapshot, but it does not replace the full historical CSV
with a fresh scrape.

## Local Test

From the repo root:

```bash
SKIP_DUNE=true python blockworks_dune_sync.py
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

## Dune Table

The script uses Dune's CSV upload endpoint:

```text
POST https://api.dune.com/api/v1/uploads/csv
```

Uploading the same `DUNE_TABLE_NAME` replaces the table contents with the
current maintained CSV. Dune exposes uploaded tables as:

```sql
select *
from dune.<team_or_user_handle>.dataset_solana_spot_dex_pair_category_volume
```

## Output Columns

- `block_date`
- `sol_stablecoin_volume_usd`
- `stablecoin_swaps_volume_usd`
- `foreign_tokens_volume_usd`
- `lst_swaps_volume_usd`
- `composites_volume_usd`
- `tokenized_assets_volume_usd`
- `project_tokens_volume_usd`
- `memes_volume_usd`
- `source_execution_id`
- `scraped_at_utc`
