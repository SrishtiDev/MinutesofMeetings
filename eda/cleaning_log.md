# Cleaning log: dataset.csv

| Step | Check | Result |
|---|---|---|
| 1 | Starting rows | 500 |
| 2 | Missing values (all 7 columns) | 0 found, nothing removed |
| 3 | Duplicate rows / duplicate doc_id | 0 found, doc_id is unique and always in format D#####|
| 4 | Extra spaces / label spelling | none; topic_label has 7 consistent categories, source has 20 consistent values |
| 5 | Data types | correct (text, integer, float) |
| 6 | Range check (readability 0-100, lengths > 0) | all valid |
| 7 | Logic check: unique_words <= word_count | 89 rows violated this (impossible: distinct words cannot exceed total words). Removed |
| 8 | Final rows | 411 (removed rows saved in removed_rows.csv) |
