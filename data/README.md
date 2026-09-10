# H-1B source data

If the `refresh sponsors` workflow cannot download from USCIS (it refuses some
datacentre IPs), fetch the files by hand and put them here.

1. Open <https://www.uscis.gov/tools/reports-and-studies/h-1b-employer-data-hub>
2. Follow the **H-1B Employer Data Hub Files** link
3. Download the CSV for each fiscal year you want
4. Save them here **keeping the original names**: `h1b_datahubexport-2023.csv`, etc.
5. Commit them

The workflow checks this folder first and only reaches for the network when it is
empty. Each file is a few MB and they change once a year, so committing them is
cheap and makes the job reproducible.
