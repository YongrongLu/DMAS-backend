# Retail Rescue datasets

These files were generated from the UCI Online Retail II workbook. The original source is preserved as `raw/original_dataset.xlsx`.

`processed/cleaned_transactions.csv` is stored losslessly as `processed/cleaned_transactions.csv.gz` because the uncompressed CSV exceeds GitHub's 100 MB per-file limit. Restore it with:

```sh
gzip -dc retail_rescue/data/processed/cleaned_transactions.csv.gz > retail_rescue/data/processed/cleaned_transactions.csv
```

SHA-256 of the restored CSV: `e613ad4dbce2a046f409168ea0fccee7becd3b8e3f2953c9458284d4ec00865d`.

Each agent should receive only its department's `devices/<department>/shared/` directory. The Finance `private/employee_salaries.csv` file is a synthetic privacy-test fixture; GitHub storage does not enforce the demo's per-agent file access policy. Never mount `private/`, `raw/`, or `processed/` in an agent's authorized data root.
