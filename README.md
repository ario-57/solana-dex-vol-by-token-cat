# Blockworks to Dune Sync

This workflow uses already-scraped historical CSVs as seeds, then updates the
datasets every 24 hours with GitHub Actions.

## Datasets

| Dataset key | Blockworks chart | State CSV | Dune table |
| --- | --- | --- | --- |
| `pair_category` | Solana: Spot DEX Volume by Pair Category | `data/solana_spot_dex_pair_category_volume.csv` | `solana_spot_dex_pair_category_volume` |
| `spot_volume_by_dex` | Solana: Spot Volume by DEX | `data/solana_spot_volume_by_dex.csv` | `solana_spot_volume_by_dex` |

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
   `02:15 UTC` and can also be run manually from the Actions tab.

The action uploads both maintained CSVs to Dune, then commits any updated CSVs
back to the repo.

## How Updates Work

For each dataset, the first run reads the historical seed CSV and writes the
maintained state CSV. Future runs read the maintained state CSV instead of
rebuilding history.

Each run merges only:

- dates newer than the current max `block_date`
- dates inside `REFRESH_LOOKBACK_DAYS`, default `7`, to catch late source updates

Blockworks' row endpoint returns a current execution snapshot, so the script
still fetches that snapshot, but it does not replace full history with a fresh
scrape.

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
select *
from dune.<team_or_user_handle>.dataset_solana_spot_dex_pair_category_volume;

select *
from dune.<team_or_user_handle>.dataset_solana_spot_volume_by_dex;
```

## Pair-Category Columns

- `block_date`
- `sol_stablecoin_volume_usd`
- `stablecoin_swaps_volume_usd`
- `foreign_tokens_volume_usd`
- `lst_swaps_volume_usd`
- `composites_volume_usd`
- `tokenized_assets_volume_usd`
- `project_tokens_volume_usd`
- `memes_volume_usd`

## Spot-Volume-by-DEX Columns

- `block_date`
- `total_exchange_humidifi_volume_usd`
- `total_exchange_orca_volume_usd`
- `total_exchange_bisonfi_volume_usd`
- `total_exchange_zerofi_volume_usd`
- `total_exchange_solfi_volume_usd`
- `total_exchange_tessera_volume_usd`
- `total_exchange_pump_volume_usd`
- `total_exchange_raydium_volume_usd`
- `total_exchange_meteora_volume_usd`
- `total_exchange_goonfi_volume_usd`
- `total_exchange_jupiterz_volume_usd`
- `total_exchange_alphaq_volume_usd`
- `total_exchange_manifest_volume_usd`
- `total_exchange_obric_volume_usd`
- `total_exchange_phoenix_volume_usd`
- `total_exchange_aquifer_volume_usd`
- `total_exchange_scorch_volume_usd`
- `total_exchange_lifinity_volume_usd`
- `total_exchange_other_volume_usd`
- `type_propamm_exchange_humidifi_volume_usd`
- `type_propamm_exchange_tessera_volume_usd`
- `type_propamm_exchange_bisonfi_volume_usd`
- `type_propamm_exchange_solfi_volume_usd`
- `type_propamm_exchange_zerofi_volume_usd`
- `type_propamm_exchange_goonfi_volume_usd`
- `type_propamm_exchange_alphaq_volume_usd`
- `type_propamm_exchange_scorch_volume_usd`
- `type_propamm_exchange_obric_volume_usd`
- `type_propamm_exchange_rubicon_volume_usd`
- `type_propamm_exchange_aquifer_volume_usd`
- `type_propamm_exchange_lifinity_volume_usd`
- `type_propamm_exchange_obsidian_volume_usd`
- `type_orderbook_exchange_manifest_volume_usd`
- `type_orderbook_exchange_phoenix_volume_usd`
