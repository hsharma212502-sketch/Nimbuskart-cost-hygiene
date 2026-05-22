# Walkthrough

https://www.loom.com/share/aa8129cfae804c8992395eb03b33a71b



## Suggested script (the brief requires all four beats)

1. **Start LocalStack + apply Terraform live.**
   - `docker run --rm -d -p 4566:4566 --name localstack localstack/localstack:3.5`
   - `cd terraform && tflocal init && tflocal apply -auto-approve`
   - Point out the orphan EBS volume ID in the outputs.

2. **Run the Janitor and walk one finding.**
   - `cd janitor && python janitor.py --dry-run --endpoint-url http://localhost:4566`
   - Open `../janitor-output/report.md`, pick the orphan EBS, explain the
     `reason`, the `age_days` calc, and the cost math (size_gb × $0.08).

3. **A design decision you're proud of.**
   - Example: the `safe_to_auto_delete=False` for stopped EC2 even after the
     threshold, so the Janitor *suggests* terminate but `--delete` never does
     it. Read out the code in `janitor.py` and `apply_deletions` so the
     reviewer can see how the kill-switch composes with the `Protected=true`
     tag.

4. **One thing you'd change.**
   - Example: static pricing in `constants.py`. Show the file, then point at
     DESIGN.md §1 where the per-cloud `pricing/` module would live.

## Transcript

(Optional — paste a transcript here if you want to make the reviewer's life
easier; not required by the brief.)
